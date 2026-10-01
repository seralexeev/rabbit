import z from 'zod';

import { reader, select } from './clickhouse.ts';
import { forgeTool } from './forge_tool.ts';
import { isSeries, loadGraph } from './graph/graph.ts';
import { fetchSeries, gridFor } from './graph/series.ts';
import { round, sparkline } from './graph/stats.ts';
import { type TimeWindow, resolveWindow, toIso } from './moment.ts';
import { epochMs, table } from './output.ts';
import { runSlab } from './slabs/run_slab.ts';

const MAX_SPAN_S = 15 * 60;
const MAX_BINS = 600;
const MAX_EVENTS = 200;
const RARE_INFO = 3;
const SILENCE_S = 1.5;
const DETAIL_CHARS = 240;

type EventKind = 'command' | 'state' | 'operator' | 'config' | 'log';

export type TimelineEvent = {
  t: string;
  offset_s: number | null;
  kind: EventKind;
  source: string;
  what: string;
  detail: string;
};

type Raw = Omit<TimelineEvent, 'offset_s'>;

const WINDOW_SQL =
  'ts >= fromUnixTimestamp64Milli({from_ms:Int64}) AND ts < fromUnixTimestamp64Milli({to_ms:Int64})';

const clip = (text: string) =>
  text.length > DETAIL_CHARS ? `${text.slice(0, DETAIL_CHARS)}...` : text;

const query = async <T>(sql: string, window: TimeWindow) =>
  await select<T>(reader, sql, { from_ms: window.from, to_ms: window.to });

const changes = async (
  window: TimeWindow,
  table: string,
  value: string,
  kind: EventKind,
  source: string,
  describe: (row: { t: string; value: string; previous: string }) => string,
): Promise<Raw[]> =>
  (
    await query<{ t: string; value: string; previous: string }>(
      `SELECT toString(ts) AS t, value, previous FROM (
        SELECT ts, toString(${value}) AS value,
          lagInFrame(toString(${value}), 1, '') OVER (ORDER BY ts ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) AS previous
        FROM ${table} WHERE ${WINDOW_SQL}
      ) WHERE value != previous ORDER BY ts`,
      window,
    )
  ).map((row) => ({ t: row.t, kind, source, what: describe(row), detail: '' }));

const commandEvents = async (window: TimeWindow): Promise<Raw[]> => {
  const [nav, other, stops, joy] = await Promise.all([
    query<{
      t: string;
      event: string;
      source: string;
      steps: string;
      goal: string;
    }>(
      `SELECT toString(ts) AS t, toString(event) AS event, source, steps,
        if(goal_x IS NULL, '', concat('x ', toString(goal_x), ', z ', toString(goal_z))) AS goal
      FROM nav_events WHERE ${WINDOW_SQL} ORDER BY ts`,
      window,
    ),
    query<{ t: string; subject: string; source: string; payload: string }>(
      `SELECT toString(ts) AS t, subject, source, payload FROM command_events WHERE ${WINDOW_SQL} ORDER BY ts`,
      window,
    ),
    query<{ t: string; source: string; count: string }>(
      `SELECT toString(toStartOfSecond(ts)) AS t, source, count() AS count
      FROM drive WHERE ${WINDOW_SQL} AND source != 'nav' AND speed = 0
      GROUP BY t, source ORDER BY t`,
      window,
    ),
    changes(
      window,
      'joy',
      "if(abs(throttle) > 0.08 OR abs(steer) > 0.08, 'active', 'released')",
      'command',
      'gamepad',
      (row) =>
        row.value === 'active' ? 'gamepad input started' : 'gamepad released',
    ),
  ]);
  return [
    ...nav.map((row) => ({
      t: row.t,
      kind: 'command' as const,
      source: row.source === '' ? 'unknown' : row.source,
      what: `nav ${row.event}`,
      detail: clip(row.steps === '' ? row.goal : row.steps),
    })),
    ...other.map((row) => ({
      t: row.t,
      kind: 'command' as const,
      source: row.source,
      what: row.subject.replace('rabbit.', ''),
      detail: clip(row.payload),
    })),
    ...stops.map((row) => ({
      t: row.t,
      kind: 'command' as const,
      source: row.source === '' ? 'unknown' : row.source,
      what: 'stop (zero drive command)',
      detail: `${row.count} messages`,
    })),
    ...joy.filter((row, i) => i > 0 || row.what !== 'gamepad released'),
  ];
};

const stateEvents = async (window: TimeWindow): Promise<Raw[]> => {
  const range = { from: toIso(window.from), to: toIso(window.to) };
  const [nav, explore, tracking, wifi, silences] = await Promise.all([
    runSlab('nav_transitions', { run_id: window.run_id, ...range }, 2000),
    changes(
      window,
      'explore_state',
      "concat(phase, if(message = '', '', concat(': ', message)))",
      'state',
      'explore',
      (row) => `exploration ${row.value}`,
    ),
    changes(
      window,
      'zed_health',
      "concat(tracking_state, ' / pose ', pose_state)",
      'state',
      'rabbit-zed',
      (row) => `tracking ${row.value}`,
    ),
    changes(
      window,
      'wifi',
      "if(connected, 'connected', 'disconnected')",
      'state',
      'telemetry',
      (row) => `wifi ${row.value}`,
    ),
    query<{ t: string; gap_s: number }>(
      `SELECT toString(ts) AS t, gap_s FROM (
        SELECT ts, dateDiff('millisecond', lagInFrame(ts, 1, ts) OVER (ORDER BY ts ROWS BETWEEN 1 PRECEDING AND CURRENT ROW), ts) / 1000 AS gap_s
        FROM operator_heartbeat WHERE ${WINDOW_SQL}
      ) WHERE gap_s > ${SILENCE_S} ORDER BY ts`,
      window,
    ),
  ]);
  return [
    ...nav.rows.map((row) => ({
      t: String(row.t),
      kind: 'state' as const,
      source: 'nav',
      what: `${String(row.kind).replace('_', ' ')} ${String(row.value)}`.trim(),
      detail: `speed command ${String(row.speed_command)}, free distance ${String(row.free_distance)} m`,
    })),
    ...explore,
    ...tracking,
    ...wifi,
    ...silences.map((row) => ({
      t: row.t,
      kind: 'operator' as const,
      source: 'hud',
      what: `heartbeat resumed after ${round(row.gap_s)} s of silence`,
      detail: '',
    })),
  ];
};

const configEvents = async (window: TimeWindow): Promise<Raw[]> =>
  (
    await query<{ t: string; key: string; operation: string; value: string }>(
      `SELECT toString(ts) AS t, key, operation, value FROM kv_changes FINAL WHERE ${WINDOW_SQL} ORDER BY ts`,
      window,
    )
  ).map((row) => ({
    t: row.t,
    kind: 'config',
    source: 'kv',
    what: `${row.key} ${row.operation.toLowerCase()}`,
    detail: clip(row.value),
  }));

const logEvents = async (window: TimeWindow): Promise<Raw[]> =>
  (
    await query<{
      t: string;
      last: string;
      source_node: string;
      severity: string;
      message: string;
      records: string;
      exception_type: string;
      container: string;
      exit_code: string;
    }>(
      `SELECT toString(min(ts)) AS t, toString(max(ts)) AS last, any(node) AS source_node,
        toString(max(level)) AS severity, argMin(message, ts) AS message,
        sum(1 + repeats) AS records, any(exception_type) AS exception_type,
        fields['container'] AS container, any(fields['exit_code']) AS exit_code
      FROM logs WHERE ${WINDOW_SQL} AND level >= 'info'
      GROUP BY fingerprint, container
      HAVING max(level) >= 'warning' OR sum(1 + repeats) <= ${RARE_INFO}
      ORDER BY min(ts)`,
      window,
    )
  ).map((row) => ({
    t: row.t,
    kind: 'log',
    source: row.source_node,
    what: `${row.severity}: ${clip(row.message)}${row.container === '' ? '' : ` ${row.container}`}${row.exit_code === '' ? '' : ` with code ${row.exit_code}`}`,
    detail: [
      Number(row.records) > 1
        ? `${row.records} times until ${row.last.slice(11)}`
        : '',
      row.exception_type,
    ]
      .filter((part) => part.length > 0)
      .join(', '),
  }));

export const windowEvents = async (
  window: TimeWindow,
): Promise<TimelineEvent[]> => {
  const groups = await Promise.all([
    commandEvents(window),
    stateEvents(window),
    configEvents(window),
    logEvents(window),
  ]);
  const ranked = groups
    .flat()
    .toSorted((a, b) => (a.kind === 'log' ? 1 : 0) - (b.kind === 'log' ? 1 : 0))
    .slice(0, MAX_EVENTS);
  return ranked
    .map((event) => {
      const ms = epochMs(event.t);
      return {
        ...event,
        offset_s:
          ms == null || window.at == null
            ? null
            : round((ms - window.at) / 1000),
      };
    })
    .toSorted((a, b) => a.t.localeCompare(b.t));
};

const windowMetrics = async (window: TimeWindow, points: number) => {
  const nodes = [...loadGraph().nodes.values()].filter(isSeries);
  const span = { first: window.from, last: window.to - 1 };
  const hz = Math.min(10, MAX_BINS / ((window.to - window.from) / 1000));
  const grid = gridFor(span, hz);
  const sampled = await fetchSeries(
    nodes,
    { run_id: window.run_id, from: toIso(window.from), to: toIso(window.to) },
    grid,
  );
  const moved = [];
  const steady: Record<string, string> = {};
  const noData: string[] = [];
  for (const node of nodes) {
    const series = sampled.get(node.id);
    const values =
      series?.values.filter((_, i) => series.observed[i] === true) ?? [];
    if (series == null || values.length === 0) {
      noData.push(node.id);
      continue;
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    if (max - min <= 3 * node.floor) {
      steady[node.id] = `${round((min + max) / 2)} ${node.unit}`;
      continue;
    }
    moved.push({
      id: node.id,
      group: node.group,
      unit: node.unit,
      min: round(min),
      max: round(max),
      mean: round(
        values.reduce((sum, value) => sum + value, 0) / values.length,
      ),
      last: round(values.at(-1) ?? Number.NaN),
      spark: sparkline(series.values, points),
    });
  }
  return { moved, steady, no_data: noData };
};

export const timelineTool = forgeTool({
  title: 'Timeline',
  description: `Everything that happened around a moment or in a short range (at most 15 minutes), on one clock: commands and who sent them (gamepad, drive stops, navigation goals, missions and cancels, exploration starts, map saves), state transitions (navigation mode, safety faults and missions, exploration phase, camera tracking, Wi-Fi), HUD heartbeat silences, robot configuration changes such as camera settings, and log records (all warnings and errors, plus rare info messages), each with its offset in seconds from at. It also summarises every metric of the metric graph over the window: the ones that moved with min, max, mean, last and a sparkline, the steady ones with their level, and those without data. Use it first to orient around an event before investigate, detect_anomalies or slabs.`,
  input: z.object({
    at: z
      .string()
      .optional()
      .describe(
        'Moment, HH:MM[:SS] UTC; the window is before_s before to after_s after it',
      ),
    before_s: z.number().int().min(1).max(600).default(30),
    after_s: z.number().int().min(0).max(300).default(10),
    from: z.string().optional().describe('Start of a range instead of at, UTC'),
    to: z.string().optional().describe('End of the range, UTC'),
    run_id: z
      .string()
      .optional()
      .describe('Run id; omitted, the run containing at, else latest'),
    spark_points: z.number().int().min(8).max(60).default(20),
  }),
  run: async (input) => {
    const window = await resolveWindow(input, input, MAX_SPAN_S);
    const [events, metrics] = await Promise.all([
      windowEvents(window),
      windowMetrics(window, input.spark_points),
    ]);
    return {
      ...table(events, {
        title: `Timeline ${toIso(window.from)} to ${toIso(window.to)} UTC`,
        truncated: events.length >= MAX_EVENTS,
      }),
      window: {
        run_id: window.run_id,
        from: toIso(window.from),
        to: toIso(window.to),
        at: window.at == null ? null : toIso(window.at),
      },
      metrics,
    };
  },
});

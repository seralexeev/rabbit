import z from 'zod';

import { reader, select } from './clickhouse.ts';
import { forgeTool } from './forge_tool.ts';
import { resolveWindow, toIso } from './moment.ts';
import { table } from './output.ts';
import { resolveRunId } from './runs.ts';

const LEVELS = ['debug', 'info', 'warning', 'error', 'critical'] as const;
const MAX_WINDOW_S = 6 * 3600;
const EXCEPTION_TAIL = 800;

const Level = z
  .enum(LEVELS)
  .describe('Lowest level to include: debug, info, warning, error or critical');

const Node = z
  .string()
  .optional()
  .describe(
    'Only this node: rabbit-zed, nav, explore, roboclaw, steering, ina4235 or telemetry',
  );

type Scope = { where: string; params: Record<string, unknown> };

const scopeFor = async (input: {
  run_id?: string | undefined;
  at?: string | undefined;
  from?: string | undefined;
  to?: string | undefined;
  node?: string | undefined;
  min_level: string;
  text?: string | undefined;
}): Promise<Scope> => {
  const conditions = ['level >= {min_level:String}'];
  const params: Record<string, unknown> = { min_level: input.min_level };
  if (input.at != null || input.from != null || input.to != null) {
    const window = await resolveWindow(
      input,
      { before_s: 300, after_s: 60 },
      MAX_WINDOW_S,
    );
    conditions.push(
      'ts >= fromUnixTimestamp64Milli({from_ms:Int64})',
      'ts < fromUnixTimestamp64Milli({to_ms:Int64})',
    );
    params.from_ms = window.from;
    params.to_ms = window.to;
  } else {
    conditions.push('run_id = {run_id:String}');
    params.run_id = await resolveRunId(input.run_id ?? 'latest');
  }
  if (input.node != null) {
    conditions.push('node = {node:String}');
    params.node = input.node;
  }
  if (input.text != null && input.text.trim().length > 0) {
    conditions.push(
      '(hasAllTokens(message, {text:String}) OR hasAllTokens(exception, {text:String}))',
    );
    params.text = input.text;
  }
  return { where: conditions.join(' AND '), params };
};

export const searchLogsTool = forgeTool({
  title: 'Search logs',
  description: `Searches the log records of every robot node (camera, navigation, exploration, motor controller, steering, power monitor, telemetry, and container starts, exits and crashes). Words in text must all appear in the message or the traceback, case-insensitive (whole words, e.g. "roboclaw error" or "relocalization"). Without at, from or to it searches the run (default latest); with them it searches that time range across runs (at alone covers 5 minutes before to 1 minute after). By default records of the same kind are grouped: one row per kind with the count (suppressed repeats included), first and last time, the latest message and exception. Set grouped false for individual records. Use log_summary first for an overview, and logs_around to read what happened at one moment.`,
  input: z.object({
    text: z
      .string()
      .optional()
      .describe('Words that must all appear; omit to list everything'),
    node: Node,
    min_level: Level.default('info'),
    run_id: z
      .string()
      .optional()
      .describe("Run id, 'latest' or 'previous'; ignored when a time is given"),
    at: z.string().optional().describe('Moment, HH:MM[:SS] UTC robot clock'),
    from: z.string().optional().describe('Start of the range, UTC'),
    to: z.string().optional().describe('End of the range, UTC'),
    grouped: z.boolean().default(true),
    limit: z.number().int().min(1).max(200).default(30),
  }),
  run: async (input) => {
    const { where, params } = await scopeFor(input);
    const rows = input.grouped
      ? await select<Record<string, unknown>>(
          reader,
          `SELECT
            any(node) AS source_node,
            toString(max(level)) AS severity,
            sum(1 + repeats) AS records,
            toString(min(ts)) AS first_at,
            toString(max(ts)) AS last_at,
            argMax(message, ts) AS latest_message,
            argMax(exception_type, ts) AS exception_type,
            right(argMax(exception, ts), ${EXCEPTION_TAIL}) AS exception_tail,
            argMax(mission_id, ts) AS latest_mission_id,
            any(run_id) AS in_run
          FROM logs WHERE ${where}
          GROUP BY fingerprint
          ORDER BY max(level) DESC, max(ts) DESC
          LIMIT {limit:UInt32}`,
          { ...params, limit: input.limit },
        )
      : await select<Record<string, unknown>>(
          reader,
          `SELECT toString(ts) AS t, node, toString(level) AS severity, message, repeats, exception_type,
            right(exception, ${EXCEPTION_TAIL}) AS exception_tail, mission_id, toJSONString(fields) AS fields, run_id
          FROM logs WHERE ${where}
          ORDER BY ts DESC
          LIMIT {limit:UInt32}`,
          { ...params, limit: input.limit },
        );
    return table(rows, {
      title:
        input.text == null
          ? 'Robot log records'
          : `Logs matching ${input.text}`,
      truncated: rows.length === input.limit,
    });
  },
});

export const logsAroundTool = forgeTool({
  title: 'Logs around a moment',
  description: `The robot log records around one moment in time order, from every node, with each record's offset in seconds from the moment (negative is before). Use it to see what the software said just before and after an anomaly, a stall, a safety stop, a reboot or a data gap: pass at from the event or from investigate's focus. Repeated records show their suppressed count.`,
  input: z.object({
    at: z.string().describe('Moment, HH:MM[:SS] or YYYY-MM-DD HH:MM:SS, UTC'),
    before_s: z.number().int().min(1).max(1800).default(60),
    after_s: z.number().int().min(0).max(600).default(15),
    node: Node,
    min_level: Level.default('info'),
    run_id: z
      .string()
      .optional()
      .describe('Run id; omitted, the run containing at'),
    limit: z.number().int().min(1).max(300).default(120),
  }),
  run: async (input) => {
    const window = await resolveWindow(input, input, 2400);
    const conditions = [
      'ts >= fromUnixTimestamp64Milli({from_ms:Int64})',
      'ts < fromUnixTimestamp64Milli({to_ms:Int64})',
      'level >= {min_level:String}',
      ...(input.node == null ? [] : ['node = {node:String}']),
    ];
    const rows = await select<Record<string, unknown>>(
      reader,
      `SELECT toString(ts) AS t,
        round((toUnixTimestamp64Milli(ts) - {at_ms:Int64}) / 1000, 2) AS offset_s,
        node, toString(level) AS severity, message, repeats, exception_type,
        if(level >= 'error', right(exception, ${EXCEPTION_TAIL}), '') AS exception_tail,
        mission_id
      FROM logs WHERE ${conditions.join(' AND ')}
      ORDER BY ts
      LIMIT {limit:UInt32}`,
      {
        from_ms: window.from,
        to_ms: window.to,
        at_ms: window.at,
        min_level: input.min_level,
        node: input.node,
        limit: input.limit,
      },
    );
    return table(rows, {
      title: `Logs from ${toIso(window.from)} to ${toIso(window.to)} UTC`,
      truncated: rows.length === input.limit,
    });
  },
});

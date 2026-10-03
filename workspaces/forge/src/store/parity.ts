import { errorMessage } from '../errors.ts';
import { isSeries, loadGraph } from '../graph/graph.ts';
import { extent, fetchSeries, gridFor } from '../graph/series.ts';
import { investigateTool } from '../graph/tools.ts';
import { logsAroundTool, searchLogsTool } from '../logs.ts';
import { findObjectTool } from '../robot.ts';
import { type Run, listRuns } from '../runs.ts';
import { describeSchema } from '../schema.ts';
import { runSlab } from '../slabs/run_slab.ts';
import { loadSlabs } from '../slabs/slab.ts';
import { timelineTool } from '../timeline.ts';
import { type Params, recordQueries, select } from './engine.ts';

type Query = { sql: string; params: Params; source: string };

const TOLERANCE = 1e-6;

const chParam = (value: unknown): string => {
  if (value === null) {
    return '\\N';
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => (typeof item === 'string' ? `'${item.replaceAll("'", "\\'")}'` : chParam(item))).join(',')}]`;
  }
  if (typeof value === 'boolean') {
    return value ? '1' : '0';
  }
  if (typeof value === 'number' || typeof value === 'bigint') {
    return String(value);
  }
  return typeof value === 'string' ? value : JSON.stringify(value);
};

const clickhouse = async (url: string, query: Query) => {
  const search = new URLSearchParams({
    user: 'forge_reader',
    password: 'forge_reader',
    database: 'forge',
    default_format: 'JSONEachRow',
  });
  for (const [name, value] of Object.entries(query.params)) {
    if (value !== undefined) {
      search.set(`param_${name}`, chParam(value));
    }
  }
  const started = performance.now();
  const response = await fetch(`${url}/?${search.toString()}`, {
    method: 'POST',
    body: query.sql,
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(text.slice(0, 300));
  }
  return {
    ms: performance.now() - started,
    rows: text
      .trimEnd()
      .split('\n')
      .filter((line) => line.length > 0)
      .map((line) => JSON.parse(line) as Record<string, unknown>),
  };
};

const same = (a: unknown, b: unknown): boolean => {
  if (typeof a === 'number' && typeof b === 'number') {
    return Math.abs(a - b) <= TOLERANCE * Math.max(1, Math.abs(a), Math.abs(b));
  }
  if (typeof a === 'string' && typeof b === 'string' && a !== b) {
    const x = Number(a);
    const y = Number(b);
    return a.trim() !== '' && Number.isFinite(x) && Number.isFinite(y)
      ? same(x, y)
      : false;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, i) => same(item, b[i]));
  }
  if (
    typeof a === 'object' &&
    typeof b === 'object' &&
    a != null &&
    b != null
  ) {
    const keys = Object.keys(a);
    return (
      keys.join() === Object.keys(b).join() &&
      keys.every((key) =>
        same(
          (a as Record<string, unknown>)[key],
          (b as Record<string, unknown>)[key],
        ),
      )
    );
  }
  return a === b;
};

const sortedRows = (rows: Array<Record<string, unknown>>) =>
  rows.map((row) => JSON.stringify(row)).toSorted();

const workload = async (cutoff: string, maxRuns: number) => {
  const queries: Query[] = [];
  let source = '';
  recordQueries((sql, params) => {
    queries.push({ sql, params: { ...params }, source });
  });
  const step = async (name: string, fn: () => Promise<unknown>) => {
    source = name;
    try {
      await fn();
    } catch (error) {
      queries.push({
        sql: '',
        params: {},
        source: `${name} failed: ${errorMessage(error)}`,
      });
    }
  };
  await step('describe_schema', describeSchema);
  const runs = (await listRuns(100))
    .filter(
      (run: Run) =>
        run.stopped_at != null &&
        run.stopped_at < cutoff &&
        run.duration_s > 60,
    )
    .slice(0, maxRuns);
  for (const run of runs) {
    for (const slab of loadSlabs()) {
      await step(
        `slab ${slab.id} ${run.run_id}`,
        async () => await runSlab(slab.id, { run_id: run.run_id }),
      );
    }
    const middle = new Date(
      (Date.parse(`${run.started_at.replace(' ', 'T')}Z`) +
        Date.parse(`${(run.stopped_at ?? '').replace(' ', 'T')}Z`)) /
        2,
    )
      .toISOString()
      .replace('T', ' ')
      .slice(0, 19);
    await step(
      `timeline ${middle}`,
      async () =>
        await timelineTool.run(
          timelineTool.input.parse({ at: middle, run_id: run.run_id }),
        ),
    );
    await step(
      `search_logs ${run.run_id}`,
      async () =>
        await searchLogsTool.run(
          searchLogsTool.input.parse({
            run_id: run.run_id,
            min_level: 'debug',
          }),
        ),
    );
    await step(
      `search_logs text ${run.run_id}`,
      async () =>
        await searchLogsTool.run(
          searchLogsTool.input.parse({ run_id: run.run_id, text: 'Map' }),
        ),
    );
    await step(
      `logs_around ${middle}`,
      async () =>
        await logsAroundTool.run(
          logsAroundTool.input.parse({ at: middle, run_id: run.run_id }),
        ),
    );
    for (const symptom of ['reboots', 'stalls', 'data_gaps']) {
      await step(
        `investigate ${symptom} ${middle}`,
        async () =>
          await investigateTool.run(
            investigateTool.input.parse({
              symptom,
              at: middle,
              run_id: run.run_id,
            }),
          ),
      );
    }
    await step(
      `investigate motor_current ${run.run_id}`,
      async () =>
        await investigateTool.run(
          investigateTool.input.parse({
            symptom: 'motor_current',
            run_id: run.run_id,
            from: run.started_at.slice(0, 19),
            to: new Date(
              Math.min(
                Date.parse(`${run.started_at.replace(' ', 'T')}Z`) + 600_000,
                Date.parse(`${(run.stopped_at ?? '').replace(' ', 'T')}Z`),
              ),
            )
              .toISOString()
              .replace('T', ' ')
              .slice(0, 19),
          }),
        ),
    );
  }
  const [first] = runs;
  if (first != null) {
    await step(`graph series ${first.run_id}`, async () => {
      const nodes = [...loadGraph().nodes.values()].filter(isSeries);
      const scope = {
        run_id: first.run_id,
        from: '1970-01-01 00:00:00',
        to: '2100-01-01 00:00:00',
      };
      await fetchSeries(nodes, scope, gridFor(await extent(nodes, scope), 0.1));
    });
  }
  await step(
    'find_object',
    async () => await findObjectTool.run({ object: 'refrigerator' }),
  );
  recordQueries(null);
  return { runs: runs.map((run) => run.run_id), queries };
};

export const parity = async (
  url: string,
  cutoff: string,
  maxRuns = 8,
  limit = Infinity,
) => {
  const { runs, queries } = await workload(cutoff, maxRuns);
  const failures = queries.filter((query) => query.sql === '');
  const unique = [
    ...new Map(
      queries
        .filter((query) => query.sql !== '')
        .map((query) => [JSON.stringify([query.sql, query.params]), query]),
    ).values(),
  ].slice(0, limit);
  const report = {
    runs,
    tool_failures: failures.map((query) => query.source),
    queries: unique.length,
    equal: 0,
    equal_unordered: 0,
    both_ran: 0,
    approximate: 0,
    different: [] as Array<{ source: string; sql: string; detail: string }>,
    errors: [] as Array<{ source: string; sql: string; error: string }>,
    chdb_ms: 0,
    clickhouse_ms: 0,
  };
  for (const query of unique) {
    try {
      const started = performance.now();
      const ours = await select<Record<string, unknown>>(
        query.sql,
        query.params,
      );
      report.chdb_ms += performance.now() - started;
      const theirs = await clickhouse(url, query);
      report.clickhouse_ms += theirs.ms;
      if (
        /^\s*EXPLAIN|system\.|now64\(|now\(\)|FROM runs ORDER/.test(query.sql)
      ) {
        report.both_ran += 1;
      } else if (same(ours, theirs.rows)) {
        report.equal += 1;
      } else if (
        ours.length === theirs.rows.length &&
        same(
          sortedRows(ours).map((row) => JSON.parse(row) as unknown),
          sortedRows(theirs.rows).map((row) => JSON.parse(row) as unknown),
        )
      ) {
        report.equal_unordered += 1;
      } else if (
        /\b(quantile|topK)\(/.test(query.sql) &&
        ours.length === theirs.rows.length
      ) {
        report.approximate += 1;
      } else {
        const found = ours.findIndex((row, i) => !same(row, theirs.rows[i]));
        const index = found < 0 ? ours.length : found;
        report.different.push({
          source: query.source,
          sql: query.sql.slice(0, 400),
          detail: `rows ${ours.length} vs ${theirs.rows.length}; first difference at ${index}: ${JSON.stringify(ours[index] ?? null).slice(0, 300)} vs ${JSON.stringify(theirs.rows[index] ?? null).slice(0, 300)}`,
        });
      }
    } catch (error) {
      report.errors.push({
        source: query.source,
        sql: query.sql.slice(0, 300),
        error: errorMessage(error).slice(0, 300),
      });
    }
  }
  return {
    ...report,
    chdb_ms: Math.round(report.chdb_ms),
    clickhouse_ms: Math.round(report.clickhouse_ms),
  };
};

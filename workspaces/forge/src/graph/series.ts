import { reader, select } from '../clickhouse.ts';
import { ForgeError } from '../errors.ts';
import { epochMs } from '../output.ts';
import { runSlab } from '../slabs/run_slab.ts';
import type { EventNode, SeriesNode } from './graph.ts';

export type Scope = { run_id: string; from: string; to: string };

export const SCOPE_SQL =
  "WHERE run_id = {run_id:String} AND ts >= parseDateTime64BestEffort({from:String}, 9, 'UTC') AND ts < parseDateTime64BestEffort({to:String}, 9, 'UTC')";

export const FAST_MAX_MS = 15 * 60 * 1000;

export type Grid = {
  binMs: number;
  firstBin: number;
  length: number;
};

export type Sampled = {
  values: number[];
  observed: boolean[];
};

export const timeOf = (grid: Grid, index: number) =>
  (grid.firstBin + index) * grid.binMs;

export const isoOf = (grid: Grid, index: number) =>
  new Date(timeOf(grid, index)).toISOString();

export const extent = async (nodes: SeriesNode[], scope: Scope) => {
  const tables = [...new Set(nodes.map((node) => node.source.table))];
  const rows = await Promise.all(
    tables.map(
      async (table) =>
        (
          await select<{ first: string; last: string; samples: string }>(
            reader,
            `SELECT toUnixTimestamp64Milli(min(ts)) AS first, toUnixTimestamp64Milli(max(ts)) AS last, count() AS samples FROM ${table} ${SCOPE_SQL}`,
            scope,
          )
        )[0],
    ),
  );
  const present = rows.filter((row) => row != null && Number(row.samples) > 0);
  if (present.length === 0) {
    throw new ForgeError('No samples for these metrics in the run', {
      llm: 'This run and time range hold no data for the requested metrics; pick another run or widen from and to.',
      internal: { tables, ...scope },
    });
  }
  return {
    first: Math.min(...present.map((row) => Number(row?.first))),
    last: Math.max(...present.map((row) => Number(row?.last))),
  };
};

export const gridFor = (
  span: { first: number; last: number },
  hz: number,
): Grid => {
  const binMs = Math.max(1, Math.round(1000 / hz));
  const firstBin = Math.floor(span.first / binMs);
  return {
    binMs,
    firstBin,
    length: Math.floor(span.last / binMs) - firstBin + 1,
  };
};

export const toGrid = (
  rows: Array<{ bin: number; value: number }>,
  firstBin: number,
  length: number,
  missing: 'gap' | 'zero' = 'gap',
): Sampled => {
  const empty = missing === 'zero' && rows.length > 0 ? 0 : Number.NaN;
  const raw = Array.from({ length }, () => empty);
  for (const row of rows) {
    const index = row.bin - firstBin;
    if (index >= 0 && index < length) {
      raw[index] = row.value;
    }
  }
  const observed = raw.map((value) => Number.isFinite(value));
  let last = raw.find((value) => Number.isFinite(value)) ?? 0;
  const values = raw.map((value) => {
    last = Number.isFinite(value) ? value : last;
    return last;
  });
  return { values, observed };
};

export const fetchSeries = async (
  nodes: SeriesNode[],
  scope: Scope,
  grid: Grid,
): Promise<Map<string, Sampled>> => {
  const byTable = Map.groupBy(nodes, (node) => node.source.table);
  const result = new Map<string, Sampled>();
  await Promise.all(
    [...byTable].map(async ([table, group]) => {
      const columns = group
        .map((node, i) =>
          node.source.agg === 'rate'
            ? `sum(toFloat64(${node.source.expr})) * 1000 / ${Math.max(grid.binMs, 1000 / node.hz)} AS m${i}`
            : `avg(toFloat64(${node.source.expr})) AS m${i}`,
        )
        .join(', ');
      const rows = await select<Record<string, number | string | null>>(
        reader,
        `SELECT intDiv(toUnixTimestamp64Milli(ts), {bin_ms:UInt32}) AS bin, ${columns} FROM ${table} ${SCOPE_SQL} GROUP BY bin ORDER BY bin`,
        { ...scope, bin_ms: grid.binMs },
      );
      for (const [i, node] of group.entries()) {
        result.set(
          node.id,
          toGrid(
            rows.map((row) => ({
              bin: Number(row.bin),
              value: row[`m${i}`] == null ? Number.NaN : Number(row[`m${i}`]),
            })),
            grid.firstBin,
            grid.length,
            node.source.agg === 'rate' ? 'zero' : 'gap',
          ),
        );
      }
    }),
  );
  return result;
};

export const fetchEvents = async (
  node: EventNode,
  scope: Scope,
): Promise<Array<{ start: number; end: number | null }>> => {
  const { rows } = await runSlab(
    node.events.slab,
    { run_id: scope.run_id, from: scope.from, to: scope.to },
    2000,
  );
  return rows
    .filter((row) =>
      Object.entries(node.events.where).every(
        ([column, value]) => String(row[column]) === String(value),
      ),
    )
    .flatMap((row) => {
      const start = epochMs(row[node.events.time]);
      return start == null
        ? []
        : [
            {
              start,
              end:
                node.events.end == null ? null : epochMs(row[node.events.end]),
            },
          ];
    });
};

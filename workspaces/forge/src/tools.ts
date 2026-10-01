import z from 'zod';

import { detectAnomaliesTool } from './anomaly/detect.ts';
import { listMetricsTool } from './catalog.ts';
import { forgeTool } from './forge_tool.ts';
import { investigateTool, metricGraphTool } from './graph/tools.ts';
import { logsAroundTool, searchLogsTool } from './logs.ts';
import { table } from './output.ts';
import { listRuns, resolveRunParams } from './runs.ts';
import { describeSchema } from './schema.ts';
import { runSlab } from './slabs/run_slab.ts';
import { searchSlabs } from './slabs/search_slabs.ts';
import { DEFAULT_ROW_LIMIT, runSql } from './sql/query_gate.ts';
import { timelineTool } from './timeline.ts';

const Params = z
  .record(z.string(), z.union([z.string(), z.number()]))
  .default({})
  .describe("Values for the {name:Type} placeholders; run_id accepts 'latest'");

const RowLimit = z
  .number()
  .int()
  .min(1)
  .max(2000)
  .default(DEFAULT_ROW_LIMIT)
  .describe('Maximum rows returned; the result says when it was truncated');

export const listRunsTool = forgeTool({
  title: 'List runs',
  description:
    'Recorded runs (missions) of the Rabbit robot, newest first: run_id, name, kind (manual runs are named recordings, auto runs are opened by the writer between them), start, stop (null while recording), duration and note.',
  input: z.object({ limit: z.number().int().min(1).max(100).default(20) }),
  run: async ({ limit }) => table(await listRuns(limit), { title: 'Runs' }),
});

export const searchSlabsTool = forgeTool({
  title: 'Search slabs',
  description:
    'Keyword search over the slab library: reviewed, parameterised ClickHouse queries for common robot questions (battery sag, wheel stall, Jetson throttling, IMU shocks, trajectory, power rails, data quality). Returns each match with its description, parameters and column metadata. Prefer running a slab over writing SQL.',
  input: z.object({
    query: z.string().describe('What you want to know, in plain words'),
    limit: z.number().int().min(1).max(20).default(5),
  }),
  run: async ({ query, limit }) =>
    await Promise.resolve(searchSlabs(query, limit)),
});

export const runSlabTool = forgeTool({
  title: 'Run slab',
  description:
    "Runs a slab by id with optional parameters (run_id defaults to 'latest', the most recent named run). Returns the rows, the resolved parameters, column metadata (kind for dimensions; measure gauge, counter, event or ratio for metrics, with units) and guidelines for reading the result.",
  input: z.object({
    slab: z.string().describe('Slab id from search_slabs'),
    params: Params,
    limit: RowLimit,
  }),
  run: async ({ slab, params, limit }) => await runSlab(slab, params, limit),
});

export const queryTool = forgeTool({
  title: 'Query',
  description:
    'Runs one read-only ClickHouse SELECT over the Forge tables (see describe_schema). The SQL must pass a static gate (single SELECT or WITH or UNION, Forge tables only, no SETTINGS, FINAL or table functions, every JOIN matches run_id on both sides) and ClickHouse EXPLAIN before it runs; a rejection explains how to fix it. Filter by run with WHERE run_id = {run_id:String} and pass params.run_id.',
  input: z.object({
    sql: z.string(),
    params: Params,
    limit: RowLimit,
  }),
  run: async ({ sql, params, limit }) => {
    const result = await runSql(sql, await resolveRunParams(params), limit);
    return table(result.rows, {
      rowCount: result.row_count,
      truncated: result.truncated,
    });
  },
});

export const describeSchemaTool = forgeTool({
  title: 'Describe schema',
  description:
    'Tables and views in the Forge ClickHouse database with column types and descriptions (units, value ranges, caveats). Every telemetry table has run_id and ts (robot wall clock, DateTime64 in nanoseconds, UTC).',
  input: z.object({}),
  run: async () => await describeSchema(),
});

export const DATA_TOOLS = {
  list_runs: listRunsTool,
  search_slabs: searchSlabsTool,
  run_slab: runSlabTool,
  query: queryTool,
  describe_schema: describeSchemaTool,
  detect_anomalies: detectAnomaliesTool,
  metric_graph: metricGraphTool,
  investigate: investigateTool,
  timeline: timelineTool,
  search_logs: searchLogsTool,
  logs_around: logsAroundTool,
  list_metrics: listMetricsTool,
};

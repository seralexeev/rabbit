import z from 'zod';

import { ForgeError } from './errors.ts';
import { forgeTool } from './forge_tool.ts';
import { type Chart, epochMs, outputId, toRows } from './output.ts';
import { resolveRunParams } from './runs.ts';
import { slabQuery } from './slabs/run_slab.ts';
import { runSql } from './sql/query_gate.ts';

const Axis = z.object({
  field: z.string(),
  label: z.string(),
  unit: z.string().optional(),
});

const MAX_POINTS = 2000;

const sourceRows = async (source: {
  slab?: string | undefined;
  sql?: string | undefined;
  params: Record<string, string | number>;
}) => {
  if ((source.slab == null) === (source.sql == null)) {
    throw new ForgeError('Chart source needs exactly one of slab or sql', {
      llm: 'Pass source.slab (a slab id) or source.sql (a SELECT), not both.',
    });
  }
  const { sql, params } =
    source.slab == null
      ? { sql: source.sql ?? '', params: await resolveRunParams(source.params) }
      : await slabQuery(source.slab, source.params);
  const [counted] = (
    await runSql(`SELECT count() AS n FROM (${sql})`, params, 1)
  ).rows;
  const total = Number(counted?.n ?? 0);
  const stride = Math.max(1, Math.ceil(total / MAX_POINTS));
  const sampled =
    stride === 1
      ? sql
      : `SELECT * FROM (${sql}) WHERE modulo(rowNumberInAllBlocks(), {chart_stride:UInt32}) = 0`;
  const result = await runSql(
    sampled,
    { ...params, chart_stride: stride },
    MAX_POINTS + 1,
  );
  return { rows: toRows(result.rows), total, stride };
};

export const chartTool = forgeTool({
  title: 'Chart',
  description:
    'Draws a chart for the user from a slab or a SQL query. The server runs the source, converts time values to epoch milliseconds, and downsamples to at most 2000 points, so pass field names, never data. Use it after you have looked at the numbers, for trends over time (line or area), comparisons across categories (bar) or relationships between two measures (scatter). Put a second unit on axis right.',
  input: z.object({
    type: z.enum(['line', 'area', 'bar', 'scatter']),
    title: z.string(),
    source: z.object({
      slab: z.string().optional().describe('Slab id to run'),
      sql: z
        .string()
        .optional()
        .describe('A SELECT that passes the query gate'),
      params: z
        .record(z.string(), z.union([z.string(), z.number()]))
        .default({})
        .describe("Slab or SQL params; run_id accepts 'latest'"),
    }),
    x: Axis.extend({
      time: z.boolean().optional().describe('True when x is a timestamp'),
    }),
    series: z
      .array(Axis.extend({ axis: z.enum(['left', 'right']).optional() }))
      .min(1)
      .max(8),
  }),
  run: async ({
    type,
    title,
    source,
    x,
    series,
  }): Promise<Chart & { source_rows: number; downsampled: boolean }> => {
    const { rows, total, stride } = await sourceRows(source);
    const missing = [x, ...series]
      .map((axis) => axis.field)
      .filter((field) => rows.length > 0 && !(field in (rows[0] ?? {})));
    if (missing.length > 0) {
      throw new ForgeError('Chart fields are not in the source rows', {
        llm: `Missing fields: ${missing.join(', ')}. Available: ${Object.keys(rows[0] ?? {}).join(', ')}.`,
      });
    }
    const fields = [x.field, ...series.map((axis) => axis.field)];
    const picked = rows.map((row) =>
      Object.fromEntries(
        fields.map((field) => [
          field,
          field === x.field && x.time === true
            ? epochMs(row[field])
            : (row[field] ?? null),
        ]),
      ),
    );
    return {
      kind: 'chart',
      id: outputId('chart'),
      chart: { type, title, x, series, rows: picked },
      source_rows: total,
      downsampled: stride > 1,
    };
  },
  forModel: ({ id, chart, source_rows, downsampled }) => ({
    kind: 'chart',
    id,
    title: chart.title,
    type: chart.type,
    points: chart.rows.length,
    source_rows,
    downsampled,
    shown_to_user: true,
  }),
});

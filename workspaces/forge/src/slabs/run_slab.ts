import { ForgeError } from '../errors.ts';
import { label, table } from '../output.ts';
import { resolveRunParams } from '../runs.ts';
import { DEFAULT_ROW_LIMIT, describeQuery, runSql } from '../sql/query_gate.ts';
import { select } from '../store/engine.ts';
import { type Slab, type SlabSub, getSlab } from './slab.ts';

type ParamValue = string | number;

const TARGET_ROWS = 180;

const autoBucket = async (params: Record<string, ParamValue>) => {
  const [span] = await select<{ seconds: number | null }>(
    "SELECT dateDiff('second', greatest(started_at, parseDateTime64BestEffort({from:String}, 9, 'UTC')), least(coalesce(stopped_at, now64(9)), parseDateTime64BestEffort({to:String}, 9, 'UTC'))) AS seconds FROM runs WHERE run_id = {run_id:String}",
    {
      run_id: params.run_id,
      from: params.from ?? '1970-01-01 00:00:00',
      to: params.to ?? '2100-01-01 00:00:00',
    },
  );
  return Math.max(1, Math.ceil((span?.seconds ?? 0) / TARGET_ROWS));
};

const coerce = (name: string, sub: SlabSub, value: unknown): ParamValue => {
  if (sub.type === 'String') {
    const text = String(value);
    if (sub.enum != null && !sub.enum.includes(text)) {
      throw new ForgeError('Slab parameter is not one of its allowed values', {
        llm: `${name} must be one of: ${sub.enum.join(', ')}.`,
        internal: { name, value: text },
      });
    }
    return text;
  }
  const number = Number(value);
  if (
    !Number.isFinite(number) ||
    (sub.type === 'UInt32' && (!Number.isInteger(number) || number < 0))
  ) {
    throw new ForgeError('Slab parameter is not a valid number', {
      llm: `${name} must be a ${sub.type === 'UInt32' ? 'non-negative integer' : 'number'}.`,
      internal: { name, value },
    });
  }
  return number;
};

const resolveParams = async (slab: Slab, input: Record<string, unknown>) => {
  const unknown = Object.keys(input).filter((name) => !(name in slab.subs));
  if (unknown.length > 0) {
    throw new ForgeError('Unknown slab parameter', {
      llm: `${slab.id} takes only: ${Object.keys(slab.subs).join(', ')}.`,
      internal: { slab: slab.id, unknown },
    });
  }
  const params: Record<string, ParamValue> = {};
  for (const [name, sub] of Object.entries(slab.subs)) {
    const value = input[name] ?? sub.default;
    if (value == null) {
      throw new ForgeError('Missing slab parameter', {
        llm: `${slab.id} needs ${name}: ${sub.description}.`,
        internal: { slab: slab.id, name },
      });
    }
    params[name] = coerce(name, sub, value);
  }
  const resolved = await resolveRunParams(params);
  if (resolved.bucket_s === 0 && typeof resolved.run_id === 'string') {
    resolved.bucket_s = await autoBucket(resolved);
  }
  return resolved;
};

export const slabQuery = async (id: string, input: Record<string, unknown>) => {
  const slab = getSlab(id);
  return { sql: slab.sql, params: await resolveParams(slab, input) };
};

export const runSlab = async (
  id: string,
  input: Record<string, unknown> = {},
  limit = DEFAULT_ROW_LIMIT,
) => {
  const slab = getSlab(id);
  const params = await resolveParams(slab, input);
  const result = await runSql(slab.sql, params, limit);
  return {
    ...table(result.rows, {
      title: slab.title,
      columns: Object.entries(slab.columns).map(([field, column]) => ({
        field,
        label: label(field),
        ...column,
      })),
      rowCount: result.row_count,
      truncated: result.truncated,
    }),
    slab: slab.id,
    params,
    ...(slab.guidelines == null ? {} : { guidelines: slab.guidelines }),
  };
};

export const checkSlab = async (slab: Slab) => {
  const params = await resolveParams(slab, {});
  const projected = (await describeQuery(slab.sql, params)).map(
    (column) => column.name,
  );
  const declared = Object.keys(slab.columns);
  if (projected.join() !== declared.join()) {
    throw new ForgeError('Slab columns do not match its SQL', {
      internal: { slab: slab.id, projected, declared },
    });
  }
  const { row_count } = await runSql(slab.sql, params, 0);
  return { slab: slab.id, run_id: params.run_id, rows: row_count };
};

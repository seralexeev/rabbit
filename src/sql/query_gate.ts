import { type Params, reader, select } from '../clickhouse.ts';
import { ForgeError, errorMessage } from '../errors.ts';
import { describeSchema, queryableTables } from '../schema.ts';
import { validateSql } from './validate_sql.ts';

export const DEFAULT_ROW_LIMIT = 200;

const UNKNOWN_IDENTIFIER =
  /Unknown expression (?:or function )?identifier [`'](?:\w+\.)?(\w+)[`']/;

const columnsHint = async (sql: string) => {
  const schema = await describeSchema();
  const used = schema.filter((table) =>
    new RegExp(`\\b${table.name}\\b`).test(sql),
  );
  return used
    .map(
      (table) =>
        `${table.name}: ${table.columns.map((column) => column.name).join(', ')}`,
    )
    .join('; ');
};

const repairHint = async (error: string, sql: string): Promise<string> => {
  const head = error.split('\n')[0]?.slice(0, 600) ?? error;
  const unknown = UNKNOWN_IDENTIFIER.exec(error)?.[1];
  if (unknown != null) {
    return `${head} There is no column '${unknown}' in scope. Columns of the tables you read: ${await columnsHint(sql)}. A CTE or subquery exposes only what it projects with AS.`;
  }
  if (
    error.includes('is not under aggregate function and not in GROUP BY keys')
  ) {
    return `${head} Every projected column that is not aggregated must be in GROUP BY or wrapped in an aggregate such as any(...).`;
  }
  if (error.includes('is found inside another aggregate function')) {
    return `${head} An alias of an aggregate is reused inside another aggregate in the same SELECT; give the aggregate a different alias or aggregate in a CTE.`;
  }
  if (/Substitution `?(\w+)`? is not set/.test(error)) {
    return `${head} Every {name:Type} placeholder needs a value in params.`;
  }
  if (error.includes('no supertype')) {
    return `${head} Both branches of if, coalesce, multiIf or UNION ALL need one type; wrap them with toFloat64(...).`;
  }
  return head;
};

export const checkSql = async (sql: string, params: Params = {}) => {
  const staticError = validateSql(sql, await queryableTables());
  if (staticError != null) {
    throw new ForgeError('SQL rejected by the static gate', {
      llm: staticError,
      internal: { sql },
    });
  }
  try {
    await select(reader, `EXPLAIN PLAN ${sql}`, params);
  } catch (error) {
    throw new ForgeError('SQL rejected by ClickHouse EXPLAIN', {
      llm: await repairHint(errorMessage(error), sql),
      internal: { sql },
      cause: error,
    });
  }
};

export type QueryResult = {
  row_count: number;
  truncated: boolean;
  rows: Array<Record<string, unknown>>;
};

export const runSql = async (
  sql: string,
  params: Params = {},
  limit = DEFAULT_ROW_LIMIT,
): Promise<QueryResult> => {
  await checkSql(sql, params);
  try {
    const rows = await select<Record<string, unknown>>(reader, sql, params);
    return {
      row_count: rows.length,
      truncated: rows.length > limit,
      rows: rows.slice(0, limit),
    };
  } catch (error) {
    throw new ForgeError('Query failed', {
      llm: await repairHint(errorMessage(error), sql),
      internal: { sql },
      cause: error,
    });
  }
};

export const describeQuery = async (sql: string, params: Params = {}) =>
  await select<{ name: string; type: string }>(
    reader,
    `DESCRIBE TABLE (${sql})`,
    params,
  );

import { Session } from 'chdb';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { config } from '../config.ts';
import { RwLock } from './rwlock.ts';
import { ensureMirror } from './sync.ts';

export type Params = Record<string, unknown>;

export type Column = {
  name: string;
  type: string;
  default_kind: string;
  default_expression: string;
  comment: string;
};

export type TableSpec = {
  name: string;
  engine: string;
  sortingKey: string;
  comment: string;
  time: string;
  columns: Column[];
};

const SCHEMA_DB = 'forge_schema';
const STAGING_DB = 'forge_staging';
const READERS = 4;
const SERVER_MEMORY_BYTES = 900_000_000;
const RETRY_CODES = new Set([76, 107]);

const COMMON_SETTINGS = {
  max_threads: 2,
  use_hive_partitioning: 0,
  input_format_parquet_allow_missing_columns: 1,
};

const READER_SETTINGS = {
  ...COMMON_SETTINGS,
  max_execution_time: 30,
  max_memory_usage: 300_000_000,
  max_bytes_before_external_sort: 100_000_000,
  max_bytes_before_external_group_by: 100_000_000,
  max_rows_to_read: 200_000_000,
  max_bytes_to_read: 4_000_000_000,
  max_result_rows: 10_000,
  result_overflow_mode: "'break'",
  readonly: 2,
};

const WRITER_SETTINGS = {
  ...COMMON_SETTINGS,
  max_memory_usage: 300_000_000,
  output_format_parquet_compression_method: "'zstd'",
  output_format_parquet_row_group_size: 65_536,
  engine_file_truncate_on_insert: 1,
};

export const SCHEMA_SQL = new URL('schema.sql', import.meta.url);

export const literal = (text: string) =>
  `'${text.replaceAll('\\', '\\\\').replaceAll("'", "\\'")}'`;

export const quoteName = (name: string) => `\`${name.replaceAll('`', '``')}\``;

export const schemaStatements = () =>
  readFileSync(SCHEMA_SQL, 'utf8')
    .split(/;\s*$/m)
    .map((statement) => statement.trim())
    .filter((statement) => statement.length > 0);

export const structure = (spec: TableSpec) =>
  spec.columns.map((column) => `${column.name} ${column.type}`).join(', ');

export const tableGlob = (table: string) =>
  join(config.dataDir, table, '*', '*', '*.parquet');

const parseRows = <T>(text: string): T[] =>
  text.length === 0
    ? []
    : text
        .trimEnd()
        .split('\n')
        .map((line) => JSON.parse(line) as T);

export const clickhouseCode = (error: unknown) => {
  if (typeof error !== 'object' || error == null) {
    return null;
  }
  const { clickhouseCode: code, message } = error as {
    clickhouseCode?: unknown;
    message?: unknown;
  };
  if (typeof code === 'number') {
    return code;
  }
  const parsed =
    typeof message === 'string' ? /Code: (\d+)\./.exec(message)?.[1] : null;
  return parsed == null ? null : Number(parsed);
};

const apply = async (session: Session, settings: Record<string, unknown>) => {
  for (const [name, value] of Object.entries(settings)) {
    await session.queryAsync(`SET ${name} = ${String(value)}`);
  }
};

class Pool {
  private readonly idle: Session[];
  private readonly waiting: Array<(session: Session) => void> = [];

  public constructor(sessions: Session[]) {
    this.idle = [...sessions];
  }

  public async use<T>(fn: (session: Session) => Promise<T>): Promise<T> {
    const session =
      this.idle.pop() ??
      (await new Promise<Session>((resolve) => {
        this.waiting.push(resolve);
      }));
    try {
      return await fn(session);
    } finally {
      const next = this.waiting.shift();
      if (next == null) {
        this.idle.push(session);
      } else {
        next(session);
      }
    }
  }
}

type Engine = {
  path: string;
  sessions: Session[];
  readers: Pool;
  writer: Session;
  tables: Map<string, TableSpec>;
  staged: Set<string>;
};

const lock = new RwLock();

const run = async (session: Session, sql: string, params: Params = {}) => {
  const bound = Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined),
  );
  const result =
    Object.keys(bound).length === 0
      ? await session.queryAsync(sql, { format: 'JSONEachRow' })
      : await session.queryBindAsync(sql, bound, { format: 'JSONEachRow' });
  return result.text();
};

const loadSpecs = async (session: Session) => {
  const tables = parseRows<{
    name: string;
    engine: string;
    sorting_key: string;
    comment: string;
  }>(
    await run(
      session,
      `SELECT name, engine, sorting_key, comment FROM system.tables WHERE database = '${SCHEMA_DB}' ORDER BY name`,
    ),
  );
  const columns = parseRows<Column & { table: string }>(
    await run(
      session,
      `SELECT table, name, type, default_kind, default_expression, comment FROM system.columns WHERE database = '${SCHEMA_DB}' ORDER BY table, position`,
    ),
  );
  return new Map(
    tables.map((table) => {
      const own = columns
        .filter((column) => column.table === table.name)
        .map(({ table: _, ...column }) => column);
      const time =
        table.sorting_key
          .split(',')
          .map((key) => key.trim())
          .find((key) =>
            own.some(
              (column) =>
                column.name === key && column.type.startsWith('DateTime64'),
            ),
          ) ?? 'ts';
      return [
        table.name,
        {
          name: table.name,
          engine: table.engine,
          sortingKey: table.sorting_key,
          comment: table.comment,
          time,
          columns: own,
        },
      ];
    }),
  );
};

const start = async (): Promise<Engine> => {
  const path = mkdtempSync(join(tmpdir(), 'forge-chdb-'));
  const writer = new Session(path, {
    connectionArgs: [`--max_server_memory_usage=${SERVER_MEMORY_BYTES}`],
  });
  const statements = schemaStatements();
  await run(writer, `CREATE DATABASE IF NOT EXISTS ${SCHEMA_DB}`);
  await run(writer, `CREATE DATABASE IF NOT EXISTS ${STAGING_DB}`);
  await run(writer, 'CREATE DATABASE IF NOT EXISTS forge');
  for (const statement of statements.filter((sql) =>
    /^CREATE TABLE/i.test(sql),
  )) {
    await run(
      writer,
      statement.replace(
        /^CREATE TABLE IF NOT EXISTS forge\./i,
        `CREATE TABLE IF NOT EXISTS ${SCHEMA_DB}.`,
      ),
    );
  }
  const tables = await loadSpecs(writer);
  for (const spec of tables.values()) {
    await run(
      writer,
      `CREATE VIEW forge.${quoteName(spec.name)} AS SELECT * FROM file(${literal(tableGlob(spec.name))}, Parquet, ${literal(structure(spec))})`,
    );
  }
  for (const statement of statements.filter(
    (sql) => !/^CREATE TABLE/i.test(sql),
  )) {
    await run(writer, statement);
  }
  await run(writer, 'USE forge');
  await apply(writer, WRITER_SETTINGS);
  const readers = Array.from({ length: READERS }, () => new Session(path));
  for (const reader of readers) {
    await run(reader, 'USE forge');
    await apply(reader, READER_SETTINGS);
  }
  return {
    path,
    sessions: [writer, ...readers],
    readers: new Pool(readers),
    writer,
    tables,
    staged: new Set(),
  };
};

let engine: Promise<Engine> | null = null;

const ready = async () => {
  engine ??= start();
  return await engine;
};

type Recorder = (sql: string, params: Params) => void;

let recorder: Recorder | null = null;

export const recordQueries = (record: Recorder | null) => {
  recorder = record;
};

export const select = async <T>(
  sql: string,
  params: Params = {},
): Promise<T[]> => {
  recorder?.(sql, params);
  if (config.syncFrom != null) {
    await ensureMirror();
  }
  const { readers } = await ready();
  for (let attempt = 0; ; attempt++) {
    try {
      return parseRows<T>(
        await lock.read(
          async () =>
            await readers.use(
              async (session) => await run(session, sql, params),
            ),
        ),
      );
    } catch (error) {
      const code = clickhouseCode(error);
      if (attempt > 0 || code == null || !RETRY_CODES.has(code)) {
        throw error;
      }
    }
  }
};

export const ping = async () => {
  try {
    await select('SELECT 1');
    return true;
  } catch {
    return false;
  }
};

export const tableSpecs = async () => (await ready()).tables;

export const tableSpec = async (table: string) => {
  const spec = (await ready()).tables.get(table);
  if (spec == null) {
    throw new Error(`Unknown table ${table}`);
  }
  return spec;
};

export const execute = async (sql: string, params: Params = {}) =>
  parseRows<Record<string, unknown>>(
    await run((await ready()).writer, sql, params),
  );

export const stagingTable = async (table: string) => {
  const { staged, writer } = await ready();
  const name = `${STAGING_DB}.${table}`;
  if (!staged.has(table)) {
    await run(
      writer,
      `CREATE TABLE IF NOT EXISTS ${name} AS ${SCHEMA_DB}.${quoteName(table)} ENGINE = Memory`,
    );
    staged.add(table);
  }
  return name;
};

export const insertJson = async (table: string, payload: Buffer) => {
  const { writer } = await ready();
  await writer.insert({ table, values: payload, format: 'JSONEachRow' });
};

export const exclusive = async <T>(fn: () => Promise<T> | T) =>
  await lock.write(fn);

export const closeStore = async () => {
  if (engine == null) {
    return;
  }
  const { path, sessions } = await engine;
  engine = null;
  for (const session of sessions) {
    session.close();
  }
  rmSync(path, { recursive: true, force: true });
};

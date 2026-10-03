import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { config } from '../config.ts';
import {
  type TableSpec,
  execute,
  insertJson,
  literal,
  quoteName,
  stagingTable,
  tableSpec,
} from './engine.ts';
import {
  TMP,
  commitFile,
  fileName,
  maxFileId,
  partitionDir,
} from './layout.ts';

export type Row = Record<string, unknown>;

let lastId: number | null = null;

export const nextFileId = () => {
  lastId ??= maxFileId(config.dataDir);
  lastId = Math.max(Date.now(), lastId + 1);
  return lastId;
};

const queues = new Map<string, Promise<unknown>>();

export const serialized = async <T>(
  key: string,
  fn: () => Promise<T>,
): Promise<T> => {
  const previous = queues.get(key) ?? Promise.resolve();
  const next = previous.then(fn, fn);
  const settled = next.then(
    () => null,
    () => null,
  );
  queues.set(key, settled);
  try {
    return await next;
  } finally {
    if (queues.get(key) === settled) {
      queues.delete(key);
    }
  }
};

export const columnList = (spec: TableSpec) =>
  spec.columns.map((column) => quoteName(column.name)).join(', ');

const HOUR_NS = 3_600_000_000_000n;
const HOUR_MS = 3_600_000n;

export const hoursOf = (rows: Row[], time: string) => {
  const hours = new Set<number>();
  for (const row of rows) {
    const value = row[time];
    if (typeof value !== 'string' || !/^\d+$/.test(value)) {
      return null;
    }
    hours.add(Number((BigInt(value) / HOUR_NS) * HOUR_MS));
  }
  return [...hours].toSorted((a, b) => a - b);
};

export const writeStaged = async (
  spec: TableSpec,
  staging: string,
  id: number,
  where = '1',
  known: number[] | null = null,
) => {
  const time = quoteName(spec.time);
  const hours =
    known ??
    (
      await execute(
        `SELECT toUnixTimestamp(toStartOfHour(${time})) AS hour FROM ${staging} WHERE ${where} GROUP BY hour ORDER BY hour`,
      )
    ).map(({ hour }) => Number(hour) * 1000);
  const staged: Array<[string, string]> = [];
  for (const hour of hours) {
    const dir = partitionDir(config.dataDir, spec.name, hour);
    mkdirSync(dir, { recursive: true });
    const path = join(dir, fileName(id, id));
    const filter =
      hours.length === 1
        ? where
        : `${where} AND toStartOfHour(${time}) = toDateTime(${String(hour / 1000)}, 'UTC')`;
    await execute(
      `INSERT INTO FUNCTION file(${literal(path + TMP)}, Parquet)
       SELECT ${columnList(spec)} FROM ${staging}
       WHERE ${filter}
       ORDER BY ${spec.sortingKey}`,
    );
    staged.push([path + TMP, path]);
  }
  for (const [tmp, path] of staged) {
    commitFile(tmp, path);
  }
  return staged.map(([, path]) => path);
};

const dirty = new Set<string>();

export const writeRows = async (
  table: string,
  rows: Row[],
  id = nextFileId(),
) =>
  await serialized(table, async () => {
    const spec = await tableSpec(table);
    const staging = await stagingTable(table);
    if (dirty.has(table)) {
      await execute(`TRUNCATE TABLE ${staging}`);
    }
    dirty.add(table);
    await insertJson(
      staging,
      Buffer.from(rows.map((row) => JSON.stringify(row)).join('\n')),
    );
    const written = await writeStaged(
      spec,
      staging,
      id,
      '1',
      hoursOf(rows, spec.time),
    );
    await execute(`TRUNCATE TABLE ${staging}`);
    dirty.delete(table);
    return written;
  });

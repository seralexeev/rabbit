import { existsSync } from 'node:fs';
import { join } from 'node:path';

import { config } from '../config.ts';
import { ForgeError } from '../errors.ts';
import { mergeFiles } from './compact.ts';
import {
  type TableSpec,
  exclusive,
  execute,
  literal,
  quoteName,
  stagingTable,
  tableSpecs,
} from './engine.ts';
import { hourEnd, listPartitions, removeFiles } from './layout.ts';
import { nextFileId, serialized, writeRows, writeStaged } from './write.ts';

const purgeBefore = async (
  spec: TableSpec,
  cutoffMs: number,
  cutoff: string,
) => {
  for (const partition of listPartitions(config.dataDir, spec.name)) {
    if (hourEnd(partition) <= cutoffMs) {
      await exclusive(() => {
        removeFiles(partition.files.map((file) => file.path));
      });
    } else if (partition.hour < cutoffMs) {
      await mergeFiles(
        spec,
        partition.files,
        `${quoteName(spec.time)} >= ${cutoff}`,
      );
    }
  }
};

const closeOpenRuns = async (source: string, cutoff: string, at: string) => {
  const open = await execute(
    `SELECT run_id, any(name) AS name, toString(any(kind)) AS kind FROM file(${literal(source)}, Parquet)
     WHERE at < ${cutoff} GROUP BY run_id HAVING countIf(toString(event) = 'stop') = 0`,
  );
  if (open.length > 0) {
    await writeRows(
      'run_events',
      open.map((run) => ({ ...run, event: 'stop', at, note: 'migrated' })),
    );
  }
  return open.length;
};

export const importTables = async (dir: string, before?: string) => {
  const cutoffMs =
    before == null ? null : Date.parse(`${before.replace(' ', 'T')}Z`);
  if (cutoffMs != null && Number.isNaN(cutoffMs)) {
    throw new ForgeError('Unreadable --before time', { internal: { before } });
  }
  const cutoff =
    cutoffMs == null
      ? null
      : `fromUnixTimestamp64Milli(toInt64(${String(cutoffMs)}), 'UTC')`;
  const results: Array<{ table: string; rows: number; files: number }> = [];
  for (const spec of (await tableSpecs()).values()) {
    const source = join(dir, `${spec.name}.parquet`);
    if (!existsSync(source)) {
      continue;
    }
    if (cutoffMs != null && cutoff != null) {
      await purgeBefore(spec, cutoffMs, cutoff);
    }
    const present = new Set(
      (await execute(`DESCRIBE file(${literal(source)}, Parquet)`)).map(
        (column) => String(column.name),
      ),
    );
    const columns = spec.columns
      .filter(
        (column) =>
          column.default_kind !== 'MATERIALIZED' &&
          column.default_kind !== 'ALIAS' &&
          present.has(column.name),
      )
      .map((column) => quoteName(column.name))
      .join(', ');
    const time = quoteName(spec.time);
    const where = cutoff == null ? '1' : `${time} < ${cutoff}`;
    const hours = await execute(
      `SELECT toUnixTimestamp(toStartOfHour(${time})) AS hour, count() AS rows FROM file(${literal(source)}, Parquet) WHERE ${where} GROUP BY hour ORDER BY hour`,
    );
    const staging = await stagingTable(spec.name);
    const files = await serialized(spec.name, async () => {
      let written = 0;
      for (const { hour } of hours) {
        await execute(`TRUNCATE TABLE ${staging}`);
        await execute(
          `INSERT INTO ${staging} (${columns}) SELECT ${columns} FROM file(${literal(source)}, Parquet)
           WHERE ${where} AND toStartOfHour(${time}) = toDateTime(${String(hour)}, 'UTC')`,
        );
        written += (await writeStaged(spec, staging, nextFileId())).length;
      }
      await execute(`TRUNCATE TABLE ${staging}`);
      return written;
    });
    results.push({
      table: spec.name,
      rows: hours.reduce((total, { rows }) => total + Number(rows), 0),
      files,
    });
    if (spec.name === 'run_events' && cutoff != null && cutoffMs != null) {
      await closeOpenRuns(source, cutoff, `${BigInt(cutoffMs) * 1_000_000n}`);
    }
  }
  return results;
};

import { renameSync } from 'node:fs';
import { dirname, join } from 'node:path';

import { config } from '../config.ts';
import { log } from '../log.ts';
import {
  type TableSpec,
  exclusive,
  execute,
  literal,
  structure,
  tableSpecs,
} from './engine.ts';
import {
  type DataFile,
  type Partition,
  TMP,
  dataBytes,
  fileName,
  filesBytes,
  hourEnd,
  listPartitions,
  removeEmptyDirs,
  removeFiles,
  syncDir,
  syncFile,
} from './layout.ts';
import { columnList, serialized } from './write.ts';

const DAY_MS = 86_400_000;
const CLOSE_GRACE_MS = 120_000;
const MAX_SMALL_FILES = 30;
const CAP_TARGET = 0.9;
const KEEP_FOREVER = new Set(['run_events']);

type Rule = { afterDays: number; keep: string | null };

export const RETENTION: Record<string, Rule[]> = {
  logs: [
    { afterDays: 30, keep: "level >= 'warning'" },
    { afterDays: 180, keep: null },
  ],
};

const sources = (files: DataFile[]) => {
  const [first] = files;
  if (files.length === 1 && first != null) {
    return first.path;
  }
  return join(
    dirname(first?.path ?? ''),
    `{${files.map((file) => file.name).join(',')}}`,
  );
};

export const mergeFiles = async (
  spec: TableSpec,
  files: DataFile[],
  where?: string,
) =>
  await serialized(`merge:${spec.name}`, async () => {
    const [first] = files;
    if (first == null) {
      return null;
    }
    const from = Math.min(...files.map((file) => file.from));
    const to = Math.max(...files.map((file) => file.to));
    const path = join(dirname(first.path), fileName(from, to));
    const dedupe =
      spec.engine === 'ReplacingMergeTree'
        ? ` LIMIT 1 BY ${spec.sortingKey}`
        : '';
    const [{ rows } = { rows: 0 }] = await execute(
      `SELECT count() AS rows FROM file(${literal(sources(files))}, Parquet, ${literal(structure(spec))})${where == null ? '' : ` WHERE ${where}`}`,
    );
    if (Number(rows) > 0) {
      await execute(
        `INSERT INTO FUNCTION file(${literal(path + TMP)}, Parquet)
         SELECT ${columnList(spec)} FROM file(${literal(sources(files))}, Parquet, ${literal(structure(spec))})
         ${where == null ? '' : `WHERE ${where}`}
         ORDER BY ${spec.sortingKey}${dedupe}`,
      );
      syncFile(path + TMP);
    }
    await exclusive(() => {
      if (Number(rows) > 0) {
        renameSync(path + TMP, path);
        syncDir(dirname(path));
      }
      removeFiles(
        files.map((file) => file.path).filter((input) => input !== path),
      );
    });
    return Number(rows) > 0 ? path : null;
  });

const isSmall = (file: DataFile) => file.from === file.to;

export const compactPartition = async (
  spec: TableSpec,
  partition: Partition,
  now: number,
) => {
  if (hourEnd(partition) + CLOSE_GRACE_MS < now) {
    if (partition.files.length > 1) {
      await mergeFiles(spec, partition.files);
      return partition.files.length;
    }
    return 0;
  }
  const small = partition.files.filter(isSmall);
  if (small.length >= MAX_SMALL_FILES) {
    await mergeFiles(spec, small);
    return small.length;
  }
  return 0;
};

export const compact = async (now = Date.now()) => {
  let merged = 0;
  for (const spec of (await tableSpecs()).values()) {
    for (const partition of listPartitions(config.dataDir, spec.name)) {
      merged += await compactPartition(spec, partition, now);
    }
  }
  return merged;
};

const pruned = new Set<string>();

const applyRules = async (spec: TableSpec, rules: Rule[], now: number) => {
  for (const partition of listPartitions(config.dataDir, spec.name)) {
    const age = now - hourEnd(partition);
    const rule = rules
      .filter((candidate) => age > candidate.afterDays * DAY_MS)
      .toSorted((a, b) => b.afterDays - a.afterDays)[0];
    if (rule == null) {
      continue;
    }
    if (rule.keep == null) {
      await exclusive(() => {
        removeFiles(partition.files.map((file) => file.path));
      });
      continue;
    }
    const key = `${partition.dir}:${rule.afterDays}`;
    if (!pruned.has(key)) {
      await mergeFiles(spec, partition.files, rule.keep);
      pruned.add(key);
    }
  }
};

export const applyRetention = async (now = Date.now()) => {
  const specs = await tableSpecs();
  for (const [table, rules] of Object.entries(RETENTION)) {
    const spec = specs.get(table);
    if (spec != null) {
      await applyRules(spec, rules, now);
    }
  }
  let total = dataBytes(config.dataDir);
  if (total <= config.maxDataBytes) {
    return { bytes: total, dropped: 0 };
  }
  const oldest = [...specs.keys()]
    .filter((table) => !KEEP_FOREVER.has(table))
    .flatMap((table) => listPartitions(config.dataDir, table))
    .toSorted((a, b) => a.hour - b.hour);
  let dropped = 0;
  for (const partition of oldest) {
    if (total <= config.maxDataBytes * CAP_TARGET) {
      break;
    }
    const before = filesBytes(partition.files);
    await exclusive(() => {
      removeFiles(partition.files.map((file) => file.path));
    });
    total -= before;
    dropped += 1;
  }
  log('Dropped the oldest partitions to stay under the data cap', {
    dropped,
    bytes: total,
  });
  return { bytes: total, dropped };
};

const COMPACT_MS = 60_000;
const RETENTION_MS = 3_600_000;

export const startMaintenance = () => {
  let lastRetention = 0;
  let running = false;
  const tick = async () => {
    if (running) {
      return;
    }
    running = true;
    try {
      const merged = await compact();
      if (merged > 0) {
        log('Compacted', { files: merged });
      }
      if (Date.now() - lastRetention > RETENTION_MS) {
        lastRetention = Date.now();
        await applyRetention();
        removeEmptyDirs(config.dataDir);
      }
    } catch (error) {
      log('Maintenance failed', { error: String(error).slice(0, 300) });
    } finally {
      running = false;
    }
  };
  const timer = setInterval(() => void tick(), COMPACT_MS);
  return {
    stop: async () => {
      clearInterval(timer);
      while (running) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    },
  };
};

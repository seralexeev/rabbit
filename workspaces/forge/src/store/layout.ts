import {
  closeSync,
  existsSync,
  fsyncSync,
  openSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
} from 'node:fs';
import { dirname, join } from 'node:path';

export const PARQUET = '.parquet';
export const TMP = '.tmp';

const FILE_NAME = /^(\d+)-(\d+)\.parquet$/;
const DATE_DIR = /^date=(\d{4}-\d{2}-\d{2})$/;
const HOUR_DIR = /^hour=(\d{2})$/;
const HOUR_MS = 3_600_000;

export type DataFile = { name: string; path: string; from: number; to: number };

export type Partition = {
  table: string;
  dir: string;
  hour: number;
  files: DataFile[];
};

export const partitionDir = (dataDir: string, table: string, hour: number) => {
  const iso = new Date(hour).toISOString();
  return join(
    dataDir,
    table,
    `date=${iso.slice(0, 10)}`,
    `hour=${iso.slice(11, 13)}`,
  );
};

export const fileName = (from: number, to: number) => `${from}-${to}${PARQUET}`;

export const parseFile = (dir: string, name: string): DataFile | null => {
  const match = FILE_NAME.exec(name);
  return match == null
    ? null
    : {
        name,
        path: join(dir, name),
        from: Number(match[1]),
        to: Number(match[2]),
      };
};

const entries = (dir: string) =>
  existsSync(dir) ? readdirSync(dir, { withFileTypes: true }) : [];

export const tableDirs = (dataDir: string) =>
  entries(dataDir)
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);

export const listPartitions = (dataDir: string, table: string): Partition[] => {
  const partitions: Partition[] = [];
  for (const date of entries(join(dataDir, table))) {
    const day = DATE_DIR.exec(date.name)?.[1];
    if (!date.isDirectory() || day == null) {
      continue;
    }
    for (const hourDir of entries(join(dataDir, table, date.name))) {
      const hour = HOUR_DIR.exec(hourDir.name)?.[1];
      if (!hourDir.isDirectory() || hour == null) {
        continue;
      }
      const dir = join(dataDir, table, date.name, hourDir.name);
      partitions.push({
        table,
        dir,
        hour: Date.parse(`${day}T${hour}:00:00Z`),
        files: entries(dir)
          .flatMap((entry) =>
            entry.isFile() ? [parseFile(dir, entry.name)] : [],
          )
          .filter((file) => file != null)
          .toSorted((a, b) =>
            a.from === b.from ? a.to - b.to : a.from - b.from,
          ),
      });
    }
  }
  return partitions.toSorted((a, b) => a.hour - b.hour);
};

export const hourEnd = (partition: Partition) => partition.hour + HOUR_MS;

export const redundantFiles = (files: DataFile[]) =>
  files.filter((file) =>
    files.some(
      (other) =>
        other !== file &&
        other.from <= file.from &&
        file.to <= other.to &&
        (other.from < file.from || file.to < other.to),
    ),
  );

export const maxFileId = (dataDir: string) => {
  let max = 0;
  for (const table of tableDirs(dataDir)) {
    for (const partition of listPartitions(dataDir, table)) {
      for (const file of partition.files) {
        max = Math.max(max, file.to);
      }
    }
  }
  return max;
};

export const syncDir = (dir: string) => {
  const fd = openSync(dir, 'r');
  try {
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
};

export const syncFile = (path: string) => {
  const fd = openSync(path, 'r+');
  try {
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
};

export const commitFile = (tmp: string, path: string) => {
  syncFile(tmp);
  renameSync(tmp, path);
  syncDir(dirname(path));
};

export const removeFiles = (paths: string[]) => {
  for (const path of paths) {
    rmSync(path, { force: true });
  }
  for (const dir of new Set(paths.map((path) => dirname(path)))) {
    if (existsSync(dir)) {
      syncDir(dir);
    }
  }
};

export const removeEmptyDirs = (dir: string) => {
  if (!existsSync(dir)) {
    return;
  }
  for (const entry of entries(dir)) {
    if (entry.isDirectory()) {
      removeEmptyDirs(join(dir, entry.name));
    }
  }
  if (readdirSync(dir).length === 0) {
    rmSync(dir, { recursive: true, force: true });
  }
};

export const recover = (dataDir: string) => {
  const removed: string[] = [];
  for (const table of tableDirs(dataDir)) {
    for (const partition of listPartitions(dataDir, table)) {
      const stale = [
        ...entries(partition.dir)
          .filter((entry) => entry.isFile() && entry.name.endsWith(TMP))
          .map((entry) => join(partition.dir, entry.name)),
        ...redundantFiles(partition.files).map((file) => file.path),
      ];
      removeFiles(stale);
      removed.push(...stale);
    }
  }
  return removed;
};

export const filesBytes = (files: DataFile[]) =>
  files.reduce(
    (total, file) =>
      total + (statSync(file.path, { throwIfNoEntry: false })?.size ?? 0),
    0,
  );

export const dataBytes = (dataDir: string) =>
  tableDirs(dataDir)
    .flatMap((table) => listPartitions(dataDir, table))
    .reduce((total, partition) => total + filesBytes(partition.files), 0);

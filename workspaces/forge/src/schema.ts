import { readFileSync } from 'node:fs';

import { reader, select, writer } from './clickhouse.ts';
import { ROOT } from './config.ts';

export const migrate = async () => {
  const statements = readFileSync(
    new URL('clickhouse/schema.sql', ROOT),
    'utf8',
  )
    .split(/;\s*$/m)
    .map((statement) => statement.trim())
    .filter((statement) => statement.length > 0);
  for (const query of statements) {
    await writer.command({ query });
  }
  return statements.length;
};

type ColumnRow = {
  table: string;
  name: string;
  type: string;
  comment: string;
};

type TableRow = { name: string; engine: string; comment: string };

type SchemaTable = {
  name: string;
  kind: 'table' | 'view';
  description: string;
  columns: Array<{ name: string; type: string; description?: string }>;
};

const INTERNAL_TABLES = new Set(['run_events']);

export const describeSchema = async (): Promise<SchemaTable[]> => {
  const [tables, columns] = await Promise.all([
    select<TableRow>(
      reader,
      'SELECT name, engine, comment FROM system.tables WHERE database = currentDatabase() ORDER BY name',
    ),
    select<ColumnRow>(
      reader,
      'SELECT table, name, type, comment FROM system.columns WHERE database = currentDatabase() ORDER BY table, position',
    ),
  ]);
  return tables
    .filter((table) => !INTERNAL_TABLES.has(table.name))
    .map((table) => ({
      name: table.name,
      kind: table.engine === 'View' ? 'view' : 'table',
      description: table.comment,
      columns: columns
        .filter((column) => column.table === table.name)
        .map(({ name, type, comment }) =>
          comment.length > 0
            ? { name, type, description: comment }
            : { name, type },
        ),
    }));
};

let tableNames: Promise<ReadonlySet<string>> | null = null;

export const queryableTables = async (): Promise<ReadonlySet<string>> => {
  tableNames ??= describeSchema().then(
    (tables) => new Set(tables.map((table) => table.name)),
    (error: unknown) => {
      tableNames = null;
      throw error;
    },
  );
  return await tableNames;
};

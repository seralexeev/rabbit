import { select, tableSpecs } from './store/engine.ts';

type ColumnRow = { table: string; name: string; type: string };

type SchemaTable = {
  name: string;
  kind: 'table' | 'view';
  description: string;
  columns: Array<{ name: string; type: string; description?: string }>;
};

const INTERNAL_TABLES = new Set(['run_events']);

export const describeSchema = async (): Promise<SchemaTable[]> => {
  const specs = await tableSpecs();
  const [views, viewColumns] = await Promise.all([
    select<{ name: string; comment: string }>(
      "SELECT name, comment FROM system.tables WHERE database = 'forge' ORDER BY name",
    ),
    select<ColumnRow>(
      "SELECT table, name, type FROM system.columns WHERE database = 'forge' ORDER BY table, position",
    ),
  ]);
  return views
    .filter((view) => !INTERNAL_TABLES.has(view.name))
    .map((view): SchemaTable => {
      const spec = specs.get(view.name);
      if (spec == null) {
        return {
          name: view.name,
          kind: 'view',
          description: view.comment,
          columns: viewColumns
            .filter((column) => column.table === view.name)
            .map(({ name, type }) => ({ name, type })),
        };
      }
      return {
        name: spec.name,
        kind: 'table',
        description: spec.comment,
        columns: spec.columns.map(({ name, type, comment }) =>
          comment.length > 0
            ? { name, type, description: comment }
            : { name, type },
        ),
      };
    });
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

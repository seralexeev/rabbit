import { randomUUID } from 'node:crypto';

const MAX_CHART_ROWS = 2000;

type Cell = number | string | null;

export type Row = Record<string, Cell>;

export type Column = { field: string; label: string; unit?: string };

export type Table = {
  kind: 'table';
  title?: string;
  columns: Column[];
  rows: Row[];
  row_count: number;
  truncated: boolean;
};

export type Severity = 'info' | 'warn' | 'alert';

export type Chart = {
  kind: 'chart';
  id?: string;
  chart: {
    type: 'line' | 'area' | 'bar' | 'scatter';
    title: string;
    layout?: 'overlay' | 'stacked';
    x: { field: string; label: string; unit?: string; time?: boolean };
    series: Array<{
      field: string;
      label: string;
      unit?: string;
      axis?: 'left' | 'right';
      panel?: string;
      dashed?: boolean;
    }>;
    rows: Row[];
    markers?: Array<{
      x: number | string;
      x_end?: number | string;
      label: string;
      severity: Severity;
      series?: string;
    }>;
    bands?: Array<{
      field_lo: string;
      field_hi: string;
      label: string;
      series?: string;
    }>;
  };
};

export type GraphEdgeType =
  | 'decomposes_into'
  | 'drives'
  | 'causes'
  | 'explains'
  | 'correlates_with'
  | 'guards'
  | 'symptom_of';

export type GraphView = {
  kind: 'graph';
  id: string;
  title: string;
  nodes: Array<{
    id: string;
    label: string;
    group: string;
    unit?: string;
    role?: 'focus' | 'symptom' | 'cause' | 'context';
    score?: number;
    status?: Severity | 'ok';
    value?: string;
    spark?: number[];
  }>;
  edges: Array<{
    from: string;
    to: string;
    type: GraphEdgeType;
    label: string;
    why: string;
    score?: number;
    lag_s?: number;
  }>;
  highlights: { nodes: string[]; edges: Array<[string, string]> };
  chart?: Chart['chart'];
};

export const outputId = (prefix: string) =>
  `${prefix}-${randomUUID().slice(0, 8)}`;

export const label = (field: string) => field.replaceAll('_', ' ');

const NUMERIC = /^-?\d+(\.\d+)?(e[+-]?\d+)?$/i;

export const cell = (value: unknown): Cell => {
  if (value == null) {
    return null;
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === 'string') {
    return NUMERIC.test(value) ? Number(value) : value;
  }
  if (typeof value === 'boolean') {
    return value ? 1 : 0;
  }
  return JSON.stringify(value);
};

export const toRows = (rows: Array<Record<string, unknown>>): Row[] =>
  rows.map((row) =>
    Object.fromEntries(
      Object.entries(row).map(([key, value]) => [key, cell(value)]),
    ),
  );

export const table = (
  rows: Array<Record<string, unknown>>,
  options: {
    title?: string;
    columns?: Column[];
    rowCount?: number;
    truncated?: boolean;
  } = {},
): Table => ({
  kind: 'table',
  ...(options.title == null ? {} : { title: options.title }),
  columns:
    options.columns ??
    Object.keys(rows[0] ?? {}).map((field) => ({ field, label: label(field) })),
  rows: toRows(rows),
  row_count: options.rowCount ?? rows.length,
  truncated: options.truncated ?? false,
});

export const epochMs = (value: unknown): number | null => {
  if (typeof value === 'number') {
    return value;
  }
  if (typeof value !== 'string') {
    return null;
  }
  const iso = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(value)
    ? `${value.slice(0, 23).replace(' ', 'T')}Z`
    : value;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? null : parsed;
};

export const downsample = <T>(rows: T[], max = MAX_CHART_ROWS): T[] => {
  if (rows.length <= max) {
    return rows;
  }
  const step = rows.length / max;
  return Array.from({ length: max }, (_, i) => rows[Math.floor(i * step)] as T);
};

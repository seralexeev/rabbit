export type Severity = 'info' | 'warn' | 'alert';

export type ChartSpec = {
    type: 'line' | 'area' | 'bar' | 'scatter';
    title?: string;
    layout?: 'overlay' | 'stacked';
    x: { field: string; label?: string; unit?: string; time?: boolean };
    series: {
        field: string;
        label?: string;
        unit?: string;
        axis?: 'left' | 'right';
        panel?: string;
        dashed?: boolean;
    }[];
    rows: Record<string, unknown>[];
    markers?: { x: number | string; x_end?: number | string; label?: string; severity?: Severity; series?: string }[];
    bands?: { field_lo: string; field_hi: string; label?: string; series?: string }[];
};

export type GraphStatus = Severity | 'ok';

export type GraphSpec = {
    id?: string;
    title?: string;
    nodes: {
        id: string;
        label: string;
        group?: string;
        unit?: string;
        role?: 'focus' | 'symptom' | 'cause' | 'context';
        score?: number;
        status?: GraphStatus;
        value?: string;
        spark?: number[];
    }[];
    edges: { from: string; to: string; type: string; label?: string; why?: string; score?: number; lag_s?: number }[];
    highlights?: { nodes?: string[]; edges?: [string, string][] };
    chart?: ChartSpec;
    symptom?: string;
    run_id?: string;
    focus?: { from?: string; to?: string };
};

export type TableSpec = {
    title?: string;
    columns: ({ field: string; label?: string; unit?: string } | string)[];
    rows: (Record<string, unknown> | unknown[])[];
    row_count?: number;
    truncated?: boolean;
};

type Output =
    | { kind: 'chart'; id?: string; chart: ChartSpec; source_rows?: number; downsampled?: boolean }
    | ({ kind: 'graph' } & GraphSpec)
    | ({ kind: 'table' } & TableSpec)
    | ({ kind: 'status' } & Record<string, unknown>);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value != null && !Array.isArray(value);

export const readOutput = (value: unknown): Output | null => {
    if (!isRecord(value)) return null;
    if (value['kind'] === 'chart' && isRecord(value['chart']) && Array.isArray(value['chart']['rows'])) {
        return {
            kind: 'chart',
            chart: value['chart'] as ChartSpec,
            ...(typeof value['id'] === 'string' ? { id: value['id'] } : {}),
            ...(typeof value['source_rows'] === 'number' ? { source_rows: value['source_rows'] } : {}),
            ...(value['downsampled'] === true ? { downsampled: true } : {}),
        };
    }
    if (value['kind'] === 'graph' && Array.isArray(value['nodes']) && Array.isArray(value['edges'])) {
        return value as { kind: 'graph' } & GraphSpec;
    }
    if (value['kind'] === 'table' && Array.isArray(value['columns']) && Array.isArray(value['rows'])) {
        return value as { kind: 'table' } & TableSpec;
    }
    if (value['kind'] === 'status') return value as { kind: 'status' } & Record<string, unknown>;
    return null;
};

export const formatValue = (value: unknown): string => {
    if (value == null) return '—';
    if (typeof value === 'number') {
        if (!Number.isFinite(value)) return String(value);
        if (Number.isInteger(value)) return value.toLocaleString('en-US');
        return Math.abs(value) >= 100 ? value.toFixed(1) : Math.abs(value) >= 1 ? value.toFixed(2) : value.toPrecision(3);
    }
    if (typeof value === 'string' || typeof value === 'boolean') return String(value);
    return JSON.stringify(value);
};

export const summarizeInput = (input: unknown, max = 72) => {
    if (!isRecord(input)) return input == null ? '' : formatValue(input).slice(0, max);
    const text = Object.entries(input)
        .map(([key, value]) => `${key}=${typeof value === 'string' ? value : formatValue(value)}`)
        .join(' ');
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
};

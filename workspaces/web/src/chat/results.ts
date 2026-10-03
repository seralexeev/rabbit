import { type MissionStep, predictWaypoints, readSteps } from '../perception/mission.ts';
import { toNumber } from './charts/plot.ts';
import { type ChartSpec, type GraphSpec, type Severity, type TableSpec, formatValue, readOutput } from './outputs.ts';

export type Point = { x: number; z: number };
export type Pose = Point & { heading: number };
export type Landmark = Point & { label: string; width: number | null; length: number | null; moving: boolean };

export type PathSpec = {
    trail: Point[][];
    plan: Point[];
    start: Pose | Point | null;
    goal: Point | null;
    obstacles: Point[];
    landmarks: Landmark[];
    facts: [string, string][];
};

export type SignalSummary = { signal: string; events: number; severity: Severity | null };

export type TrendSeries = { label: string; unit: string | undefined; values: number[] };

export type Result =
    | { kind: 'series'; id: string | undefined; chart: ChartSpec; note: string | undefined }
    | { kind: 'anomaly'; id: string | undefined; chart: ChartSpec; signals: SignalSummary[] }
    | { kind: 'graph'; id: string | undefined; graph: GraphSpec }
    | { kind: 'path'; title: string; path: PathSpec }
    | { kind: 'status'; status: Record<string, unknown> }
    | { kind: 'table'; table: TableSpec; trend: TrendSeries[]; path: PathSpec | null }
    | { kind: 'fields'; title: string; values: [string, string][] };

const VISUAL = new Set<Result['kind']>(['series', 'anomaly', 'graph']);

export const isChartLike = (result: Result) => VISUAL.has(result.kind);

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value != null && !Array.isArray(value);

const MAX_TREND_SERIES = 6;
const MAX_FIELDS = 8;
const MIN_TREND_ROWS = 3;
const TIME_FIELDS = new Set(['t', 'ts', 'time', 'bucket', 'minute', 'second']);
const SEVERITY_RANK: Record<Severity, number> = { info: 0, warn: 1, alert: 2 };

export const humanize = (key: string) => key.replace(/_/g, ' ');

const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.z - b.z);

const pathLength = (points: Point[]) => points.slice(1).reduce((sum, p, i) => sum + distance(p, points[i] ?? p), 0);

const point = (x: unknown, z: unknown): Point | null => {
    const px = toNumber(x);
    const pz = toNumber(z);
    return px == null || pz == null ? null : { x: px, z: pz };
};

export const missionPath = (steps: MissionStep[], start: Pose, obstacles: Point[]): PathSpec => {
    const waypoints = Array.from({ length: 64 }, () => ({ x: 0, z: 0, marker: false }));
    const count = predictWaypoints(steps, start, waypoints);
    const plan = [start, ...waypoints.slice(0, count)];

    return {
        trail: [],
        plan: plan.map(({ x, z }) => ({ x, z })),
        start,
        goal: count > 0 ? (plan.at(-1) ?? null) : null,
        obstacles,
        landmarks: [],
        facts: [
            ['steps', String(steps.length)],
            ['planned', `${pathLength(plan).toFixed(2)} m`],
        ],
    };
};

const columnsOf = (table: TableSpec) =>
    table.columns.map((column, index) =>
        typeof column === 'string'
            ? { field: column, index, unit: undefined, kind: undefined, measure: undefined }
            : {
                  field: column.field,
                  index,
                  unit: column.unit,
                  kind: (column as { kind?: string }).kind,
                  measure: (column as { measure?: string }).measure,
              },
    );

const cellOf = (row: TableSpec['rows'][number], field: string, index: number) => (Array.isArray(row) ? row[index] : row[field]);

const JUMP_MIN_M = 5;
const JUMP_FACTOR = 10;
const JUMP_SLACK_M = 0.5;

const splitAtJumps = (points: Point[], reported: (number | null)[] | null) => {
    const steps = points.slice(1).map((p, i) => distance(p, points[i] ?? p));
    const moving = steps.filter((step) => step > 0).toSorted((a, b) => a - b);
    const limit = Math.max(JUMP_MIN_M, (moving[Math.floor(moving.length / 2)] ?? 0) * JUMP_FACTOR);
    const isJump = (step: number, i: number) => {
        const counted = reported?.[i + 1];
        return step > limit || (counted != null && step > counted + JUMP_SLACK_M);
    };
    const segments: Point[][] = [[points[0]!]];
    steps.forEach((step, i) => {
        const p = points[i + 1]!;
        if (isJump(step, i)) segments.push([p]);
        else segments.at(-1)!.push(p);
    });
    return segments;
};

const tablePath = (table: TableSpec): PathSpec | null => {
    const columns = columnsOf(table);
    const xs = columns.find((column) => column.field === 'x');
    const zs = columns.find((column) => column.field === 'z');
    if (xs == null || zs == null) return null;
    const stepColumn = columns.find((column) => column.field === 'step_m');
    const samples = table.rows.flatMap((row) => {
        const p = point(cellOf(row, 'x', xs.index), cellOf(row, 'z', zs.index));
        return p == null ? [] : [{ p, step: stepColumn == null ? null : toNumber(cellOf(row, 'step_m', stepColumn.index)) }];
    });
    const trail = samples.map(({ p }) => p);
    if (trail.length < 2) return null;
    const segments = splitAtJumps(trail, stepColumn == null ? null : samples.map(({ step }) => step));
    const distanceColumn = columns.find((column) => column.field === 'distance_m');
    const travelled =
        distanceColumn == null
            ? pathLength(trail)
            : toNumber(cellOf(table.rows.at(-1) ?? {}, 'distance_m', distanceColumn.index));
    const first = trail[0] ?? null;
    const last = trail.at(-1) ?? null;
    return {
        trail: segments,
        plan: [],
        start: first,
        goal: last,
        obstacles: [],
        landmarks: [],
        facts: [
            ['samples', trail.length.toLocaleString('en-US')],
            ...(segments.length > 1 ? [['tracking jumps', String(segments.length - 1)] as [string, string]] : []),
            ...(travelled == null ? [] : [['travelled', `${travelled.toFixed(2)} m`] as [string, string]]),
            ...(first == null || last == null ? [] : [['net', `${distance(last, first).toFixed(2)} m`] as [string, string]]),
        ],
    };
};

const MOVING_LABELS = new Set(['person', 'cat', 'dog', 'robot vacuum']);

const tableObjects = (table: TableSpec): PathSpec | null => {
    const columns = columnsOf(table);
    const find = (field: string) => columns.find((column) => column.field === field);
    const labels = find('label');
    const xs = find('x');
    const zs = find('z');
    if (labels == null || xs == null || zs == null) return null;
    const widths = find('width_m');
    const lengths = find('length_m');
    const size = (row: TableSpec['rows'][number], column: typeof widths) =>
        column == null ? null : toNumber(cellOf(row, column.field, column.index));
    const landmarks = table.rows.flatMap((row) => {
        const p = point(cellOf(row, 'x', xs.index), cellOf(row, 'z', zs.index));
        const label = cellOf(row, 'label', labels.index);
        if (p == null || typeof label !== 'string') return [];
        return [{ ...p, label, width: size(row, widths), length: size(row, lengths), moving: MOVING_LABELS.has(label) }];
    });
    if (landmarks.length === 0) return null;
    return {
        trail: [],
        plan: [],
        start: null,
        goal: null,
        obstacles: [],
        landmarks,
        facts: [
            ['objects', String(landmarks.length)],
            ['classes', String(new Set(landmarks.map((landmark) => landmark.label)).size)],
        ],
    };
};

const tableTrend = (table: TableSpec): TrendSeries[] => {
    if (table.rows.length < MIN_TREND_ROWS) return [];
    const columns = columnsOf(table);
    const time = columns.find((column) => column.kind === 'time' || TIME_FIELDS.has(column.field));
    if (time == null) return [];
    return columns
        .filter((column) => column !== time && column.kind == null && column.measure !== 'event')
        .flatMap((column) => {
            const values = table.rows.map((row) => toNumber(cellOf(row, column.field, column.index)) ?? Number.NaN);
            const finite = values.filter(Number.isFinite);
            if (finite.length < MIN_TREND_ROWS || Math.min(...finite) === Math.max(...finite)) return [];
            return [{ label: humanize(column.field), unit: column.unit, values }];
        })
        .slice(0, MAX_TREND_SERIES);
};

const signalsOf = (value: Record<string, unknown>): SignalSummary[] =>
    (Array.isArray(value['per_signal']) ? value['per_signal'] : []).filter(isRecord).map((signal) => {
        const events = (Array.isArray(signal['events']) ? signal['events'] : []).filter(isRecord);
        const severity = events.reduce<Severity | null>((worst, event) => {
            const level = event['severity'];
            if (level !== 'info' && level !== 'warn' && level !== 'alert') return worst;
            return worst == null || SEVERITY_RANK[level] > SEVERITY_RANK[worst] ? level : worst;
        }, null);
        return {
            signal: humanize(String(signal['signal'] ?? '')),
            events: typeof signal['event_count'] === 'number' ? signal['event_count'] : events.length,
            severity,
        };
    });

const actionFields = (value: Record<string, unknown>): [string, string][] | null => {
    if (value['ok'] !== true) return null;
    const entries = Object.entries(value).filter(([key, field]) => key !== 'ok' && key !== 'kind' && field != null);
    if (entries.length === 0 || entries.length > MAX_FIELDS) return null;
    if (entries.some(([, field]) => typeof field === 'object')) return null;
    return entries.map(([key, field]) => [humanize(key), formatValue(field)]);
};

const readPose = (value: unknown): Pose | null => {
    if (!isRecord(value)) return null;
    const p = point(value['x'], value['z']);
    return p == null ? null : { ...p, heading: toNumber(value['heading_deg']) ?? 0 };
};

const readPoints = (value: unknown): Point[] =>
    (Array.isArray(value) ? value : []).flatMap((item) => {
        const p = isRecord(item) ? point(item['x'], item['z']) : null;
        return p == null ? [] : [p];
    });

const routePath = (raw: Record<string, unknown>, start: Pose, route: Point[]): PathSpec => {
    const target = isRecord(raw['target']) ? raw['target'] : null;
    const landmark = target == null ? null : point(target['x'], target['z']);
    const label = target == null ? null : String(target['label'] ?? target['kind'] ?? '');
    return {
        trail: [],
        plan: [start, ...route],
        start,
        goal: route.at(-1) ?? null,
        obstacles: [],
        landmarks:
            landmark == null || target?.['kind'] === 'point'
                ? []
                : [{ ...landmark, label: label ?? '', width: null, length: null, moving: false }],
        facts: [
            ['route', `${formatValue(raw['path_length_m'])} m`],
            ['planned in', `${formatValue(raw['plan_ms'])} ms`],
        ],
    };
};

export const readResult = (tool: string, raw: unknown): Result | null => {
    const output = readOutput(raw);
    if (output?.kind === 'chart') {
        const value = raw as Record<string, unknown>;
        if (Array.isArray(value['per_signal']))
            return { kind: 'anomaly', id: output.id, chart: output.chart, signals: signalsOf(value) };
        return {
            kind: 'series',
            id: output.id,
            chart: output.chart,
            note:
                output.downsampled === true && output.source_rows != null
                    ? `DOWNSAMPLED · ${output.source_rows.toLocaleString('en-US')} SOURCE ROWS`
                    : undefined,
        };
    }
    if (output?.kind === 'graph') return { kind: 'graph', id: output.id, graph: output };
    if (output?.kind === 'status') return { kind: 'status', status: output };
    if (output?.kind === 'table')
        return { kind: 'table', table: output, trend: tableTrend(output), path: tableObjects(output) ?? tablePath(output) };
    if (!isRecord(raw)) return null;
    const steps = readSteps(raw);
    const start = readPose(raw['start']);
    if (steps != null && start != null)
        return { kind: 'path', title: 'Mission sent', path: missionPath(steps, start, readPoints(raw['obstacles'])) };
    const route = readPoints(raw['route']);
    if (route.length > 1 && start != null)
        return {
            kind: 'path',
            title: raw['phase'] === 'planned' ? 'Route preview' : `Trip to ${String((isRecord(raw['target']) && raw['target']['label']) || 'point')}`,
            path: routePath(raw, start, route),
        };
    const fields = actionFields(raw);
    return fields == null ? null : { kind: 'fields', title: humanize(tool), values: fields };
};

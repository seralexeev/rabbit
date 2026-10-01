import uPlot from 'uplot';

import { type ChartSpec, type Severity, formatValue } from '../outputs.ts';

export const FONT = '10px "JetBrains Mono", monospace';
const TICK = 'rgba(98, 232, 255, 0.65)';
const GRID = 'rgba(98, 232, 255, 0.08)';
export const COLORS = ['#62e8ff', '#ffb547', '#b99bff', '#7dffb6', '#ff7aa8', '#9fd4ff', '#ffd966', '#ff9a6b'];
export const SEVERITY: Record<Severity, string> = { info: '#62e8ff', warn: '#ffb547', alert: '#ff5a4a' };
const PANEL_MIN_HEIGHT = 84;

type SeriesSpec = ChartSpec['series'][number];

export type Panel = {
    key: string;
    series: { spec: SeriesSpec; color: string }[];
    bands: NonNullable<ChartSpec['bands']>;
    markers: { marker: NonNullable<ChartSpec['markers']>[number]; number: number }[];
};

export const utcTime = (seconds: number) => new Date(seconds * 1000).toISOString().slice(11, 19);

export const toNumber = (value: unknown) => {
    const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : Number.NaN;
    return Number.isFinite(n) ? n : null;
};

export const withAlpha = (hex: string, alpha: number) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};

const bars = uPlot.paths.bars?.({ size: [0.6, 64] });

const panelKey = (chart: ChartSpec, spec: SeriesSpec) =>
    chart.layout === 'stacked' ? (spec.panel ?? spec.unit ?? 'main') : 'main';

export const panelsOf = (chart: ChartSpec): Panel[] => {
    const panels: Panel[] = [];
    chart.series.forEach((spec, i) => {
        const key = panelKey(chart, spec);
        let panel = panels.find((candidate) => candidate.key === key);
        if (panel == null) {
            panel = { key, series: [], bands: [], markers: [] };
            panels.push(panel);
        }
        const solid = panel.series.find((item) => item.spec.dashed !== true);
        const color =
            spec.dashed === true && solid != null ? solid.color : (COLORS[i % COLORS.length] ?? COLORS[0] ?? '#62e8ff');
        panel.series.push({ spec, color });
    });
    const owner = (field: string | undefined) =>
        (field == null ? null : panels.find((panel) => panel.series.some((item) => item.spec.field === field))) ?? null;
    for (const band of chart.bands ?? []) {
        (owner(band.series) ?? panels[0])?.bands.push(band);
    }
    (chart.markers ?? []).forEach((marker, i) => {
        const target = owner(marker.series);
        for (const panel of target == null ? panels : [target]) panel.markers.push({ marker, number: i + 1 });
    });
    return panels;
};

export const scaleOf = (spec: SeriesSpec) =>
    spec.unit != null && spec.unit !== '' ? `u:${spec.unit}` : spec.axis === 'right' ? 'y2' : 'y';

export const xAxisOf = (chart: ChartSpec) => {
    const rawX = chart.rows.map((row) => row[chart.x.field]);
    const numeric = rawX.every((value) => toNumber(value) != null);
    const time = numeric && chart.x.time === true;
    const categories = numeric ? null : rawX.map((value) => formatValue(value));
    const xs = rawX.map((value, i) => (numeric ? (toNumber(value) ?? 0) / (time ? 1000 : 1) : i));
    const toX = (value: number | string) =>
        categories == null ? (toNumber(value) ?? 0) / (time ? 1000 : 1) : Math.max(0, categories.indexOf(String(value)));
    return { xs, time, categories, toX };
};

export const panelData = (chart: ChartSpec, panel: Panel, xs: number[]): uPlot.AlignedData =>
    [xs, ...panel.series.map(({ spec }) => chart.rows.map((row) => toNumber(row[spec.field])))] as uPlot.AlignedData;

const axis = (scale: string, side: number, grid: boolean, label?: string): uPlot.Axis => ({
    scale,
    side,
    stroke: TICK,
    font: FONT,
    size: 44,
    gap: 3,
    grid: { show: grid, stroke: GRID, width: 1 },
    ticks: { stroke: GRID, width: 1, size: 3 },
    ...(label == null ? {} : { label, labelFont: FONT, labelSize: 12, labelGap: 0 }),
    values: (_: uPlot, ticks: number[]) => ticks.map((tick) => formatValue(tick)),
});

type Draw = { chart: () => ChartSpec; toX: (value: number | string) => number };

const drawBands = (u: uPlot, panel: Panel, draw: Draw) => {
    if (panel.bands.length === 0) return;
    const chart = draw.chart();
    const { ctx, bbox } = u;
    const xs = u.data[0];
    ctx.save();
    ctx.beginPath();
    ctx.rect(bbox.left, bbox.top, bbox.width, bbox.height);
    ctx.clip();
    for (const band of panel.bands) {
        const owner = panel.series.find((item) => item.spec.field === band.series) ?? panel.series[0];
        if (owner == null) continue;
        const scale = scaleOf(owner.spec);
        ctx.fillStyle = withAlpha(owner.color, 0.14);
        let segment: { x: number; lo: number; hi: number }[] = [];
        const flush = () => {
            if (segment.length > 1) {
                ctx.beginPath();
                segment.forEach((point, i) => (i === 0 ? ctx.moveTo(point.x, point.hi) : ctx.lineTo(point.x, point.hi)));
                for (let i = segment.length - 1; i >= 0; i--) {
                    const point = segment[i];
                    if (point != null) ctx.lineTo(point.x, point.lo);
                }
                ctx.closePath();
                ctx.fill();
            }
            segment = [];
        };
        chart.rows.forEach((row, i) => {
            const lo = toNumber(row[band.field_lo]);
            const hi = toNumber(row[band.field_hi]);
            const x = xs[i];
            if (lo == null || hi == null || x == null) {
                flush();
                return;
            }
            segment.push({
                x: u.valToPos(x, 'x', true),
                lo: u.valToPos(lo, scale, true),
                hi: u.valToPos(hi, scale, true),
            });
        });
        flush();
    }
    ctx.restore();
};

const drawMarkers = (u: uPlot, panel: Panel, draw: Draw, showNumbers: boolean) => {
    if (panel.markers.length === 0) return;
    const { ctx, bbox } = u;
    const ratio = devicePixelRatio;
    ctx.save();
    ctx.font = `${Math.round(9 * ratio)}px "JetBrains Mono", monospace`;
    ctx.textBaseline = 'top';
    for (const { marker, number } of panel.markers) {
        const color = SEVERITY[marker.severity ?? 'info'];
        const x = u.valToPos(draw.toX(marker.x), 'x', true);
        if (marker.x_end != null) {
            const end = u.valToPos(draw.toX(marker.x_end), 'x', true);
            const left = Math.max(bbox.left, Math.min(x, end));
            const right = Math.min(bbox.left + bbox.width, Math.max(x, end, x + ratio * 2));
            if (right < bbox.left || left > bbox.left + bbox.width) continue;
            ctx.fillStyle = withAlpha(color, marker.severity == null || marker.severity === 'info' ? 0.07 : 0.14);
            ctx.fillRect(left, bbox.top, right - left, bbox.height);
            ctx.fillStyle = color;
            ctx.fillRect(left, bbox.top, right - left, 2 * ratio);
            if (showNumbers) ctx.fillText(String(number), left + 2 * ratio, bbox.top + 3 * ratio);
            continue;
        }
        const px = Math.round(x);
        if (px < bbox.left || px > bbox.left + bbox.width) continue;
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = ratio;
        ctx.setLineDash([3 * ratio, 3 * ratio]);
        ctx.beginPath();
        ctx.moveTo(px, bbox.top);
        ctx.lineTo(px, bbox.top + bbox.height);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(px - 4 * ratio, bbox.top);
        ctx.lineTo(px + 4 * ratio, bbox.top);
        ctx.lineTo(px, bbox.top + 6 * ratio);
        ctx.fill();
        if (showNumbers) ctx.fillText(String(number), px + 5 * ratio, bbox.top + 2 * ratio);
    }
    ctx.restore();
};

export const panelHeight = (panels: number, height: number) =>
    panels <= 1 ? height : Math.max(PANEL_MIN_HEIGHT, Math.round(height * 0.6));

const observedRange =
    (panel: Panel, scale: string): uPlot.Range.Function =>
    (u, min, max) => {
        let low = Number.POSITIVE_INFINITY;
        let high = Number.NEGATIVE_INFINITY;
        panel.series.forEach(({ spec }, i) => {
            if (spec.dashed === true || scaleOf(spec) !== scale) return;
            for (const value of u.data[i + 1] ?? []) {
                if (value == null) continue;
                low = Math.min(low, value);
                high = Math.max(high, value);
            }
        });
        if (!Number.isFinite(low)) return [min, max];
        const pad = (high - low || Math.abs(high) || 1) * 0.12;
        return [low - pad, high + pad];
    };

export const buildOptions = ({
    chart,
    panel,
    width,
    height,
    last,
    syncKey,
    draw,
}: {
    chart: ChartSpec;
    panel: Panel;
    width: number;
    height: number;
    last: boolean;
    syncKey: string;
    draw: Draw;
}): uPlot.Options => {
    const { time, categories } = xAxisOf(chart);
    const series: uPlot.Series[] = [
        {
            label: chart.x.label ?? chart.x.field,
            value: (_, v) => (v == null ? '—' : time ? `${utcTime(v)} UTC` : (categories?.[v] ?? formatValue(v))),
        },
    ];
    const scales: uPlot.Scales = { x: { time } };
    const scaleUnits: { scale: string; unit: string | undefined }[] = [];
    for (const { spec, color } of panel.series) {
        const scale = scaleOf(spec);
        if (!scaleUnits.some((item) => item.scale === scale)) {
            scaleUnits.push({ scale, unit: spec.unit });
            scales[scale] = { range: observedRange(panel, scale) };
        }
        const unit = spec.unit == null ? '' : ` ${spec.unit}`;
        series.push({
            label: spec.label ?? spec.field,
            scale,
            stroke: spec.dashed === true ? withAlpha(color, 0.7) : color,
            width: spec.dashed === true ? 1 : 1.25,
            ...(spec.dashed === true ? { dash: [4, 3] } : {}),
            ...(chart.type === 'area' ? { fill: withAlpha(color, 0.12) } : {}),
            ...(chart.type === 'bar' ? { fill: withAlpha(color, 0.45), ...(bars == null ? {} : { paths: bars }) } : {}),
            ...(chart.type === 'scatter' ? { paths: () => null } : {}),
            points: { show: chart.type === 'scatter', size: 4, fill: color, stroke: color },
            value: (_, v) => (v == null ? '—' : `${formatValue(v)}${unit}`),
        });
    }
    const labelled = scaleUnits.length > 1 || chart.layout === 'stacked';
    const yAxes = scaleUnits.map(({ scale, unit }, i) =>
        axis(scale, i % 2 === 0 ? 3 : 1, i === 0, labelled ? unit : undefined),
    );
    const xAxis: uPlot.Axis = {
        ...axis('x', 2, true),
        space: 72,
        size: last ? 26 : 6,
        ...(last
            ? categories != null
                ? { values: (_: uPlot, ticks: number[]) => ticks.map((tick) => categories[Math.round(tick)] ?? '') }
                : time
                  ? { values: (_: uPlot, ticks: number[]) => ticks.map((tick) => utcTime(tick).slice(0, 8)) }
                  : {}
            : { values: (_: uPlot, ticks: number[]) => ticks.map(() => '') }),
    };
    return {
        width,
        height,
        series,
        scales,
        tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), 'Etc/UTC'),
        axes: [xAxis, ...yAxes],
        cursor: {
            drag: { x: true, y: false, setScale: true },
            points: { size: 6 },
            sync: { key: syncKey, setSeries: false },
        },
        legend: { show: true, live: true },
        hooks: {
            drawClear: [(u) => drawBands(u, panel, draw)],
            draw: [(u) => drawMarkers(u, panel, draw, true)],
        },
    };
};

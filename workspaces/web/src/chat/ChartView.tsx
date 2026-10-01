import { css } from '@emotion/css';
import React from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

import { buildOptions, panelData, panelHeight, panelsOf, xAxisOf } from './charts/plot.ts';
import type { ChartSpec } from './outputs.ts';

const HEIGHT = 180;
const VISIBLE_MARKERS = 3;

const structureOf = (chart: ChartSpec) =>
    JSON.stringify([chart.type, chart.layout ?? null, chart.x, chart.series, chart.bands ?? null, chart.markers ?? null]);

type ChartViewProps = { chart: ChartSpec; height?: number | undefined; note?: string | undefined };

export const ChartView: React.FC<ChartViewProps> = ({ chart, height = HEIGHT, note }) => {
    const ref = React.useRef<HTMLDivElement | null>(null);
    const plotsRef = React.useRef<uPlot[]>([]);
    const chartRef = React.useRef(chart);
    const [zoomed, setZoomed] = React.useState(false);
    const [allMarkers, setAllMarkers] = React.useState(false);
    const syncKey = `chart-${React.useId()}`;
    const structure = structureOf(chart);

    React.useEffect(() => {
        chartRef.current = chart;
        const plots = plotsRef.current;
        if (plots.length === 0) return;
        const { xs } = xAxisOf(chart);
        panelsOf(chart).forEach((panel, i) => plots[i]?.setData(panelData(chart, panel, xs)));
    }, [chart]);

    React.useEffect(() => {
        const host = ref.current;
        if (host == null) return;
        const current = chartRef.current;
        const panels = panelsOf(current);
        const each = panelHeight(panels.length, height);
        const draw = { chart: () => chartRef.current, toX: (value: number | string) => xAxisOf(chartRef.current).toX(value) };
        let syncing = false;
        const plots: uPlot[] = [];
        const { xs } = xAxisOf(current);
        panels.forEach((panel, i) => {
            const options = buildOptions({
                chart: current,
                panel,
                width: Math.max(host.clientWidth, 200),
                height: each,
                last: i === panels.length - 1,
                syncKey,
                draw,
            });
            options.hooks = {
                ...options.hooks,
                setScale: [
                    (u, key) => {
                        if (key !== 'x' || syncing) return;
                        syncing = true;
                        const { min, max } = u.scales['x'] ?? {};
                        const full = u.data[0];
                        setZoomed(min != null && max != null && (min > (full[0] ?? min) || max < (full.at(-1) ?? max)));
                        for (const other of plots) {
                            if (other !== u && min != null && max != null) other.setScale('x', { min, max });
                        }
                        syncing = false;
                    },
                ],
            };
            const cell = document.createElement('div');
            host.appendChild(cell);
            plots.push(new uPlot(options, panelData(current, panel, xs), cell));
        });
        plotsRef.current = plots;
        let width = host.clientWidth;
        const observer = new ResizeObserver(() => {
            if (host.clientWidth === width || host.clientWidth === 0) return;
            width = host.clientWidth;
            for (const plot of plots) plot.setSize({ width, height: each });
        });
        observer.observe(host);
        return () => {
            observer.disconnect();
            for (const plot of plots) plot.destroy();
            host.replaceChildren();
            plotsRef.current = [];
        };
    }, [structure, height, syncKey]);

    const resetZoom = () => {
        for (const plot of plotsRef.current) {
            const xs = plot.data[0];
            const min = xs[0];
            const max = xs.at(-1);
            if (min != null && max != null) plot.setScale('x', { min, max });
        }
        setZoomed(false);
    };

    const markers = chart.markers ?? [];

    return (
        <figure className={figureCss}>
            {(chart.title != null || zoomed) && (
                <figcaption className={captionCss}>
                    <span>{chart.title ?? ''}</span>
                    {zoomed && (
                        <button className={resetCss} onClick={resetZoom}>
                            RESET ZOOM
                        </button>
                    )}
                </figcaption>
            )}
            <div ref={ref} className={plotCss} />
            {chart.rows.length === 0 && <div className={emptyCss}>NO DATA</div>}
            {note != null && <div className={noteCss}>{note}</div>}
            {markers.length > 0 && (
                <ol className={markersCss}>
                    {(allMarkers ? markers : markers.slice(0, VISIBLE_MARKERS)).map((marker, i) => (
                        <li key={i} data-severity={marker.severity ?? 'info'}>
                            <span>{i + 1}</span>
                            {marker.label ?? ''}
                        </li>
                    ))}
                    {markers.length > VISIBLE_MARKERS && (
                        <li>
                            <button className={moreCss} onClick={() => setAllMarkers((value) => !value)}>
                                {allMarkers ? '▴ fewer' : `▸ ${markers.length - VISIBLE_MARKERS} more`}
                            </button>
                        </li>
                    )}
                </ol>
            )}
        </figure>
    );
};

const figureCss = css`
    position: relative;
    margin: 0;
`;

const captionCss = css`
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 4px;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    opacity: 0.85;

    & > span {
        flex: 1;
    }
`;

const resetCss = css`
    padding: 0 4px;
    border: 1px solid var(--hud-faint);
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 8px;
    cursor: pointer;

    &:hover {
        background: var(--hud-faint);
    }
`;

const plotCss = css`
    width: 100%;

    & .u-legend {
        display: block;
        margin-top: 2px;
        font-size: 9px;
        color: var(--hud);
        text-align: left;
    }

    & .u-legend .u-series {
        display: inline-flex !important;
        align-items: center;
        margin-right: 10px;
        cursor: pointer;
    }

    & .u-legend .u-series.u-off {
        opacity: 0.35;
    }

    & .u-legend th,
    & .u-legend td {
        padding: 0 2px;
    }

    & .u-legend .u-marker {
        width: 8px;
        height: 2px;
        border: none !important;
    }

    & .u-legend th {
        font-weight: 400;
        opacity: 0.7;
    }

    & .u-select {
        background: rgba(98, 232, 255, 0.12);
    }

    & .u-cursor-x,
    & .u-cursor-y {
        border-color: rgba(98, 232, 255, 0.45) !important;
    }
`;

const noteCss = css`
    margin-top: 2px;
    font-size: 8px;
    letter-spacing: 0.1em;
    opacity: 0.55;
`;

const markersCss = css`
    margin: 4px 0 2px;
    padding: 0;
    list-style: none;
    font-size: 9px;
    text-transform: none;

    & li {
        display: flex;
        gap: 6px;
        color: var(--hud);
    }

    & li[data-severity='warn'] {
        color: var(--hud-amber);
    }

    & li[data-severity='alert'] {
        color: var(--hud-alert);
    }

    & li > span {
        min-width: 12px;
        font-weight: 700;
    }
`;

const moreCss = css`
    padding: 0;
    border: none;
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 9px;
    cursor: pointer;
    opacity: 0.6;

    &:hover {
        opacity: 1;
    }
`;

const emptyCss = css`
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.5;
`;

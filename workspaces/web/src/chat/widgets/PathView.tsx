import { css } from '@emotion/css';
import React from 'react';

import type { PathSpec, Point, Pose } from '../results.ts';

const MIN_SPAN_M = 1;
const MAX_TRAIL_POINTS = 600;
const GRID_STEPS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 25];
const MAX_GRID_LINES = 8;
const GRID_REACH = 2;
const ROBUST_MIN_POINTS = 20;
const CORE_LOW = 0.05;
const CORE_HIGH = 0.95;

const thin = (points: Point[]) => {
    if (points.length <= MAX_TRAIL_POINTS) return points;
    const step = points.length / MAX_TRAIL_POINTS;
    return [...Array.from({ length: MAX_TRAIL_POINTS - 1 }, (_, i) => points[Math.floor(i * step)]!), points.at(-1)!];
};

const quantile = (sorted: number[], q: number) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] ?? 0;

const robustCore = (points: Point[]) => {
    if (points.length < ROBUST_MIN_POINTS) return points;
    const xs = points.map((p) => p.x).toSorted((a, b) => a - b);
    const zs = points.map((p) => p.z).toSorted((a, b) => a - b);
    return [
        { x: quantile(xs, CORE_LOW), z: quantile(zs, CORE_LOW) },
        { x: quantile(xs, CORE_HIGH), z: quantile(zs, CORE_HIGH) },
    ];
};

const boundsOf = (points: Point[]) => {
    const xs = points.map((p) => p.x);
    const zs = points.map((p) => p.z);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cz = (Math.min(...zs) + Math.max(...zs)) / 2;
    const span = Math.max(MIN_SPAN_M, Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs)) * 1.25;
    return { cx, cz, span };
};

const polyline = (points: Point[]) => points.map((p) => `${p.x.toFixed(3)},${p.z.toFixed(3)}`).join(' ');

const isPose = (value: Point | Pose): value is Pose => 'heading' in value;

const arrow = (pose: Pose, size: number) => {
    const h = (pose.heading * Math.PI) / 180;
    const fx = Math.sin(h);
    const fz = -Math.cos(h);
    const at = (along: number, across: number) => ({
        x: pose.x + (fx * along - fz * across) * size,
        z: pose.z + (fz * along + fx * across) * size,
    });
    return polyline([at(1.4, 0), at(-0.7, -0.6), at(-0.3, 0), at(-0.7, 0.6)]);
};

type PathViewProps = { path: PathSpec; title?: string; height?: number };

export const PathView: React.FC<PathViewProps> = ({ path, title, height = 170 }) => {
    const trail = path.trail.map(thin);
    const all = [
        ...robustCore(trail.flat()),
        ...path.plan,
        ...path.obstacles,
        ...path.landmarks,
        ...(path.start == null ? [] : [path.start]),
    ];
    if (all.length === 0) return null;
    const { cx, cz, span } = boundsOf(all);
    const grid = GRID_STEPS.find((step) => span / step <= MAX_GRID_LINES) ?? GRID_STEPS.at(-1)!;
    const reach = span * GRID_REACH;
    const gridLines = (center: number) =>
        Array.from({ length: Math.ceil((2 * reach) / grid) + 1 }, (_, k) => (Math.floor((center - reach) / grid) + k) * grid);
    const lines = gridLines(cx);
    const linesZ = gridLines(cz);
    const r = span * 0.018;
    const left = cx - span / 2;
    const top = cz - span / 2;

    return (
        <figure className={figureCss}>
            {title != null && <figcaption className={captionCss}>{title}</figcaption>}
            <div className={bodyCss}>
                <svg
                    className={svgCss}
                    style={{ height }}
                    viewBox={`${left} ${top} ${span} ${span}`}
                    preserveAspectRatio='xMidYMid meet'
                    role='img'
                    aria-label='Top-down path'>
                    <g data-layer='grid'>
                        {lines.map((x) => (
                            <line key={`x${x}`} x1={x} x2={x} y1={cz - reach} y2={cz + reach} data-axis={Math.abs(x) < 1e-9} />
                        ))}
                        {linesZ.map((z) => (
                            <line key={`z${z}`} y1={z} y2={z} x1={cx - reach} x2={cx + reach} data-axis={Math.abs(z) < 1e-9} />
                        ))}
                    </g>
                    {trail.map(
                        (segment, i) =>
                            segment.length > 1 && <polyline key={i} points={polyline(segment)} data-layer='trail' />,
                    )}
                    {path.plan.length > 1 && <polyline points={polyline(path.plan)} data-layer='plan' />}
                    {path.plan.slice(1).map((p, i) => (
                        <circle key={i} cx={p.x} cy={p.z} r={r * 0.55} data-layer='waypoint' />
                    ))}
                    {path.obstacles.map((p, i) => (
                        <g key={i} data-layer='obstacle'>
                            <line x1={p.x - r} x2={p.x + r} y1={p.z - r} y2={p.z + r} />
                            <line x1={p.x - r} x2={p.x + r} y1={p.z + r} y2={p.z - r} />
                        </g>
                    ))}
                    {path.landmarks.map((landmark, i) => {
                        const w = Math.max(landmark.width ?? 0, r * 2);
                        const l = Math.max(landmark.length ?? 0, r * 2);
                        return (
                            <g key={i} data-layer='landmark' data-moving={landmark.moving}>
                                <rect x={landmark.x - w / 2} y={landmark.z - l / 2} width={w} height={l} />
                                <text x={landmark.x} y={landmark.z - l / 2 - r * 0.6} fontSize={r * 2.6}>
                                    {landmark.label.toUpperCase()}
                                </text>
                            </g>
                        );
                    })}
                    {path.goal != null && (
                        <rect
                            x={path.goal.x - r}
                            y={path.goal.z - r}
                            width={r * 2}
                            height={r * 2}
                            transform={`rotate(45 ${path.goal.x} ${path.goal.z})`}
                            data-layer='goal'
                        />
                    )}
                    {path.start != null &&
                        (isPose(path.start) ? (
                            <polygon points={arrow(path.start, r * 2.4)} data-layer='robot' />
                        ) : (
                            <circle cx={path.start.x} cy={path.start.z} r={r} data-layer='start' />
                        ))}
                </svg>
                <div className={scaleCss}>GRID {grid} M · -Z UP</div>
            </div>
            <div className={legendCss}>
                {trail.length > 0 && <span data-key='trail'>TRAIL</span>}
                {path.plan.length > 1 && <span data-key='plan'>PLAN</span>}
                {path.obstacles.length > 0 && <span data-key='obstacle'>OBSTACLE</span>}
                {path.landmarks.length > 0 && <span data-key='landmark'>OBJECT</span>}
                {path.facts.map(([label, value]) => (
                    <span key={label} className={factCss}>
                        {label} <b>{value}</b>
                    </span>
                ))}
            </div>
        </figure>
    );
};

const figureCss = css`
    margin: 0;
`;

const captionCss = css`
    margin-bottom: 4px;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    opacity: 0.7;
`;

const bodyCss = css`
    position: relative;
    background: #020709;
    box-shadow: inset 0 0 0 1px var(--hud-faint);
`;

const svgCss = css`
    display: block;
    width: 100%;

    & * {
        vector-effect: non-scaling-stroke;
    }

    & [data-layer='grid'] line {
        stroke: rgba(98, 232, 255, 0.07);
        stroke-width: 1;
    }

    & [data-layer='grid'] line[data-axis='true'] {
        stroke: rgba(98, 232, 255, 0.2);
    }

    & polyline {
        fill: none;
        stroke-width: 1.6;
        stroke-linejoin: round;
        stroke-linecap: round;
    }

    & [data-layer='trail'] {
        stroke: var(--hud);
        filter: drop-shadow(0 0 2px var(--hud-glow));
    }

    & [data-layer='plan'] {
        stroke: var(--hud-amber);
        stroke-dasharray: 4 3;
    }

    & [data-layer='waypoint'] {
        fill: var(--hud-amber);
    }

    & [data-layer='obstacle'] line {
        stroke: var(--hud-alert);
        stroke-width: 1.6;
    }

    & [data-layer='goal'] {
        fill: none;
        stroke: var(--hud-amber);
        stroke-width: 1.4;
    }

    & [data-layer='landmark'] rect {
        fill: rgba(232, 251, 255, 0.08);
        stroke: #e8fbff;
        stroke-width: 1.2;
    }

    & [data-layer='landmark'] text {
        fill: #e8fbff;
        text-anchor: middle;
        font-weight: 600;
        letter-spacing: 0.04em;
    }

    & [data-layer='landmark'][data-moving='true'] rect {
        stroke: var(--hud-amber);
        fill: rgba(255, 181, 71, 0.08);
    }

    & [data-layer='landmark'][data-moving='true'] text {
        fill: var(--hud-amber);
    }

    & [data-layer='robot'] {
        fill: var(--hud);
        filter: drop-shadow(0 0 3px var(--hud-glow));
    }

    & [data-layer='start'] {
        fill: #020709;
        stroke: var(--hud);
        stroke-width: 1.4;
    }
`;

const scaleCss = css`
    position: absolute;
    right: 4px;
    bottom: 2px;
    font-size: 7.5px;
    letter-spacing: 0.1em;
    opacity: 0.45;
`;

const legendCss = css`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px 10px;
    margin-top: 3px;
    font-size: 8.5px;
    letter-spacing: 0.06em;

    & > [data-key]::before {
        content: '';
        display: inline-block;
        width: 10px;
        height: 2px;
        margin-right: 4px;
        vertical-align: middle;
        background: var(--hud);
    }

    & > [data-key='plan']::before {
        background: repeating-linear-gradient(90deg, var(--hud-amber) 0 3px, transparent 3px 5px);
    }

    & > [data-key='landmark']::before {
        width: 6px;
        height: 6px;
        background: none;
        box-shadow: inset 0 0 0 1px #e8fbff;
    }

    & > [data-key='obstacle']::before {
        width: 6px;
        height: 6px;
        background: var(--hud-alert);
        clip-path: polygon(
            0 15%,
            15% 0,
            50% 35%,
            85% 0,
            100% 15%,
            65% 50%,
            100% 85%,
            85% 100%,
            50% 65%,
            15% 100%,
            0 85%,
            35% 50%
        );
    }
`;

const factCss = css`
    opacity: 0.6;
    text-transform: uppercase;

    & > b {
        color: #fff;
        font-weight: 600;
        opacity: 1;
    }
`;

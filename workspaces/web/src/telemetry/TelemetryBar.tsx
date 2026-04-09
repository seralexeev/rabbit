import { css, keyframes } from '@emotion/css';
import React from 'react';

import { useNats } from '../app/NatsProvider.tsx';
import { ui } from '../ui/index.ts';

const TELEMETRY_SUBJECT = 'rabbit.telemetry';
const HISTORY_SIZE = 20;

type ContainerStats = {
    name: string;
    cpu: number;
    mem: number;
    mem_limit: number;
};

type TelemetryData = {
    cpu: number[];
    gpu: number;
    ram: { used: number; total: number };
    swap: { used: number; total: number };
    temp: Record<string, number>;
    power: number;
    disk: { used: number; total: number };
    uptime: string;
    fan: number;
    fan_rpm: number;
    containers: ContainerStats[];
};

type History = {
    cpu: number[];
    gpu: number[];
    ram: number[];
    temps: Record<string, number[]>;
    power: number[];
    fan: number[];
    rpm: number[];
    containers: Record<string, { cpu: number[]; mem: number[] }>;
};

function pushHistory(arr: number[], val: number): number[] {
    const next = [...arr, val];
    if (next.length > HISTORY_SIZE) next.shift();
    return next;
}

function formatBytes(bytes: number): string {
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(1)}G`;
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(0)}M`;
}

function levelColor(pct: number): string {
    if (pct > 90) return '#ff3333';
    if (pct > 70) return '#ff8800';
    return '#00ff41';
}

function tempColor(deg: number): string {
    if (deg > 80) return '#ff3333';
    if (deg > 65) return '#ff8800';
    return '#00ff41';
}

const emptyHistory: History = {
    cpu: [],
    gpu: [],
    ram: [],
    temps: {},
    power: [],
    fan: [],
    rpm: [],
    containers: {},
};

export const TelemetryBar: React.FC = () => {
    const { nc } = useNats();
    const [data, setData] = React.useState<TelemetryData | null>(null);
    const [history, setHistory] = React.useState<History>(emptyHistory);

    React.useEffect(() => {
        const sub = nc.subscribe(TELEMETRY_SUBJECT, {
            callback: (_, msg) => {
                try {
                    const d = msg.json() as TelemetryData;
                    setData(d);

                    const cpuAvg = Math.round(d.cpu.reduce((a, b) => a + b, 0) / d.cpu.length);
                    const ramPct = d.ram.total > 0 ? (d.ram.used / d.ram.total) * 100 : 0;

                    setHistory((h) => {
                        const nextTemps: Record<string, number[]> = {};
                        for (const [name, val] of Object.entries(d.temp)) {
                            nextTemps[name] = pushHistory(h.temps[name] ?? [], val);
                        }

                        const nextContainers: Record<string, { cpu: number[]; mem: number[] }> = {};
                        for (const c of d.containers ?? []) {
                            const prev = h.containers[c.name] ?? { cpu: [], mem: [] };
                            const memPct = c.mem_limit > 0 ? (c.mem / c.mem_limit) * 100 : 0;
                            nextContainers[c.name] = {
                                cpu: pushHistory(prev.cpu, c.cpu),
                                mem: pushHistory(prev.mem, memPct),
                            };
                        }

                        return {
                            cpu: pushHistory(h.cpu, cpuAvg),
                            gpu: pushHistory(h.gpu, d.gpu),
                            ram: pushHistory(h.ram, ramPct),
                            temps: nextTemps,
                            power: pushHistory(h.power, d.power / 1000),
                            fan: pushHistory(h.fan, d.fan),
                            rpm: pushHistory(h.rpm, d.fan_rpm),
                            containers: nextContainers,
                        };
                    });
                } catch {}
            },
        });

        return () => {
            sub.unsubscribe();
        };
    }, [nc]);

    if (data == null) {
        return <ui.Placeholder label='WAITING FOR TELEMETRY' />;
    }

    const cpuAvg = Math.round(data.cpu.reduce((a, b) => a + b, 0) / data.cpu.length);
    const ramPct = data.ram.total > 0 ? (data.ram.used / data.ram.total) * 100 : 0;
    const maxTemp = Object.values(data.temp).length > 0 ? Math.max(...Object.values(data.temp)) : 0;

    return (
        <div
            className={css`
                display: flex;
                flex-direction: column;
                gap: 6px;
                padding: 8px;
                font-variant-numeric: tabular-nums;
            `}>
            {/* CPU — big card with core bars */}
            <Metric
                label='CPU'
                value={`${cpuAvg}%`}
                points={history.cpu}
                max={100}
                color={levelColor(cpuAvg)}>
                <div
                    className={css`
                        display: flex;
                        gap: 2px;
                        height: 20px;
                        align-items: flex-end;
                        margin-top: 4px;
                    `}>
                    {data.cpu.map((val, i) => (
                        <div
                            key={i}
                            className={css`
                                flex: 1;
                                height: 100%;
                                display: flex;
                                flex-direction: column;
                                justify-content: flex-end;
                            `}>
                            <div
                                className={css`
                                    width: 100%;
                                    background: ${levelColor(val)};
                                    height: ${Math.max(val, 2)}%;
                                    opacity: 0.7;
                                    transition: height 0.3s ease, background 0.3s ease;
                                `}
                            />
                        </div>
                    ))}
                </div>
                <div
                    className={css`
                        display: flex;
                        gap: 2px;
                        margin-top: 1px;
                    `}>
                    {data.cpu.map((val, i) => (
                        <span
                            key={i}
                            className={css`
                                flex: 1;
                                text-align: center;
                                font-size: 7px;
                                opacity: 0.4;
                                color: ${levelColor(val)};
                            `}>
                            {val}
                        </span>
                    ))}
                </div>
            </Metric>

            {/* GPU + RAM row */}
            <div className={rowCss}>
                <Metric label='GPU' value={`${data.gpu}%`} points={history.gpu} max={100} color={levelColor(data.gpu)} />
                <Metric
                    label='RAM'
                    value={`${formatBytes(data.ram.used)}/${formatBytes(data.ram.total)}`}
                    points={history.ram}
                    max={100}
                    color={levelColor(ramPct)}
                />
            </div>

            {/* THERMAL — each sensor as a compact card */}
            <div
                className={css`
                    display: flex;
                    align-items: baseline;
                    margin-bottom: -2px;
                `}>
                <span
                    className={css`
                        font-size: 9px;
                        opacity: 0.4;
                        letter-spacing: 0.08em;
                    `}>
                    THERMAL
                </span>
                <span
                    className={css`
                        margin-left: auto;
                        font-size: 10px;
                        color: ${tempColor(maxTemp)};
                        text-shadow: 0 0 6px ${tempColor(maxTemp)}44;
                    `}>
                    {Math.round(maxTemp)}°C
                </span>
            </div>
            <div
                className={css`
                    display: grid;
                    grid-template-columns: repeat(3, 1fr);
                    gap: 4px;
                `}>
                {Object.entries(data.temp).map(([name, val]) => (
                    <Metric
                        key={name}
                        label={name.toUpperCase()}
                        value={`${Math.round(val)}°`}
                        points={history.temps[name] ?? []}
                        max={100}
                        color={tempColor(val)}
                        compact
                    />
                ))}
            </div>

            {/* POWER + FAN + RPM */}
            <div className={rowCss}>
                <Metric label='PWR' value={`${(data.power / 1000).toFixed(1)}W`} points={history.power} color='#00ff41' />
                <Metric label='FAN' value={`${data.fan}%`} points={history.fan} max={100} color='#00ff41' />
                <Metric label='RPM' value={`${data.fan_rpm}`} points={history.rpm} color='#00ff41' />
            </div>

            {/* CONTAINERS */}
            {data.containers?.length > 0 && (
                <>
                    <div
                        className={css`
                            font-size: 9px;
                            opacity: 0.4;
                            letter-spacing: 0.08em;
                            margin-bottom: -2px;
                        `}>
                        NODES
                    </div>
                    <div
                        className={css`
                            display: flex;
                            flex-direction: column;
                            gap: 4px;
                        `}>
                        {data.containers.map((c) => {
                            const ch = history.containers[c.name];
                            const memPct = c.mem_limit > 0 ? (c.mem / c.mem_limit) * 100 : 0;
                            const shortName = c.name.replace(/^rabbit-/, '');
                            return (
                                <Metric
                                    key={c.name}
                                    label={shortName.toUpperCase()}
                                    value={`${c.cpu.toFixed(1)}% · ${formatBytes(c.mem)}`}
                                    points={ch?.cpu ?? []}
                                    color={levelColor(c.cpu)}
                                    compact
                                />
                            );
                        })}
                    </div>
                </>
            )}

            {/* SECONDARY */}
            <div
                className={css`
                    display: flex;
                    justify-content: space-between;
                    font-size: 8px;
                    opacity: 0.3;
                    letter-spacing: 0.05em;
                    padding-top: 2px;
                    border-top: 1px solid rgba(0, 255, 65, 0.08);
                `}>
                <span>SWP {formatBytes(data.swap.used)}/{formatBytes(data.swap.total)}</span>
                <span>DSK {data.disk.used}G/{data.disk.total}G</span>
                <span>UP {data.uptime}</span>
            </div>
        </div>
    );
};

const rowCss = css`
    display: flex;
    gap: 4px;
`;

// --- Sparkline path builder ---

function buildSparkPaths(points: number[], fixedMax?: number) {
    const w = 100;
    const h = 40;
    const pad = 2;
    const innerH = h - pad * 2;

    const min = 0;
    const autoMax = Math.max(...points);
    const max = fixedMax ?? (autoMax > 0 ? autoMax : 1);
    const range = max - min || 1;

    const step = w / (HISTORY_SIZE - 1);
    const offset = (HISTORY_SIZE - points.length) * step;

    const coords = points.map((v, i) => {
        const x = offset + i * step;
        const y = pad + innerH - ((v - min) / range) * innerH;
        return `${x},${y}`;
    });

    const linePath = `M${coords.join(' L')}`;
    const fillPath = `${linePath} L${offset + (points.length - 1) * step},${h} L${offset},${h} Z`;

    return { linePath, fillPath };
}

// --- Metric card: value + label + sparkline background ---

let metricIdCounter = 0;

const Metric: React.FC<{
    label: string;
    value: string;
    points?: number[];
    max?: number;
    color?: string;
    compact?: boolean;
    children?: React.ReactNode;
}> = ({ label, value, points, max: fixedMax, color = '#00ff41', compact, children }) => {
    const idRef = React.useRef(`m${metricIdCounter++}`);
    const hasSparkline = points != null && points.length >= 2;
    const paths = hasSparkline ? buildSparkPaths(points, fixedMax) : null;

    return (
        <div
            className={css`
                flex: 1;
                position: relative;
                overflow: hidden;
                border: 1px solid rgba(0, 255, 65, 0.12);
                padding: ${compact ? '4px 6px' : '6px 8px'};
                min-width: 0;
            `}>
            {paths && (
                <svg
                    viewBox='0 0 100 40'
                    preserveAspectRatio='none'
                    className={css`
                        position: absolute;
                        inset: 0;
                        width: 100%;
                        height: 100%;
                        pointer-events: none;
                    `}>
                    <defs>
                        <linearGradient id={`mf-${idRef.current}`} x1='0' y1='0' x2='0' y2='1'>
                            <stop offset='0%' stopColor={color} stopOpacity='0.18' />
                            <stop offset='100%' stopColor={color} stopOpacity='0' />
                        </linearGradient>
                    </defs>
                    <path d={paths.fillPath} fill={`url(#mf-${idRef.current})`} />
                    <path
                        d={paths.linePath}
                        fill='none'
                        stroke={color}
                        strokeWidth='1.5'
                        opacity='0.35'
                        vectorEffect='non-scaling-stroke'
                    />
                </svg>
            )}
            <div
                className={css`
                    position: relative;
                    z-index: 1;
                `}>
                <div
                    className={css`
                        display: flex;
                        justify-content: space-between;
                        align-items: baseline;
                    `}>
                    <span
                        className={css`
                            font-size: ${compact ? '7px' : '9px'};
                            opacity: 0.4;
                            letter-spacing: 0.08em;
                        `}>
                        {label}
                    </span>
                    <span
                        className={css`
                            font-size: ${compact ? '12px' : '14px'};
                            color: ${color};
                            text-shadow: 0 0 8px ${color}44;
                        `}>
                        {value}
                    </span>
                </div>
                {children}
            </div>
        </div>
    );
};

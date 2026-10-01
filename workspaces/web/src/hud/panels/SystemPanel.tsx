import { css, cx } from '@emotion/css';
import React from 'react';

import { ChartView } from '../../chat/ChartView.tsx';
import { TableView } from '../../chat/TableView.tsx';
import type { ChartSpec } from '../../chat/outputs.ts';
import { type SystemTelemetry as TelemetryData, isLive } from '../../perception/Telemetry.ts';
import { ui } from '../../ui/index.ts';
import { useHud, useHudTick } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { detailGridCss } from '../detail.ts';
import { type Tone, fixed, scaled, sectionCss, toneCss } from '../fields.ts';

const HISTORY_SIZE = 600;
const SPARK_SIZE = 30;
const STALE_MS = 3500;

type History = {
    t: number[];
    temp: number[];
    cpu: number[];
    gpu: number[];
    ram: number[];
    power: number[];
};

const pushHistory = (values: number[], value: number) => [...values.slice(-(HISTORY_SIZE - 1)), value];

const finite = (values: readonly (number | null)[]) =>
    values.filter((value): value is number => value != null && Number.isFinite(value));

const average = (values: number[]) => (values.length === 0 ? 0 : values.reduce((a, b) => a + b, 0) / values.length);

const appendHistory = (history: History, data: TelemetryData): History => ({
    t: pushHistory(history.t, Date.now()),
    temp: pushHistory(history.temp, Math.max(0, ...Object.values(data.temp))),
    cpu: pushHistory(history.cpu, average(data.cpu)),
    gpu: pushHistory(history.gpu, data.gpu),
    ram: pushHistory(history.ram, data.ram.total > 0 ? (data.ram.used / data.ram.total) * 100 : 0),
    power: pushHistory(history.power, data.power / 1000),
});

const formatBytes = (bytes: number) => {
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(1)}G`;
    return `${(bytes / (1024 * 1024)).toFixed(0)}M`;
};

const levelTone = (pct: number): Tone => (pct > 90 ? 'alert' : pct > 70 ? 'warn' : 'normal');
const tempTone = (deg: number): Tone => (deg > 80 ? 'alert' : deg > 65 ? 'warn' : 'normal');

const EMPTY_HISTORY: History = { t: [], temp: [], cpu: [], gpu: [], ram: [], power: [] };

export const SystemPanel: React.FC = () => {
    const { store } = useHud();
    const [data, setData] = React.useState<TelemetryData | null>(null);
    const [history, setHistory] = React.useState<History>(EMPTY_HISTORY);
    const [live, setLive] = React.useState(false);
    const seen = React.useRef(0);

    useHudTick((now) => {
        const channel = store.system;
        const fresh = isLive(channel, now, STALE_MS);
        if (fresh !== live) setLive(fresh);
        if (channel.value == null || channel.version === seen.current) return;
        seen.current = channel.version;
        const next = channel.value;
        setData(next);
        setHistory((prev) => appendHistory(prev, next));
    });

    return (
        <HudPanel
            id='system'
            code='SY'
            title='JETSON // SYSTEM'
            live={live}
            detail={
                data == null ? <ui.Placeholder label='WAITING FOR TELEMETRY' /> : <SystemDetail data={data} history={history} />
            }>
            {data == null ? <ui.Placeholder label='WAITING FOR TELEMETRY' /> : <SystemBody data={data} history={history} />}
        </HudPanel>
    );
};

const SystemBody: React.FC<{ data: TelemetryData; history: History }> = ({ data, history }) => {
    const cpu = Math.round(average(data.cpu));
    const ramPct = data.ram.total > 0 ? (data.ram.used / data.ram.total) * 100 : 0;
    const temps = Object.entries(data.temp);
    const maxTemp = Math.max(0, ...finite(temps.map(([, value]) => value)));
    const maxFreq = Math.max(0, ...finite(data.cpu_freq_mhz));

    return (
        <>
            <Metric
                label={`CPU ${fixed(maxFreq / 1000, 2)}GHZ`}
                value={`${cpu}%`}
                points={history.cpu}
                max={100}
                tone={levelTone(cpu)}>
                <div className={coresCss}>
                    {data.cpu.map((value, i) => (
                        <div key={i} className={coreCss}>
                            <div
                                className={cx(coreBarCss, toneCss)}
                                data-tone={levelTone(value)}
                                style={{ height: `${Math.max(value, 3)}%` }}
                            />
                            <span>{fixed(value, 0)}</span>
                        </div>
                    ))}
                </div>
            </Metric>

            <div className={gridCss}>
                <Metric
                    label={`GPU ${fixed(scaled(data.gpu_freq_mhz, 1 / 1000), 2)}GHZ`}
                    value={fixed(data.gpu, 0, '%')}
                    points={history.gpu}
                    max={100}
                    tone={levelTone(data.gpu)}
                />
                <Metric
                    label='RAM'
                    value={`${formatBytes(data.ram.used)}/${formatBytes(data.ram.total)}`}
                    points={history.ram}
                    max={100}
                    tone={levelTone(ramPct)}
                />
                <Metric label='PWR' value={fixed(scaled(data.power, 1 / 1000), 1, 'W')} points={history.power} tone='normal' />
                <Metric label='FAN' value={`${data.fan}% ${data.fan_rpm}`} tone='normal' />
            </div>

            <div className={sectionCss}>
                THERMAL <span className={toneCss} data-tone={tempTone(maxTemp)}>{`MAX ${fixed(maxTemp, 0)}°C`}</span>
            </div>
            <div className={tempsCss}>
                {temps.map(([name, value]) => (
                    <div key={name} className={tempCss}>
                        <span>{name}</span>
                        <span className={toneCss} data-tone={tempTone(value)}>
                            {fixed(value, 0, '°')}
                        </span>
                    </div>
                ))}
            </div>

            {data.containers.length > 0 && (
                <>
                    <div className={sectionCss}>NODES</div>
                    {data.containers.map((container) => (
                        <div key={container.name} className={containerCss}>
                            <span>{container.name.replace(/^rabbit-/, '')}</span>
                            <span className={toneCss} data-tone={levelTone(container.cpu)}>
                                {fixed(container.cpu, 1, '%')}
                            </span>
                            <span>{formatBytes(container.mem)}</span>
                        </div>
                    ))}
                </>
            )}

            <div className={footerCss}>
                <span>{`SWP ${formatBytes(data.swap.used)}/${formatBytes(data.swap.total)}`}</span>
                <span>{`DSK ${data.disk.used}/${data.disk.total}G`}</span>
                <span>{`UP ${data.uptime}`}</span>
            </div>
        </>
    );
};

const historyChart = (history: History, title: string, series: ChartSpec['series']): ChartSpec => ({
    type: 'line',
    title,
    x: { field: 't', label: 'TIME', time: true },
    series,
    rows: history.t.map((t, i) => ({
        t,
        cpu: history.cpu[i],
        gpu: history.gpu[i],
        ram: history.ram[i],
        power: history.power[i],
        temp: history.temp[i],
    })),
});

const SystemDetail: React.FC<{ data: TelemetryData; history: History }> = ({ data, history }) => (
    <>
        <div className={detailGridCss}>
            <ChartView
                chart={historyChart(history, 'LOAD', [
                    { field: 'cpu', label: 'CPU', unit: '%' },
                    { field: 'gpu', label: 'GPU', unit: '%' },
                    { field: 'ram', label: 'RAM', unit: '%' },
                ])}
                height={200}
            />
            <ChartView
                chart={historyChart(history, 'POWER / MAX TEMP', [
                    { field: 'power', label: 'POWER', unit: 'W' },
                    { field: 'temp', label: 'MAX TEMP', unit: '°C', axis: 'right' },
                ])}
                height={200}
            />
            <TableView
                table={{
                    title: 'THERMAL',
                    columns: [
                        { field: 'sensor', label: 'SENSOR' },
                        { field: 'temp', label: 'TEMP', unit: '°C' },
                    ],
                    rows: Object.entries(data.temp).map(([sensor, temp]) => ({ sensor, temp })),
                }}
            />
            <TableView
                table={{
                    title: 'CPU CORES',
                    columns: [
                        { field: 'core', label: 'CORE' },
                        { field: 'load', label: 'LOAD', unit: '%' },
                        { field: 'freq', label: 'FREQ', unit: 'MHz' },
                    ],
                    rows: data.cpu.map((load, core) => ({ core, load, freq: data.cpu_freq_mhz[core] ?? null })),
                }}
            />
        </div>
        <TableView
            table={{
                title: 'NODES',
                columns: [
                    { field: 'name', label: 'CONTAINER' },
                    { field: 'cpu', label: 'CPU', unit: '%' },
                    { field: 'mem', label: 'MEM' },
                    { field: 'limit', label: 'LIMIT' },
                ],
                rows: data.containers.map((container) => ({
                    name: container.name,
                    cpu: container.cpu,
                    mem: formatBytes(container.mem),
                    limit: formatBytes(container.mem_limit),
                })),
            }}
        />
    </>
);

const sparkPath = (points: number[], fixedMax?: number) => {
    const width = 100;
    const height = 40;
    const max = fixedMax ?? Math.max(...points, 1);
    const step = width / (SPARK_SIZE - 1);
    const offset = (SPARK_SIZE - points.length) * step;
    const line = points
        .map((value, i) => `${i === 0 ? 'M' : 'L'}${offset + i * step},${height - 2 - (value / max) * (height - 4)}`)
        .join('');
    return { line, fill: `${line}L${offset + (points.length - 1) * step},${height}L${offset},${height}Z` };
};

const Metric: React.FC<{
    label: string;
    value: string;
    tone: Tone;
    points?: number[];
    max?: number;
    children?: React.ReactNode;
}> = ({ label, value, tone, points, max, children }) => {
    const recent = points?.slice(-SPARK_SIZE);
    const paths = recent != null && recent.length >= 2 ? sparkPath(recent, max) : null;

    return (
        <div className={metricCss}>
            {paths != null && (
                <svg viewBox='0 0 100 40' preserveAspectRatio='none' className={sparkCss}>
                    <path d={paths.fill} className='fill' />
                    <path d={paths.line} className='line' />
                </svg>
            )}
            <div className={metricHeadCss}>
                <span className={metricLabelCss}>{label}</span>
                <span className={cx(metricValueCss, toneCss)} data-tone={tone}>
                    {value}
                </span>
            </div>
            {children}
        </div>
    );
};

const metricCss = css`
    position: relative;
    padding: 3px 6px;
    margin-bottom: 4px;
    border: 1px solid var(--hud-faint);
    overflow: hidden;
`;

const sparkCss = css`
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;

    & .fill {
        fill: rgba(98, 232, 255, 0.08);
    }

    & .line {
        fill: none;
        stroke: var(--hud);
        stroke-opacity: 0.4;
        stroke-width: 1.2;
        vector-effect: non-scaling-stroke;
    }
`;

const metricHeadCss = css`
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 6px;
`;

const metricLabelCss = css`
    font-size: 9px;
    opacity: 0.55;
    white-space: nowrap;
`;

const metricValueCss = css`
    font-size: 12px;
    text-transform: none;
    white-space: nowrap;
`;

const gridCss = css`
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 4px;
`;

const coresCss = css`
    position: relative;
    display: flex;
    gap: 3px;
    height: 26px;
    margin-top: 3px;
`;

const coreCss = css`
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    align-items: center;
    font-size: 7px;
    opacity: 0.8;
`;

const coreBarCss = css`
    width: 100%;
    max-height: 18px;
    background: currentColor;
    opacity: 0.7;
    transition: height 0.3s ease;
`;

const tempsCss = css`
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    column-gap: 8px;
`;

const tempCss = css`
    display: flex;
    justify-content: space-between;
    font-size: 9px;

    & > span:first-child {
        opacity: 0.55;
    }
`;

const containerCss = css`
    display: grid;
    grid-template-columns: 1fr 52px 44px;
    gap: 6px;
    font-size: 9px;
    line-height: 13px;

    & > span:not(:first-child) {
        text-align: right;
    }
`;

const footerCss = css`
    display: flex;
    justify-content: space-between;
    margin-top: 5px;
    padding-top: 3px;
    border-top: 1px solid var(--hud-faint);
    font-size: 8px;
    opacity: 0.45;
`;

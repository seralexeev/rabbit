import { css } from '@emotion/css';
import React from 'react';

import { ChartView } from '../ChartView.tsx';
import { TableView } from '../TableView.tsx';
import { Sparkline } from '../charts/Sparkline.tsx';
import { GraphView } from '../graph/GraphView.tsx';
import { formatValue } from '../outputs.ts';
import type { Result, SignalSummary, TrendSeries } from '../results.ts';
import { PathView } from './PathView.tsx';
import { StatusCard } from './StatusCard.tsx';
import { Card, Disclosure, cardCss } from './kit.tsx';

const TABLE_OPEN_ROWS = 12;

const TrendRows: React.FC<{ series: TrendSeries[] }> = ({ series }) => (
    <div className={trendCss}>
        {series.map(({ label, unit, values }) => {
            const finite = values.filter(Number.isFinite);
            const suffix = unit == null ? '' : ` ${unit}`;
            return (
                <React.Fragment key={label}>
                    <span className={trendLabelCss}>{label}</span>
                    <Sparkline values={values} width={120} height={16} title={label} />
                    <span className={trendValueCss}>
                        <b>{formatValue(finite.at(-1))}</b>
                        {suffix}
                    </span>
                    <span className={trendRangeCss}>
                        {formatValue(Math.min(...finite))}–{formatValue(Math.max(...finite))}
                    </span>
                </React.Fragment>
            );
        })}
    </div>
);

const SignalChips: React.FC<{ signals: SignalSummary[] }> = ({ signals }) => (
    <div className={chipsCss}>
        {signals.map((signal) => (
            <span key={signal.signal} data-severity={signal.events === 0 ? 'none' : (signal.severity ?? 'info')}>
                {signal.signal} · {signal.events === 0 ? 'clean' : `${signal.events} event${signal.events === 1 ? '' : 's'}`}
            </span>
        ))}
    </div>
);

type ResultViewProps = { result: Result; quiet: boolean };

export const ResultView: React.FC<ResultViewProps> = ({ result, quiet }) => {
    switch (result.kind) {
        case 'series':
            return (
                <div className={cardCss} data-output-id={result.id}>
                    <ChartView
                        chart={result.chart}
                        height={result.chart.layout === 'stacked' ? 260 : undefined}
                        note={result.note}
                    />
                </div>
            );
        case 'anomaly':
            return (
                <div className={cardCss} data-output-id={result.id}>
                    <SignalChips signals={result.signals} />
                    <ChartView chart={result.chart} height={result.chart.layout === 'stacked' ? 260 : undefined} />
                </div>
            );
        case 'graph':
            return (
                <div data-output-id={result.id}>
                    <GraphView graph={result.graph} />
                </div>
            );
        case 'path':
            return (
                <Card title={result.title}>
                    <PathView path={result.path} />
                </Card>
            );
        case 'status':
            return <StatusCard status={result.status} />;
        case 'fields':
            return (
                <div className={fieldsCss}>
                    <span>{result.title}</span>
                    {result.values.map(([key, value]) => (
                        <span key={key}>
                            {key} <b>{value}</b>
                        </span>
                    ))}
                </div>
            );
        case 'table': {
            const { title, ...table } = result.table;
            const { trend, path } = result;
            const total = table.row_count ?? table.rows.length;
            const label = `${title ?? 'Rows'} · ${total.toLocaleString('en-US')} row${total === 1 ? '' : 's'}`;
            if (quiet && path == null)
                return (
                    <div className={quietCss}>
                        <Disclosure label={label}>
                            <TableView table={table} />
                        </Disclosure>
                    </div>
                );
            return (
                <Card title={title ?? 'Rows'} meta={`${total.toLocaleString('en-US')} ROWS`}>
                    {path != null ? <PathView path={path} /> : trend.length > 0 && <TrendRows series={trend} />}
                    {path == null && trend.length === 0 && total <= TABLE_OPEN_ROWS ? (
                        <TableView table={table} />
                    ) : (
                        <Disclosure label='Table'>
                            <TableView table={table} />
                        </Disclosure>
                    )}
                </Card>
            );
        }
    }
};

const trendCss = css`
    display: grid;
    grid-template-columns: minmax(0, auto) 120px auto minmax(0, 1fr);
    align-items: center;
    gap: 2px 8px;
    margin-bottom: 4px;
    font-size: 9.5px;
`;

const trendLabelCss = css`
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-transform: uppercase;
    opacity: 0.65;
`;

const trendValueCss = css`
    white-space: nowrap;
    opacity: 0.7;

    & > b {
        color: #fff;
        font-weight: 600;
    }
`;

const trendRangeCss = css`
    font-size: 8.5px;
    white-space: nowrap;
    opacity: 0.45;
`;

const chipsCss = css`
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 4px;
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.06em;

    & > span {
        padding: 0 5px;
        border-left: 2px solid var(--tone);
        background: rgba(98, 232, 255, 0.04);
        color: var(--tone);

        --tone: var(--hud);
    }

    & > span[data-severity='none'] {
        --tone: var(--hud-good);
    }

    & > span[data-severity='warn'] {
        --tone: var(--hud-amber);
    }

    & > span[data-severity='alert'] {
        --tone: var(--hud-alert);
    }
`;

const fieldsCss = css`
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px 10px;
    margin: 6px 0 0;
    padding: 3px 8px;
    background: #03090d;
    box-shadow: inset 2px 0 0 var(--hud-dim);
    font-size: 9.5px;
    text-transform: uppercase;

    & > span:first-child {
        font-weight: 600;
        letter-spacing: 0.1em;
    }

    & > span:not(:first-child) {
        opacity: 0.6;
    }

    & b {
        color: #fff;
        font-weight: 600;
    }
`;

const quietCss = css`
    margin-top: 4px;
`;

import { css } from '@emotion/css';
import React from 'react';

import { formatValue } from '../outputs.ts';

export type SparkTone = 'info' | 'ok' | 'warn' | 'alert';

type SparklineProps = {
    values: number[];
    width?: number;
    height?: number;
    tone?: SparkTone;
    title?: string;
};

export const Sparkline: React.FC<SparklineProps> = ({ values, width = 64, height = 14, tone = 'info', title }) => {
    const finite = values.filter((value) => Number.isFinite(value));
    if (finite.length < 2) return null;
    const min = Math.min(...finite);
    const max = Math.max(...finite);
    const span = max - min || 1;
    const pad = 1.5;
    const x = (i: number) => pad + (i / (values.length - 1)) * (width - 2 * pad);
    const y = (value: number) => pad + (1 - (value - min) / span) * (height - 2 * pad);
    const path = values
        .map((value, i) => (Number.isFinite(value) ? `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(value).toFixed(1)}` : ''))
        .join('');
    const peak = values.indexOf(max);
    const trough = values.indexOf(min);
    const last = values.length - 1;
    return (
        <svg
            className={sparkCss}
            data-tone={tone}
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            role='img'
            aria-label={title ?? `from ${formatValue(values[0])} to ${formatValue(values[last])}`}>
            <title>{`${title == null ? '' : `${title}: `}min ${formatValue(min)}, max ${formatValue(max)}, last ${formatValue(values[last])}`}</title>
            <path d={path} />
            <circle cx={x(peak)} cy={y(max)} r={1.6} data-point='max' />
            <circle cx={x(trough)} cy={y(min)} r={1.6} data-point='min' />
        </svg>
    );
};

const sparkCss = css`
    display: inline-block;
    vertical-align: middle;
    overflow: visible;

    --tone: var(--hud);

    &[data-tone='ok'] {
        --tone: var(--hud-good);
    }

    &[data-tone='warn'] {
        --tone: var(--hud-amber);
    }

    &[data-tone='alert'] {
        --tone: var(--hud-alert);
    }

    & path {
        fill: none;
        stroke: var(--tone);
        stroke-width: 1.1;
        stroke-linejoin: round;
        filter: drop-shadow(0 0 2px var(--hud-glow));
    }

    & circle[data-point='max'] {
        fill: var(--tone);
    }

    & circle[data-point='min'] {
        fill: none;
        stroke: var(--tone);
        stroke-width: 0.8;
    }
`;

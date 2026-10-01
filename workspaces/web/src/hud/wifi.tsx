import { css } from '@emotion/css';
import React from 'react';

import type { Tone } from './fields.ts';

export const LINK_STALE_MS = 2000;

export const signalBars = (dbm: number | null | undefined) =>
    dbm == null ? 0 : dbm >= -55 ? 4 : dbm >= -67 ? 3 : dbm >= -75 ? 2 : dbm >= -85 ? 1 : 0;

export const signalTone = (bars: number): Tone => (bars >= 3 ? 'good' : bars === 2 ? 'warn' : 'alert');

export const rttTone = (rtt: number | null | undefined): Tone =>
    rtt == null ? 'alert' : rtt < 20 ? 'good' : rtt < 100 ? 'warn' : 'alert';

export const band = (frequency: number | null | undefined) =>
    frequency == null ? '—' : frequency >= 5900 ? '6 GHz' : frequency >= 4900 ? '5 GHz' : '2.4 GHz';

export const writeBars = (bars: SVGSVGElement | null, count: number, tone: Tone) => {
    if (bars == null) return;
    const key = `${count}:${tone}`;
    if (bars.dataset['key'] === key) return;
    bars.dataset['key'] = key;
    bars.dataset['tone'] = tone;
    bars.querySelectorAll('rect').forEach((rect, i) => rect.setAttribute('data-on', String(i < count)));
};

export const SignalBars: React.FC<{ size?: number; ref?: React.Ref<SVGSVGElement> }> = ({ size = 14, ref }) => (
    <svg ref={ref} className={barsCss} width={size} height={size} viewBox='0 0 16 16'>
        {[0, 1, 2, 3].map((i) => (
            <rect key={i} x={i * 4} y={12 - i * 4} width={3} height={4 + i * 4} data-on='false' />
        ))}
    </svg>
);

const barsCss = css`
    display: block;
    color: var(--hud);

    &[data-tone='good'] {
        color: var(--hud-good);
    }

    &[data-tone='warn'] {
        color: var(--hud-amber);
    }

    &[data-tone='alert'] {
        color: var(--hud-alert);
    }

    & rect {
        fill: currentColor;
        opacity: 0.18;
    }

    & rect[data-on='true'] {
        opacity: 1;
    }
`;

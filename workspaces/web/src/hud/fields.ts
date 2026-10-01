import { css, cx, keyframes } from '@emotion/css';
import React from 'react';

export type Tone = 'good' | 'normal' | 'warn' | 'alert';
type BarKind = 'fill' | 'center';
export type RowSpec = { label: string; bar?: BarKind };
export type FieldRefs = { values: (HTMLElement | null)[]; bars: (HTMLElement | null)[] };

const BAR_STEPS = 40;

export const useFields = () => React.useRef<FieldRefs>({ values: [], bars: [] });

const isNumber = (value: number | null | undefined): value is number => value != null && Number.isFinite(value);

export const above = (value: number | null | undefined, warn: number, alert: number): Tone =>
    !isNumber(value) ? 'normal' : value >= alert ? 'alert' : value >= warn ? 'warn' : 'normal';

export const below = (value: number | null | undefined, warn: number, alert: number): Tone =>
    !isNumber(value) ? 'normal' : value <= alert ? 'alert' : value <= warn ? 'warn' : 'normal';

export const scaled = (value: number | null | undefined, factor: number) => (isNumber(value) ? value * factor : null);

export const fixed = (value: number | null | undefined, digits: number, unit = '') =>
    isNumber(value) ? `${value.toFixed(digits)}${unit}` : '—';

export const signed = (value: number | null | undefined, digits: number, unit = '') =>
    isNumber(value) ? `${value < 0 ? '-' : '+'}${Math.abs(value).toFixed(digits)}${unit}` : '—';
export const writeText = (el: HTMLElement | null | undefined, text: string, tone: Tone = 'normal') => {
    if (el == null) return;
    if ((el.dataset['tone'] ?? 'normal') !== tone) el.dataset['tone'] = tone;
    const node = el.firstChild;
    if (node instanceof Text ? node.data === text : el.textContent === text) return;
    if (node instanceof Text) node.data = text;
    else el.textContent = text;
    el.dataset['flick'] = el.dataset['flick'] === 'a' ? 'b' : 'a';
};

const barLevels = new WeakMap<HTMLElement, number>();

export const writeBar = (el: HTMLElement | null | undefined, value: number) => {
    if (el == null) return;
    const steps = Math.round(Math.max(-1, Math.min(1, Number.isFinite(value) ? value : 0)) * BAR_STEPS);
    if (barLevels.get(el) === steps) return;
    barLevels.set(el, steps);
    if (el.dataset['kind'] === 'center') {
        const pct = (Math.abs(steps) / BAR_STEPS) * 50;
        el.style.clipPath = steps >= 0 ? `inset(0 ${50 - pct}% 0 50%)` : `inset(0 50% 0 ${50 - pct}%)`;
    } else {
        el.style.clipPath = `inset(0 ${100 - (Math.max(steps, 0) / BAR_STEPS) * 100}% 0 0)`;
    }
};

const flickerA = keyframes`
    0% { opacity: 0.35; }
    35% { opacity: 1; }
    55% { opacity: 0.7; }
    100% { opacity: 1; }
`;
const flickerB = keyframes`
    0% { opacity: 0.35; }
    35% { opacity: 1; }
    55% { opacity: 0.7; }
    100% { opacity: 1; }
`;

export const toneCss = css`
    &[data-tone='good'] {
        color: var(--hud-good);
        text-shadow: 0 0 6px rgba(61, 255, 122, 0.45);
    }

    &[data-tone='warn'] {
        color: var(--hud-amber);
        text-shadow: 0 0 6px rgba(255, 181, 71, 0.5);
    }

    &[data-tone='alert'] {
        color: var(--hud-alert);
        text-shadow: 0 0 6px rgba(255, 90, 74, 0.6);
    }

    &[data-flick='a'] {
        animation: ${flickerA} 220ms linear;
    }

    &[data-flick='b'] {
        animation: ${flickerB} 220ms linear;
    }
`;

export const rowCss = css`
    display: grid;
    grid-template-columns: 34px 1fr auto;
    align-items: center;
    gap: 6px;
    min-height: 14px;
`;

export const labelCss = css`
    opacity: 0.55;
    white-space: nowrap;
`;

export const valueCss = cx(
    toneCss,
    css`
        grid-column: 3;
        min-width: 64px;
        text-align: right;
        white-space: pre;
        text-transform: none;
    `,
);

export const sectionCss = css`
    margin: 6px 0 3px;
    font-size: 9px;
    letter-spacing: 0.1em;
    opacity: 0.45;
`;

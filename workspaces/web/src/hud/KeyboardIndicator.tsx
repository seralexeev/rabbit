import { css, cx } from '@emotion/css';
import React from 'react';

import { ARROW_ORDER, type Arrow, type KeyboardDriver } from '../controller/keyboard.ts';
import { useHudTick } from './HudContext.ts';
import { signed, toneCss, writeText } from './fields.ts';

const GLYPHS: Record<Arrow, string> = { up: '▲', down: '▼', left: '◀', right: '▶' };

export const KeyboardIndicator: React.FC<{ driver: KeyboardDriver }> = ({ driver }) => {
    const stateRef = React.useRef<HTMLSpanElement | null>(null);
    const valueRef = React.useRef<HTMLSpanElement | null>(null);
    const arrowRefs = React.useRef<Partial<Record<Arrow, HTMLSpanElement | null>>>({});

    useHudTick(() => {
        const { held, fast, speed, steer } = driver.read();
        const driving = held.size > 0;
        writeText(stateRef.current, driving && fast ? 'KEYS FAST' : 'KEYS', driving ? 'warn' : 'normal');
        writeText(
            valueRef.current,
            driving ? `SPD ${signed(speed * 100, 0, '%')} STR ${signed(steer * 100, 0, '%')}` : 'IDLE',
            driving ? 'warn' : 'normal',
        );
        for (const arrow of ARROW_ORDER) {
            const el = arrowRefs.current[arrow];
            const on = String(held.has(arrow));
            if (el != null && el.dataset['on'] !== on) el.dataset['on'] = on;
        }
    });

    return (
        <div
            className={rootCss}
            title='Arrow keys drive the robot, Shift for fast. Releasing the keys or leaving the window stops it.'>
            <span ref={stateRef} className={cx(toneCss, labelCss)}>
                KEYS
            </span>
            <span className={arrowsCss}>
                {ARROW_ORDER.map((arrow) => (
                    <span
                        key={arrow}
                        ref={(el) => {
                            arrowRefs.current[arrow] = el;
                        }}
                        data-on='false'>
                        {GLYPHS[arrow]}
                    </span>
                ))}
            </span>
            <span ref={valueRef} className={cx(toneCss, labelCss)}>
                IDLE
            </span>
        </div>
    );
};

const rootCss = css`
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 8px;
    border: 1px solid var(--hud-faint);
    font-size: 10px;
    letter-spacing: 0.08em;
    font-variant-numeric: tabular-nums;
`;

const labelCss = css`
    white-space: nowrap;

    &:not([data-tone='warn']) {
        opacity: 0.55;
    }
`;

const arrowsCss = css`
    display: flex;
    gap: 2px;
    font-size: 8px;

    & > [data-on='false'] {
        opacity: 0.25;
    }

    & > [data-on='true'] {
        color: var(--hud-amber);
        text-shadow: 0 0 6px rgba(255, 181, 71, 0.5);
    }
`;

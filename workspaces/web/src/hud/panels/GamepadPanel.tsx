import { css } from '@emotion/css';
import React from 'react';

import type { DualSenseState } from '../../controller/dualsense.ts';
import { isLive } from '../../perception/Telemetry.ts';
import { HistoryChart, type HistorySignals } from '../HistoryChart.tsx';
import { useHud, useHudFrame, useHudTick } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { Rows } from '../Rows.tsx';
import { detailGridCss } from '../detail.ts';
import { fixed, useFields, writeBar, writeText } from '../fields.ts';

const GAMEPAD_CHARTS = {
    sticks: [
        { key: 'left_x', label: 'LEFT X' },
        { key: 'left_y', label: 'LEFT Y' },
        { key: 'right_x', label: 'RIGHT X' },
        { key: 'right_y', label: 'RIGHT Y' },
    ],
    triggers: [
        { key: 'l2', label: 'L2' },
        { key: 'r2', label: 'R2' },
    ],
} as const satisfies Record<string, HistorySignals>;

const STICK_RADIUS = 22;
const ROWS = [{ label: 'L2', bar: 'fill' }, { label: 'R2', bar: 'fill' }, { label: 'BTN' }] as const;
const BUTTONS = [
    'cross',
    'circle',
    'square',
    'triangle',
    'l1',
    'r1',
    'l3',
    'r3',
    'up',
    'down',
    'left',
    'right',
    'share',
    'options',
] as const;

export const GamepadPanel: React.FC = () => {
    const { store } = useHud();
    const fields = useFields();
    const leftRef = React.useRef<SVGCircleElement | null>(null);
    const rightRef = React.useRef<SVGCircleElement | null>(null);
    const drawn = React.useRef({ left: '', right: '' });

    const place = (dot: SVGCircleElement | null, stick: { x: number; y: number }, key: 'left' | 'right') => {
        const transform = `translate(${Math.round(stick.x * STICK_RADIUS)} ${Math.round(stick.y * STICK_RADIUS)})`;
        if (dot == null || drawn.current[key] === transform) return;
        drawn.current[key] = transform;
        dot.setAttribute('transform', transform);
    };

    useHudFrame((now) => {
        const joy = isLive(store.joy, now) ? store.joy.value : null;
        place(leftRef.current, joy?.sticks.left ?? { x: 0, y: 0 }, 'left');
        place(rightRef.current, joy?.sticks.right ?? { x: 0, y: 0 }, 'right');
    });

    useHudTick((now) => {
        const joy: DualSenseState | null = isLive(store.joy, now) ? store.joy.value : null;
        const { values, bars } = fields.current;
        const l2 = joy?.buttons.l2.value ?? 0;
        const r2 = joy?.buttons.r2.value ?? 0;
        writeText(values[0], fixed(l2 * 100, 0, '%'));
        writeBar(bars[0], l2);
        writeText(values[1], fixed(r2 * 100, 0, '%'));
        writeBar(bars[1], r2);
        const pressed = joy == null ? [] : BUTTONS.filter((name) => joy.buttons[name].pressed);
        writeText(values[2], pressed.length === 0 ? '—' : pressed.join(' ').toUpperCase());
    });

    return (
        <HudPanel
            id='gamepad'
            code='GP'
            title='GAMEPAD // JOY'
            source='joy'
            detail={
                <div className={detailGridCss}>
                    <HistoryChart title='STICKS' signals={GAMEPAD_CHARTS.sticks} />
                    <HistoryChart title='TRIGGERS' signals={GAMEPAD_CHARTS.triggers} />
                </div>
            }>
            <div className={sticksCss}>
                {(['left', 'right'] as const).map((key) => (
                    <svg key={key} width={56} height={56} viewBox='-28 -28 56 56'>
                        <circle className='frame' r={STICK_RADIUS + 4} />
                        <path className='faint' d={`M${-STICK_RADIUS} 0H${STICK_RADIUS}M0 ${-STICK_RADIUS}V${STICK_RADIUS}`} />
                        <circle ref={key === 'left' ? leftRef : rightRef} className='dot' r={3} />
                    </svg>
                ))}
            </div>
            <Rows rows={ROWS} fields={fields} />
        </HudPanel>
    );
};

const sticksCss = css`
    display: flex;
    justify-content: space-around;
    padding: 2px 0 6px;

    & svg {
        display: block;
        overflow: visible;
    }

    & .frame {
        fill: none;
        stroke: var(--hud-dim);
        stroke-width: 1;
    }

    & .faint {
        fill: none;
        stroke: var(--hud-faint);
        stroke-dasharray: 2 2;
    }

    & .dot {
        fill: var(--hud-amber);
    }
`;

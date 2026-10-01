import { css, cx } from '@emotion/css';
import React from 'react';

import { type NavState, isLive } from '../../perception/Telemetry.ts';
import type { MissionStep } from '../../perception/mission.ts';
import { HistoryChart, type HistorySignals } from '../HistoryChart.tsx';
import { useHud, useHudTick } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { MissionSteps } from '../MissionSteps.tsx';
import { Rows } from '../Rows.tsx';
import { detailGridCss } from '../detail.ts';
import { type Tone, fixed, signed, useFields, writeBar, writeText } from '../fields.ts';

const ROWS = [
    { label: 'MODE' },
    { label: 'GOAL' },
    { label: 'DIST' },
    { label: 'HERR', bar: 'center' },
    { label: 'SPD' },
    { label: 'STR', bar: 'center' },
] as const;

const ROUTE_CHART: HistorySignals = [
    { key: 'goal_m', label: 'DISTANCE TO GOAL', unit: 'm' },
    { key: 'heading_error', label: 'HEADING ERROR', unit: '°', axis: 'right' },
];

const MODE_TONES: Record<string, Tone> = { blocked: 'alert', fault: 'alert', maneuvering: 'warn' };
const NAV_TIMEOUT_MS = 2000;
const MISSION_REFRESH_MS = 250;

type MissionView = { done: number; total: number; steps: MissionStep[]; progress: string; key: string };

const describeMission = (nav: NavState | null): MissionView | null => {
    if (nav?.step == null) return null;
    const steps = [nav.step, ...(nav.queue ?? [])];
    const progress =
        nav.step.type === 'turn'
            ? `${fixed(Math.abs(nav.turn_remaining_deg ?? 0), 0)}° left`
            : fixed(nav.distance_to_goal, 2, ' m');
    const done = Math.max((nav.step_index ?? 1) - 1, 0);
    const total = nav.steps_total ?? done + steps.length;
    return { done, total, steps, progress, key: `${done}/${total}:${JSON.stringify(steps)}:${progress}` };
};

type RoutePanelProps = { armed: boolean; onArm: () => void; onCancel: () => void };

export const RoutePanel: React.FC<RoutePanelProps> = ({ armed, onArm, onCancel }) => {
    const { store, connected } = useHud();
    const fields = useFields();
    const [mission, setMission] = React.useState<MissionView | null>(null);
    const missionRef = React.useRef({ key: '', updatedAt: 0 });

    useHudTick((now) => {
        const nav = isLive(store.nav, now, NAV_TIMEOUT_MS) ? store.nav.value : null;
        if (now - missionRef.current.updatedAt >= MISSION_REFRESH_MS) {
            const next = describeMission(nav);
            const key = next?.key ?? '';
            if (key !== missionRef.current.key) {
                missionRef.current = { key, updatedAt: now };
                setMission(next);
            }
        }
        const { values, bars } = fields.current;
        if (nav == null) {
            writeText(values[0], 'OFFLINE', 'warn');
            for (let i = 1; i < ROWS.length; i++) writeText(values[i], '—');
            writeBar(bars[3], 0);
            writeBar(bars[5], 0);
            return;
        }
        const fault = nav.mode === 'fault' ? (nav.fault ?? 'FAULT') : null;
        writeText(values[0], fault == null ? nav.mode.toUpperCase() : `FAULT · ${fault}`, MODE_TONES[nav.mode] ?? 'normal');
        writeText(values[1], nav.goal == null ? '—' : `${signed(nav.goal.x, 2)} ${signed(nav.goal.z, 2)}`);
        writeText(values[2], fixed(nav.distance_to_goal, 2, ' m'));
        writeText(values[3], signed(nav.heading_error_deg, 0, '°'));
        writeBar(bars[3], (nav.heading_error_deg ?? 0) / 90);
        writeText(values[4], fixed(nav.speed, 2));
        writeText(values[5], signed(nav.steer, 2));
        writeBar(bars[5], nav.steer ?? 0);
    });

    return (
        <HudPanel
            id='route'
            code='RT'
            title='ROUTE // NAV'
            source='nav'
            detail={
                <div className={detailGridCss}>
                    <div>
                        <div className={missionHeadCss}>
                            {mission == null ? 'NO ACTIVE MISSION' : `MISSION · STEP ${mission.done + 1}/${mission.total}`}
                        </div>
                        {mission != null && (
                            <MissionSteps
                                steps={mission.steps}
                                current={1}
                                progress={mission.progress}
                                start={mission.done + 1}
                            />
                        )}
                    </div>
                    <HistoryChart title='GOAL TRACKING' signals={ROUTE_CHART} />
                </div>
            }>
            <Rows rows={ROWS} fields={fields} />
            {mission != null && (
                <div className={missionCss}>
                    <div
                        className={
                            missionHeadCss
                        }>{`MISSION · STEP ${mission.done + 1}/${mission.total}${mission.done > 0 ? ` · ${mission.done} DONE` : ''}`}</div>
                    <MissionSteps steps={mission.steps} current={1} progress={mission.progress} start={mission.done + 1} />
                </div>
            )}
            <div className={actionsCss}>
                <button
                    className={cx(buttonCss, armed && armedCss)}
                    onClick={onArm}
                    disabled={!connected}
                    title={connected ? 'Arm click-to-go (G)' : 'NATS disconnected'}>
                    {armed ? '◎ CLICK FLOOR…' : '◎ GO TO [G]'}
                </button>
                <button className={buttonCss} onClick={onCancel} title='Cancel navigation (X)'>
                    ✕ CANCEL [X]
                </button>
            </div>
        </HudPanel>
    );
};

const missionCss = css`
    margin-top: 6px;
    padding-top: 4px;
    border-top: 1px solid var(--hud-faint);
`;

const missionHeadCss = css`
    font-size: 8px;
    letter-spacing: 0.12em;
    opacity: 0.6;
`;

const actionsCss = css`
    display: flex;
    gap: 6px;
    margin-top: 6px;
`;

const buttonCss = css`
    flex: 1;
    padding: 2px 4px;
    border: 1px solid var(--hud-dim);
    background: transparent;
    color: var(--hud);
    font: inherit;
    letter-spacing: inherit;
    cursor: pointer;

    &:hover:not(:disabled) {
        background: var(--hud-faint);
    }

    &:disabled {
        opacity: 0.35;
        cursor: not-allowed;
    }
`;

const armedCss = css`
    border-color: var(--hud-amber);
    color: #1a0f00;
    background: var(--hud-amber);
    text-shadow: none;

    &:hover {
        background: var(--hud-amber);
    }
`;

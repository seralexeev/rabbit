import { css, cx } from '@emotion/css';
import React from 'react';

import { useNats } from '../../app/NatsProvider.tsx';
import { L } from '../../log.ts';
import { type ExploreState, isLive } from '../../perception/Telemetry.ts';
import { useHud, useHudTick } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { Rows } from '../Rows.tsx';
import { type Tone, fixed, useFields, writeText } from '../fields.ts';

const START_SUBJECT = 'rabbit.nav.explore';
const START_REQUEST = { max_duration_s: 300, max_distance_m: 20 };
const STALE_MS = 3000;
const CONFIRM_MS = 4000;
const RUNNING = new Set(['planning', 'driving']);

const ROWS = [
    { label: 'PHASE' },
    { label: 'INFO' },
    { label: 'TIME' },
    { label: 'DIST' },
    { label: 'FRNT' },
    { label: 'TGT' },
    { label: 'PLAN' },
] as const;

const PHASE_TONES: Record<string, Tone> = { done: 'good', failed: 'alert', planning: 'warn', driving: 'warn' };

const limit = (state: ExploreState, key: string, unit: string) => {
    const value = state.limits?.[key];
    return value == null ? '' : ` / ${fixed(value, 0, unit)}`;
};

export const ExplorePanel: React.FC = () => {
    const { store, connected, stopRobot } = useHud();
    const { nc, link } = useNats();
    const fields = useFields();
    const [confirming, setConfirming] = React.useState(false);
    const [running, setRunning] = React.useState(false);
    const [snapshot, setSnapshot] = React.useState<ExploreState | null>(null);

    React.useEffect(() => {
        if (!confirming) return;
        const timer = window.setTimeout(() => setConfirming(false), CONFIRM_MS);
        return () => window.clearTimeout(timer);
    }, [confirming]);

    useHudTick((now) => {
        const state = isLive(store.explore, now, STALE_MS) ? store.explore.value : null;
        const nextRunning = state != null && RUNNING.has(state.phase);
        if (nextRunning !== running) setRunning(nextRunning);
        if (state !== snapshot) setSnapshot(state);
        const values = fields.current.values;
        if (state == null) {
            writeText(values[0], 'OFFLINE', 'warn');
            for (let i = 1; i < ROWS.length; i++) writeText(values[i], '—');
            return;
        }
        writeText(values[0], state.phase.toUpperCase(), PHASE_TONES[state.phase] ?? 'normal');
        writeText(values[1], state.message ?? '—', state.phase === 'failed' ? 'alert' : 'normal');
        writeText(values[2], `${fixed(state.elapsed_s, 0, ' s')}${limit(state, 'max_duration_s', ' s')}`);
        writeText(values[3], `${fixed(state.travelled_m, 1, ' m')}${limit(state, 'max_distance_m', ' m')}`);
        writeText(values[4], `${fixed(state.frontiers, 0)} · ${fixed(state.failed_frontiers, 0)} failed`);
        const target = state.target;
        writeText(
            values[5],
            target == null ? '—' : `${fixed(target.x, 2)} ${fixed(target.z, 2)} · ${fixed(target.path_length, 1, ' m')}`,
        );
        writeText(values[6], fixed(state.planning_ms, 0, ' ms'));
    });

    const start = () => {
        if (!confirming) {
            setConfirming(true);
            return;
        }
        setConfirming(false);
        if (link() !== 'connected') {
            L.warn('Exploration not started: NATS is not connected');
            return;
        }
        nc.publish(START_SUBJECT, JSON.stringify(START_REQUEST));
        L.info('Exploration started', START_REQUEST);
    };

    return (
        <HudPanel id='explore' code='EX' title='EXPLORE // AUTO' source='explore' detail={<ExploreDetail state={snapshot} />}>
            <Rows rows={ROWS} fields={fields} />
            <div className={actionsCss}>
                <button
                    className={cx(buttonCss, confirming && confirmCss)}
                    onClick={start}
                    disabled={!connected || running}
                    title={connected ? 'Start autonomous exploration (300 s, 20 m)' : 'NATS disconnected'}>
                    {confirming ? '▲ CONFIRM START' : '◎ START'}
                </button>
                <button className={buttonCss} onClick={stopRobot} disabled={!running} title='Cancel exploration and stop'>
                    ✕ ABORT
                </button>
            </div>
        </HudPanel>
    );
};

const ExploreDetail: React.FC<{ state: ExploreState | null }> = ({ state }) =>
    state == null ? (
        <div className={detailCss}>NO EXPLORATION STATE</div>
    ) : (
        <div className={detailCss}>
            {Object.entries(state).map(([key, value]) => (
                <div key={key} className={pairCss}>
                    <span>{key.replace(/_/g, ' ')}</span>
                    <span>{typeof value === 'object' && value != null ? JSON.stringify(value) : String(value ?? '—')}</span>
                </div>
            ))}
        </div>
    );

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

const confirmCss = css`
    border-color: var(--hud-amber);
    background: var(--hud-amber);
    color: #1a0f00;
    text-shadow: none;

    &:hover:not(:disabled) {
        background: var(--hud-amber);
    }
`;

const detailCss = css`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    column-gap: 20px;
    font-size: 11px;
`;

const pairCss = css`
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 2px 0;
    border-bottom: 1px solid var(--hud-faint);
    text-transform: none;

    & > span:first-child {
        opacity: 0.55;
        text-transform: uppercase;
    }

    & > span:last-child {
        text-align: right;
        overflow-wrap: anywhere;
    }
`;

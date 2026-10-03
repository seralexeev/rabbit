import { css } from '@emotion/css';
import React from 'react';

import { useNats } from '../../app/NatsProvider.tsx';
import { L } from '../../log.ts';
import { type ExploreState, isLive } from '../../perception/Telemetry.ts';
import { ConfirmButton, actionButtonCss, actionsCss } from '../ConfirmButton.tsx';
import { useHud, useHudTick } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { Rows } from '../Rows.tsx';
import { type Tone, fixed, useFields, writeText } from '../fields.ts';

const START_SUBJECT = 'rabbit.nav.explore';
const START_REQUEST = { max_duration_s: 300, max_distance_m: 20, source: 'hud' };
const STALE_MS = 3000;
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
    const [running, setRunning] = React.useState(false);
    const [snapshot, setSnapshot] = React.useState<ExploreState | null>(null);

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
                <ConfirmButton
                    label='◎ START'
                    confirmLabel='▲ CONFIRM START'
                    onConfirm={start}
                    disabled={!connected || running}
                    title={connected ? 'Start autonomous exploration (300 s, 20 m)' : 'NATS disconnected'}
                />
                <button className={actionButtonCss} onClick={stopRobot} disabled={!running} title='Cancel exploration and stop'>
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

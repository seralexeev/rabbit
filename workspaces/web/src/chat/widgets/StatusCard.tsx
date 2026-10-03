import { css } from '@emotion/css';
import React from 'react';

import { toNumber } from '../charts/plot.ts';
import { formatValue, summarizeInput } from '../outputs.ts';
import { type Landmark, type PathSpec, type Point, humanize } from '../results.ts';
import { PathView } from './PathView.tsx';
import { Card, Disclosure, Kpi, type Tone } from './kit.tsx';

type Section = Record<string, unknown>;

const SECTIONS = ['pose', 'nav', 'battery', 'obstacle', 'objects', 'camera'] as const;
const MOVING_LABELS = new Set(['person', 'cat', 'dog', 'robot vacuum']);
const ACTIVE_MODES = new Set(['driving', 'maneuvering']);
const ALERT_MODES = new Set(['blocked', 'fault']);

const sectionOf = (status: Record<string, unknown>, name: string): Section | null => {
    const value = status[name];
    return typeof value === 'object' && value != null && !Array.isArray(value) ? (value as Section) : null;
};

const fixed = (value: unknown, digits: number, unit = '') => {
    const n = toNumber(value);
    return n == null ? '—' : `${n.toFixed(digits)}${unit}`;
};

const point = (section: Section | null, x: string, z: string): Point | null => {
    const px = toNumber(section?.[x]);
    const pz = toNumber(section?.[z]);
    return px == null || pz == null ? null : { x: px, z: pz };
};

const landmarksOf = (objects: Section | null): Landmark[] =>
    (Array.isArray(objects?.['in_view']) ? objects['in_view'] : []).flatMap((item: unknown) => {
        const object = typeof item === 'object' && item != null ? (item as Section) : null;
        const at = point(object, 'x', 'z');
        const label = object?.['label'];
        if (at == null || typeof label !== 'string') return [];
        return [{ ...at, label, width: null, length: null, moving: MOVING_LABELS.has(label) }];
    });

const mapOf = (pose: Section | null, nav: Section | null, obstacle: Section | null, landmarks: Landmark[]): PathSpec | null => {
    const at = point(pose, 'x', 'z');
    if (at == null) return null;
    const goal = point(nav, 'goal_x', 'goal_z');
    return {
        trail: [],
        plan: goal == null ? [] : [at, goal],
        start: { ...at, heading: toNumber(pose?.['heading_deg']) ?? 0 },
        goal,
        obstacles: [point(obstacle, 'nearest_x', 'nearest_z'), point(obstacle, 'ahead_x', 'ahead_z')].filter((p) => p != null),
        landmarks,
        facts: [],
    };
};

const aheadTone = (distance: number | null): Tone =>
    distance == null ? 'ok' : distance < 0.3 ? 'alert' : distance < 0.6 ? 'warn' : 'normal';

const SectionRows: React.FC<{ values: Section }> = ({ values }) => (
    <div className={rowsCss}>
        {Object.entries(values).map(([key, value]) => (
            <div key={key}>
                <span>{humanize(key)}</span>
                <span>{typeof value === 'object' && value != null ? summarizeInput(value, 40) : formatValue(value)}</span>
            </div>
        ))}
    </div>
);

export const StatusCard: React.FC<{ status: Record<string, unknown> }> = ({ status }) => {
    const [pose = null, nav = null, battery = null, obstacle = null, objects = null, camera = null] = SECTIONS.map((name) =>
        sectionOf(status, name),
    );
    const mode = typeof nav?.['mode'] === 'string' ? nav['mode'] : null;
    const stepsTotal = toNumber(nav?.['steps_total']) ?? 0;
    const ahead = toNumber(obstacle?.['ahead_distance']);
    const tracking = camera?.['pose_state'];
    const present = [pose, nav, battery, obstacle, objects, camera].filter((section) => section != null);
    const recorded = present.filter((section) => section['source'] === 'recorded');
    const oldest = Math.max(0, ...present.map((section) => toNumber(section['age_s']) ?? 0));
    const landmarks = landmarksOf(objects);
    const map = mapOf(pose, nav, obstacle, landmarks);
    const notes = Array.isArray(status['notes'])
        ? status['notes'].filter((note): note is string => typeof note === 'string')
        : [];
    const missing = SECTIONS.filter((name) => sectionOf(status, name) == null);

    return (
        <Card
            title='Robot status'
            meta={
                present.length === 0
                    ? 'NO DATA'
                    : `${recorded.length === 0 ? 'LIVE' : recorded.length === present.length ? 'RECORDED' : 'PARTLY RECORDED'} · ≤ ${oldest.toFixed(1)} S OLD`
            }>
            <div className={layoutCss} data-map={map != null}>
                <div className={kpisCss}>
                    <Kpi
                        label='Nav'
                        value={mode?.toUpperCase() ?? '—'}
                        sub={
                            ACTIVE_MODES.has(mode ?? '') && stepsTotal > 0
                                ? `STEP ${formatValue(nav?.['step_index'])}/${stepsTotal}`
                                : undefined
                        }
                        tone={
                            mode == null ? 'normal' : ALERT_MODES.has(mode) ? 'alert' : ACTIVE_MODES.has(mode) ? 'warn' : 'ok'
                        }
                    />
                    <Kpi
                        label='Battery'
                        value={fixed(battery?.['voltage'], 2, ' V')}
                        sub={
                            battery == null
                                ? undefined
                                : `${fixed(battery['charge_pct'], 0, '%')} · ${fixed(battery['current_a'], 2, ' A')}`
                        }
                    />
                    <Kpi
                        label='Tracking'
                        value={tracking == null ? '—' : String(tracking)}
                        sub={camera == null ? undefined : `${fixed(camera['current_fps'], 0)} FPS`}
                        tone={tracking == null ? 'normal' : tracking === 'OK' ? 'ok' : 'alert'}
                    />
                    <Kpi
                        label='Obstacle ahead'
                        value={obstacle == null ? '—' : ahead == null ? 'CLEAR' : `${ahead.toFixed(2)} M`}
                        sub={obstacle == null ? undefined : `NEAREST ${fixed(obstacle['nearest_distance'], 2, ' M')}`}
                        tone={obstacle == null ? 'normal' : aheadTone(ahead)}
                    />
                    <Kpi
                        label='In view'
                        value={objects == null ? '—' : String(landmarks.length)}
                        sub={
                            landmarks.length === 0
                                ? undefined
                                : [...new Set(landmarks.map((landmark) => landmark.label.toUpperCase()))].join(' · ')
                        }
                    />
                    <Kpi
                        label='Pose'
                        value={pose == null ? '—' : `${fixed(pose['x'], 2)}, ${fixed(pose['z'], 2)}`}
                        sub={
                            pose == null
                                ? undefined
                                : `HDG ${fixed(pose['heading_deg'], 0, '°')} · ${fixed(pose['speed_mps'], 2, ' M/S')}`
                        }
                    />
                </div>
                {map != null && <PathView path={map} height={128} />}
            </div>
            {missing.length > 0 && <div className={missingCss}>NO DATA · {missing.join(', ').toUpperCase()}</div>}
            <Disclosure label='All fields'>
                <div className={detailsCss}>
                    {SECTIONS.map((name) => {
                        const section = sectionOf(status, name);
                        return section == null ? null : (
                            <div key={name}>
                                <div className={sectionTitleCss}>{name}</div>
                                <SectionRows values={section} />
                            </div>
                        );
                    })}
                    {notes.length > 0 && (
                        <ul className={notesCss}>
                            {notes.map((note) => (
                                <li key={note}>{note}</li>
                            ))}
                        </ul>
                    )}
                </div>
            </Disclosure>
        </Card>
    );
};

const layoutCss = css`
    display: grid;
    gap: 8px;
    margin-bottom: 4px;

    &[data-map='true'] {
        grid-template-columns: minmax(0, 1fr) minmax(110px, 0.8fr);
        align-items: start;
    }
`;

const kpisCss = css`
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
    gap: 6px 8px;
`;

const missingCss = css`
    margin: 2px 0;
    color: var(--hud-amber);
    font-size: 8.5px;
    letter-spacing: 0.08em;
`;

const detailsCss = css`
    display: grid;
    gap: 5px;
    padding: 2px 0 0 13px;
    font-size: 9.5px;
`;

const sectionTitleCss = css`
    font-size: 8px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    opacity: 0.5;
`;

const rowsCss = css`
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 10px;

    & > div {
        display: flex;
        justify-content: space-between;
        gap: 6px;
        overflow: hidden;
        white-space: nowrap;
    }

    & > div > span:first-child {
        opacity: 0.55;
        text-transform: uppercase;
    }
`;

const notesCss = css`
    margin: 0;
    padding-left: 14px;
    font-size: 9px;
    opacity: 0.6;
    text-transform: none;
`;

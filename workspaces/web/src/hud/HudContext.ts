import React from 'react';

import { useEvent } from '../hooks.ts';
import type { FloorPlan } from '../perception/FloorPlan.ts';
import type { TelemetryStore } from '../perception/Telemetry.ts';
import type { History } from '../perception/history.ts';
import type { HudEngine } from './Hud.ts';

const PANEL_IDS = [
    'minimap',
    'nav',
    'route',
    'explore',
    'system',
    'zed',
    'power',
    'wifi',
    'drive-left',
    'drive-right',
    'steering',
    'roboclaw',
    'gamepad',
] as const;
export type PanelId = (typeof PANEL_IDS)[number];

export type HudLayout = { left: PanelId[]; right: PanelId[]; collapsed: PanelId[] };

export const DEFAULT_LAYOUT: HudLayout = {
    left: ['nav', 'route', 'explore', 'system', 'drive-left', 'steering'],
    right: ['minimap', 'zed', 'power', 'wifi', 'drive-right', 'roboclaw', 'gamepad'],
    collapsed: [],
};

const isPanelId = (value: unknown): value is PanelId => PANEL_IDS.includes(value as PanelId);

export const normalize = (raw: unknown): HudLayout => {
    const source = (raw ?? {}) as Partial<Record<keyof HudLayout, unknown[]>>;
    const seen = new Set<PanelId>();
    const pick = (list: unknown[] | undefined) =>
        (list ?? []).filter((id): id is PanelId => {
            if (!isPanelId(id) || seen.has(id)) return false;
            seen.add(id);
            return true;
        });
    const left = pick(source.left);
    const right = pick(source.right);
    for (const id of PANEL_IDS) {
        if (seen.has(id)) continue;
        const defaults = DEFAULT_LAYOUT.left.includes(id) ? DEFAULT_LAYOUT.left : DEFAULT_LAYOUT.right;
        const list = defaults === DEFAULT_LAYOUT.left ? left : right;
        list.splice(Math.min(defaults.indexOf(id), list.length), 0, id);
    }
    return { left, right, collapsed: (source.collapsed ?? []).filter(isPanelId) };
};

type HudContextValue = {
    engine: HudEngine;
    store: TelemetryStore;
    floorPlan: FloorPlan;
    history: History;
    connected: boolean;
    stopRobot: () => void;
    layout: HudLayout;
    toggle: (id: PanelId) => void;
    swap: (id: PanelId) => void;
};

export const HudContext = React.createContext<HudContextValue | null>(null);

export const useHud = () => {
    const context = React.useContext(HudContext);
    if (context == null) {
        throw new Error('useHud must be used within a HudProvider');
    }
    return context;
};

export const useHudTick = (fn: (now: number) => void) => {
    const { engine } = useHud();
    const callback = useEvent(fn);
    React.useEffect(() => engine.onTick(callback), [engine, callback]);
};

export const useHudFrame = (fn: (now: number) => void) => {
    const { engine } = useHud();
    const callback = useEvent(fn);
    React.useEffect(() => engine.onFrame(callback), [engine, callback]);
};

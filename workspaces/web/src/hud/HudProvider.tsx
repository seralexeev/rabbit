import React from 'react';

import { useLocalState } from '../hooks.ts';
import type { FloorPlan } from '../perception/FloorPlan.ts';
import type { TelemetryStore } from '../perception/Telemetry.ts';
import type { History } from '../perception/history.ts';
import type { HudEngine } from './Hud.ts';
import { DEFAULT_LAYOUT, HudContext, type HudLayout, type PanelId, normalize } from './HudContext.ts';

export const HudProvider: React.FC<{
    engine: HudEngine;
    store: TelemetryStore;
    floorPlan: FloorPlan;
    history: History;
    connected: boolean;
    stopRobot: () => void;
    children: React.ReactNode;
}> = ({ engine, store, floorPlan, history, connected, stopRobot, children }) => {
    const [layout, update] = useLocalState<HudLayout>('rabbit.ui.hud', normalize, DEFAULT_LAYOUT);

    const toggle = (id: PanelId) =>
        update((prev) => ({
            ...prev,
            collapsed: prev.collapsed.includes(id) ? prev.collapsed.filter((x) => x !== id) : [...prev.collapsed, id],
        }));

    const swap = (id: PanelId) =>
        update((prev) => {
            const fromLeft = prev.left.includes(id);
            const from = fromLeft ? prev.left : prev.right;
            const to = fromLeft ? prev.right : prev.left;
            const index = Math.min(from.indexOf(id), to.length);
            const nextFrom = from.filter((x) => x !== id);
            const nextTo = [...to.slice(0, index), id, ...to.slice(index)];
            return fromLeft ? { ...prev, left: nextFrom, right: nextTo } : { ...prev, left: nextTo, right: nextFrom };
        });

    return (
        <HudContext.Provider value={{ engine, store, floorPlan, history, connected, stopRobot, layout, toggle, swap }}>
            {children}
        </HudContext.Provider>
    );
};

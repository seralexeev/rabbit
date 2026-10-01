import { L } from '../log.ts';

export const HUD_COLOR = 0x62e8ff;

const TICK_MS = 125;
const ERROR_LOG_MS = 5000;

export type HudEngine = {
    frame: (now: number) => void;
    onFrame: (fn: (now: number) => void) => () => void;
    onTick: (fn: (now: number) => void) => () => void;
};

export const createHudEngine = (): HudEngine => {
    const frameListeners = new Set<(now: number) => void>();
    const tickListeners = new Set<(now: number) => void>();
    let lastTick = -Infinity;
    let lastErrorLog = -Infinity;
    let suppressed = 0;

    const run = (fn: (now: number) => void, now: number) => {
        try {
            fn(now);
        } catch (error) {
            if (now - lastErrorLog < ERROR_LOG_MS) {
                suppressed++;
                return;
            }
            L.error(`HUD listener failed${suppressed > 0 ? ` (${suppressed} more suppressed)` : ''}`, error);
            lastErrorLog = now;
            suppressed = 0;
        }
    };

    return {
        frame: (now) => {
            for (const fn of frameListeners) run(fn, now);
            if (now - lastTick >= TICK_MS) {
                lastTick = now;
                for (const fn of tickListeners) run(fn, now);
            }
        },
        onFrame: (fn) => {
            frameListeners.add(fn);
            return () => {
                frameListeners.delete(fn);
            };
        },
        onTick: (fn) => {
            tickListeners.add(fn);
            return () => {
                tickListeners.delete(fn);
            };
        },
    };
};

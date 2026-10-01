import { L } from '../log.ts';

export const HUD_COLOR = 0x62e8ff;

type Side = 'left' | 'right';

const TOP = 46;
const MARGIN = 12;
const GAP = 8;
const COMPACT_HEIGHT = 34;
const LAYOUT_RATE = 12;
const TICK_MS = 125;
const ERROR_LOG_MS = 5000;

export type HudEngine = {
    attach: (root: HTMLElement) => () => void;
    register: (id: string, element: HTMLElement) => () => void;
    setColumns: (left: readonly string[], right: readonly string[]) => void;
    frame: (dt: number, now: number) => void;
    onFrame: (fn: (now: number) => void) => () => void;
    onTick: (fn: (now: number) => void) => () => void;
};

type Panel = {
    element: HTMLElement;
    height: number;
    expandedHeight: number;
    compact: boolean;
    placed: boolean;
    y: number;
    x: number;
    drawnY: number;
};

export const createHudEngine = (): HudEngine => {
    const panels = new Map<string, Panel>();
    const frameListeners = new Set<(now: number) => void>();
    const tickListeners = new Set<(now: number) => void>();
    let columns: { left: readonly string[]; right: readonly string[] } = { left: [], right: [] };
    let root: HTMLElement | null = null;
    let width = 0;
    let height = 0;
    let columnWidth = 0;
    let lastTick = -Infinity;
    const column: Panel[] = [];
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

    const measurePanel = (panel: Panel) => {
        panel.height = panel.element.offsetHeight;
        if (!panel.compact) panel.expandedHeight = panel.height;
    };

    const observer = new ResizeObserver((entries) => {
        for (const entry of entries) {
            if (entry.target === root) {
                width = root.clientWidth;
                height = root.clientHeight;
                columnWidth = parseFloat(getComputedStyle(root).getPropertyValue('--hud-column')) || 272;
                continue;
            }
            for (const panel of panels.values()) {
                if (panel.element === entry.target) measurePanel(panel);
            }
        }
    });

    const setCompact = (panel: Panel, compact: boolean) => {
        if (panel.compact === compact) return;
        panel.compact = compact;
        panel.element.dataset['compact'] = compact ? 'true' : 'false';
    };

    const draw = (panel: Panel, side: Side) => {
        const x = side === 'left' ? MARGIN : Math.round(width - MARGIN - columnWidth);
        const y = Math.round(panel.y);
        if (x !== panel.x || y !== panel.drawnY) {
            panel.x = x;
            panel.drawnY = y;
            panel.element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
        }
        if (!panel.placed) {
            panel.placed = true;
            panel.element.dataset['placed'] = 'true';
        }
    };

    const layoutColumn = (ids: readonly string[], side: Side, k: number) => {
        column.length = 0;
        for (const id of ids) {
            const panel = panels.get(id);
            if (panel != null) column.push(panel);
        }

        let total = -GAP;
        for (const panel of column) total += panel.expandedHeight + GAP;
        for (let i = column.length - 1; i >= 0; i--) {
            const panel = column[i]!;
            const shrink = Math.max(panel.expandedHeight - COMPACT_HEIGHT, 0);
            const compact = total > height - MARGIN - TOP && shrink > 0;
            if (compact) total -= shrink;
            setCompact(panel, compact);
        }

        let target = TOP;
        for (const panel of column) {
            panel.y = panel.placed ? panel.y + (target - panel.y) * k : target;
            target += panel.height + GAP;
            draw(panel, side);
        }
    };

    return {
        attach: (nextRoot) => {
            root = nextRoot;
            observer.observe(nextRoot);
            return () => {
                observer.unobserve(nextRoot);
                root = null;
            };
        },
        register: (id, element) => {
            const panel: Panel = {
                element,
                height: 0,
                expandedHeight: 0,
                compact: false,
                placed: false,
                y: 0,
                x: Number.NaN,
                drawnY: Number.NaN,
            };
            panels.set(id, panel);
            measurePanel(panel);
            observer.observe(element);
            return () => {
                observer.unobserve(element);
                if (panels.get(id) === panel) panels.delete(id);
            };
        },
        setColumns: (left, right) => {
            columns = { left, right };
        },
        frame: (dt, now) => {
            for (const fn of frameListeners) run(fn, now);
            if (now - lastTick >= TICK_MS) {
                lastTick = now;
                for (const fn of tickListeners) run(fn, now);
            }
            if (root == null || width === 0) return;
            const k = 1 - Math.exp(-LAYOUT_RATE * dt);
            layoutColumn(columns.left, 'left', k);
            layoutColumn(columns.right, 'right', k);
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

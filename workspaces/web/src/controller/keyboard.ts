import type { NatsConnection } from '@nats-io/nats-core';

import { type DualSenseState, NEUTRAL_STATE } from './dualsense.ts';
import { JOY_PERIOD_MS, JOY_RELEASE_FRAMES, JOY_SUBJECT } from './joy.ts';

const ARROWS = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' } as const;
export type Arrow = (typeof ARROWS)[keyof typeof ARROWS];
export const ARROW_ORDER: readonly Arrow[] = Object.values(ARROWS);

const SPEED = 0.5;
const FAST_SPEED = 1;

export type KeyboardDrive = { held: ReadonlySet<Arrow>; fast: boolean; speed: number; steer: number };

const arrowFor = (code: string): Arrow | null => ARROWS[code as keyof typeof ARROWS] ?? null;

export const driveFor = (held: ReadonlySet<Arrow>, fast: boolean): KeyboardDrive => {
    const axis = (positive: Arrow, negative: Arrow) => Number(held.has(positive)) - Number(held.has(negative));
    return { held, fast, speed: axis('up', 'down') * (fast ? FAST_SPEED : SPEED), steer: axis('right', 'left') };
};

export const joyStateFor = ({ speed, steer }: KeyboardDrive): DualSenseState => {
    const trigger = (value: number) => ({ pressed: value > 0, value });
    return {
        buttons: { ...NEUTRAL_STATE.buttons, r2: trigger(Math.max(speed, 0)), l2: trigger(Math.max(-speed, 0)) },
        sticks: { left: { x: steer, y: 0 }, right: NEUTRAL_STATE.sticks.right },
    };
};

export const isEditable = (target: EventTarget | null) =>
    target instanceof HTMLElement && (target.isContentEditable || target.matches('input, textarea, select'));

export type KeyboardDriver = { start: (nc: NatsConnection) => () => void; read: () => KeyboardDrive };

export const createKeyboardDriver = (): KeyboardDriver => {
    const held = new Set<Arrow>();
    let fast = false;
    let timer: number | null = null;
    let releaseFrames = 0;

    const read = () => driveFor(held, fast);

    const start = (nc: NatsConnection) => {
        const publish = (state: DualSenseState) => nc.publish(JOY_SUBJECT, JSON.stringify(state));

        const stopTimer = () => {
            if (timer != null) window.clearInterval(timer);
            timer = null;
        };

        const tick = () => {
            if (held.size > 0) {
                releaseFrames = JOY_RELEASE_FRAMES;
                publish(joyStateFor(read()));
            } else if (releaseFrames > 0) {
                releaseFrames--;
                publish(NEUTRAL_STATE);
            } else {
                stopTimer();
            }
        };

        const update = () => {
            tick();
            if (timer == null && (held.size > 0 || releaseFrames > 0)) timer = window.setInterval(tick, JOY_PERIOD_MS);
        };

        const release = () => {
            fast = false;
            if (held.size === 0) return;
            held.clear();
            update();
        };

        const onKeyDown = (event: KeyboardEvent) => {
            if (event.ctrlKey || event.metaKey || event.altKey) {
                release();
                return;
            }
            fast = event.shiftKey;
            const arrow = arrowFor(event.code);
            if (arrow == null || isEditable(event.target)) return;
            event.preventDefault();
            if (held.has(arrow)) return;
            held.add(arrow);
            update();
        };

        const onKeyUp = (event: KeyboardEvent) => {
            fast = event.shiftKey;
            const arrow = arrowFor(event.code);
            if (arrow == null || !held.delete(arrow)) return;
            update();
        };

        const onVisibility = () => {
            if (document.visibilityState !== 'visible') release();
        };

        const onFocusIn = (event: FocusEvent) => {
            if (isEditable(event.target)) release();
        };

        const controller = new AbortController();
        const options = { signal: controller.signal };
        window.addEventListener('keydown', onKeyDown, options);
        window.addEventListener('keyup', onKeyUp, options);
        window.addEventListener('blur', release, options);
        document.addEventListener('visibilitychange', onVisibility, options);
        document.addEventListener('focusin', onFocusIn, options);

        return () => {
            controller.abort();
            const driving = timer != null;
            stopTimer();
            held.clear();
            fast = false;
            releaseFrames = 0;
            if (driving) publish(NEUTRAL_STATE);
        };
    };

    return { start, read };
};

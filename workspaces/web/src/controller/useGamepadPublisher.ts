import type { NatsConnection } from '@nats-io/nats-core';
import React from 'react';

import { useNats } from '../app/NatsProvider.tsx';
import { L } from '../log.ts';
import { NEUTRAL_STATE, isNeutral, readDualSense } from './dualsense.ts';
import { JOY_PERIOD_MS, JOY_RELEASE_FRAMES, JOY_SUBJECT } from './joy.ts';

const canDrive = () => document.visibilityState === 'visible' && document.hasFocus();

const startPublishing = (nc: NatsConnection) => {
    let padId: string | null = null;
    let timer: number | null = null;
    let releaseFrames = 0;

    const publish = (state: unknown) => nc.publish(JOY_SUBJECT, JSON.stringify(state));

    const findPad = () => {
        const pads = navigator.getGamepads().filter((pad): pad is Gamepad => pad != null && pad.connected);
        const pad = pads.find((candidate) => candidate.id === padId) ?? pads[0] ?? null;
        if (pad != null && pad.id !== padId) {
            padId = pad.id;
            L.info('Gamepad selected', { id: pad.id });
        }
        return pad;
    };

    const tick = () => {
        const pad = findPad();
        if (pad == null) {
            update();
            return;
        }
        const state = readDualSense(pad);
        if (!isNeutral(state)) {
            releaseFrames = JOY_RELEASE_FRAMES;
            publish(state);
        } else if (releaseFrames > 0) {
            releaseFrames--;
            publish(NEUTRAL_STATE);
        }
    };

    const stop = () => {
        if (timer == null) return;
        window.clearInterval(timer);
        timer = null;
        releaseFrames = 0;
        publish(NEUTRAL_STATE);
    };

    const update = () => {
        const active = canDrive() && findPad() != null;
        if (active && timer == null) timer = window.setInterval(tick, JOY_PERIOD_MS);
        else if (!active) stop();
    };

    const onDisconnect = (event: GamepadEvent) => {
        if (event.gamepad.id === padId) padId = null;
        update();
    };

    const controller = new AbortController();
    const options = { signal: controller.signal };
    window.addEventListener('gamepadconnected', update, options);
    window.addEventListener('gamepaddisconnected', onDisconnect, options);
    window.addEventListener('focus', update, options);
    window.addEventListener('blur', update, options);
    document.addEventListener('visibilitychange', update, options);
    update();

    return () => {
        controller.abort();
        stop();
    };
};

export const useGamepadPublisher = () => {
    const { nc } = useNats();
    React.useEffect(() => startPublishing(nc), [nc]);
};

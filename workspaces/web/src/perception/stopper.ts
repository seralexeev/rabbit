import type { NatsConnection } from '@nats-io/nats-core';

import { L } from '../log.ts';
import type { TelemetryStore } from './Telemetry.ts';

const REPEAT_MS = 200;
const MAX_MS = 5000;
const STOPPED_MODES = new Set(['idle', 'arrived', 'fault']);

type Stopper = { stop: () => void; dispose: () => void };

export const createStopper = (nc: NatsConnection, store: TelemetryStore): Stopper => {
    let timer: number | null = null;

    const clear = () => {
        if (timer != null) window.clearInterval(timer);
        timer = null;
    };

    const publish = () => {
        nc.publish('rabbit.nav.cancel', JSON.stringify({}));
        nc.publish('rabbit.cmd.drive', JSON.stringify({ speed: 0, steer: 0 }));
    };

    return {
        stop: () => {
            clear();
            const startedAt = performance.now();
            const startVersion = store.nav.version;
            publish();
            L.warn('STOP issued');
            timer = window.setInterval(() => {
                const mode = store.nav.value?.mode;
                const confirmed = store.nav.version > startVersion && mode != null && STOPPED_MODES.has(mode);
                if (confirmed || performance.now() - startedAt > MAX_MS) {
                    clear();
                    if (!confirmed) L.warn('STOP not confirmed by rabbit.nav.state within 5 s');
                    return;
                }
                publish();
            }, REPEAT_MS);
        },
        dispose: clear,
    };
};

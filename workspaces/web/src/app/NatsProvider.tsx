import { type JetStreamClient, jetstream } from '@nats-io/jetstream';
import { type KV, type KvWatchEntry, Kvm } from '@nats-io/kv';
import { type Msg, type NatsConnection, type SubscriptionOptions, wsconnect } from '@nats-io/nats-core';
import { useQuery } from '@tanstack/react-query';
import React from 'react';

import { useEvent } from '../hooks.ts';
import { L } from '../terminal/LogProvider.tsx';
import { ui } from '../ui/index.ts';

const ALIVE_KEY = 'rabbit.operator.alive';

const NatsContext = React.createContext<{
    nc: NatsConnection;
    kv: KV;
    js: JetStreamClient;
} | null>(null);

export const NatsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const heartbeatIntervalRef = React.useRef<number | null>(null);

    const query = useQuery({
        queryKey: ['nats'],
        queryFn: connect,
    });

    React.useEffect(() => {
        if (query.isError) {
            L.error('Failed to connect to NATS server', query.error);
        } else if (query.isSuccess) {
            L.info('Connected to NATS server');
            const { kv } = query.data;

            heartbeatIntervalRef.current = window.setInterval(() => {
                void kv
                    .put(ALIVE_KEY, JSON.stringify(true), { ttl: '5s' })
                    .catch((error) => L.error('Failed to send heartbeat', error));
            }, 1_000);
        }

        return () => {
            if (heartbeatIntervalRef.current != null) {
                window.clearInterval(heartbeatIntervalRef.current);
                heartbeatIntervalRef.current = null;
            }
        };
    }, [query]);

    if (query.data == null) {
        return <ui.SplashSpinner children='Connecting to NATS server...' />;
    }

    return <NatsContext.Provider value={query.data}>{children}</NatsContext.Provider>;
};

export const useSubscribe = (
    subject: string,
    options: Omit<SubscriptionOptions, 'callback'> & { callback: (msg: Msg) => unknown },
) => {
    const { nc } = useNats();

    const callback = useEvent(options.callback);

    React.useEffect(() => {
        const sub = nc.subscribe(subject, {
            ...options,
            callback: (err, msg) => {
                if (err) {
                    L.error(`Error in subscription to subject ${subject}`, err);
                    return;
                }

                (async () => {
                    try {
                        await callback(msg);
                    } catch (e) {
                        L.error(`Failed to parse message from subject ${subject}`, e);
                    }
                })();
            },
        });

        L.info('Subscribed to subject', { subject });

        return () => {
            sub.unsubscribe();
            L.info('Unsubscribed from subject', { subject });
        };
    }, [nc, subject]);
};

export const useWatchNats = <T,>(options: { key: string; fn: (data: KvWatchEntry) => Promise<T> | T }) => {
    const { kv } = useNats();
    const fn = useEvent(options.fn);
    const [value, setValue] = React.useState<T | null>(null);

    React.useEffect(() => {
        const watcher = kv.watch(options);

        (async () => {
            for await (const entry of await watcher) {
                try {
                    const result = await fn(entry);
                    setValue(result);
                } catch (e) {
                    L.error('Failed to parse entry from NATS', e);
                }
            }
        })().catch((e) => {
            L.error('Failed to watch NATS', e);
        });

        return () => {
            void watcher.then((w) => w.stop()).catch((e) => L.error('Failed to close camera settings watcher', e));
        };
    }, []);

    const updateValue = (fn: (prev: T | null) => T | null) => {
        const newValue = fn(value);
        setValue(newValue);
        return kv.put(options.key, JSON.stringify(newValue));
    };

    return [value, updateValue] as const;
};

const connect = async () => {
    L.info('Connecting to NATS server...');

    const nc = await wsconnect({
        servers: ['wss://jetson.rabbit:9222'],
        reconnect: true,
        maxReconnectAttempts: -1,
        waitOnFirstConnect: true,
        name: 'rabbit-web',
    });

    const kvm = new Kvm(nc);
    const js = jetstream(nc);
    const kv = await kvm.open('rabbit', {
        markerTTL: 5_000,
    });

    await kv.purge(ALIVE_KEY);
    await kv.create(ALIVE_KEY, JSON.stringify(true), '5s');

    return { nc, kv, js };
};

export const useNats = () => {
    const context = React.useContext(NatsContext);
    if (context == null) {
        throw new Error('useNats must be used within a NatsProvider');
    }

    return context;
};

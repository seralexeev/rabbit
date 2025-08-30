import { type JetStreamClient, jetstream } from '@nats-io/jetstream';
import { type KV, type KvEntry, type KvWatchEntry, Kvm } from '@nats-io/kv';
import { type Msg, type NatsConnection, type SubscriptionOptions, wsconnect } from '@nats-io/nats-core';
import { type ObjectResult, type ObjectStore, type ObjectWatchInfo, Objm } from '@nats-io/obj';
import { useQuery } from '@tanstack/react-query';
import { createNanoEvents } from 'nanoevents';
import React from 'react';

import { useEvent } from '../hooks.ts';
import { L } from '../terminal/LogProvider.tsx';
import { ui } from '../ui/index.ts';

const NatsContext = React.createContext<{
    nc: NatsConnection;
    js: JetStreamClient;
    kv: KV;
    obj: ObjectStore;
} | null>(null);

export const NatsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const query = useQuery({
        queryKey: ['nats'],
        queryFn: connect,
    });

    React.useEffect(() => {
        let heartbeatInterval: number | null = null;

        if (query.isError) {
            L.error('Failed to connect to NATS server', query.error);
        } else if (query.isSuccess) {
            L.info('Connected to NATS server');
            const { kv } = query.data;

            heartbeatInterval = window.setInterval(() => {
                void kv
                    .put('rabbit.operator.heartbeat', JSON.stringify(true), { ttl: '5s' })
                    .catch((error) => L.error('Failed to send heartbeat', error));
            }, 1_000);
        }

        return () => {
            if (heartbeatInterval != null) {
                window.clearInterval(heartbeatInterval);
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

export const useWatchKV = <T,>(options: { key: string; parse: (data: KvWatchEntry) => Promise<T> | T }) => {
    const { kv } = useNats();
    const fn = useEvent(options.parse);
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
        })().catch((e) => L.error('Failed to watch NATS', e));

        return () => {
            void watcher.then((w) => w.stop()).catch((e) => L.error('Failed to close NATS watcher', e));
        };
    }, []);

    const updateValue = (fn: (prev: T | null) => T | null) => {
        const newValue = fn(value);
        setValue(newValue);
        return kv.put(options.key, JSON.stringify(newValue));
    };

    return [value, updateValue] as const;
};

export const useObjectStoreSubscribe = () => {
    const { obj } = useNats();
    const [emitter] = React.useState(() => createNanoEvents<{ onChange: (info: ObjectWatchInfo) => Promise<void> }>());

    const subscribe = useEvent((name: string, fn: (value: ObjectResult | null) => Promise<void> | void) =>
        emitter.on('onChange', async (info) => {
            if (info?.name === name) {
                const result = await obj.get(info.name);
                fn(result);
            }
        }),
    );

    React.useEffect(() => {
        const watcher = obj.watch();

        (async () => {
            for await (const info of await watcher) {
                try {
                    L.info('Received update for object', { name: info.name, revision: info.revision });
                    emitter.emit('onChange', info);
                } catch (e) {
                    L.error('Failed to parse entry from NATS Object Store', e);
                }
            }
        })().catch((e) => L.error('Failed to watch NATS Object Store', e));

        return () => {
            void watcher.then((w) => w.stop()).catch((e) => L.error('Failed to close NATS Object Store watcher', e));
        };
    }, []);

    return subscribe;
};

export const useKVSubscribe = () => {
    const { kv } = useNats();

    const subscribe = useEvent((key: string, fn: (value: KvEntry | null) => Promise<void> | void) => {
        const watcher = kv.watch({ key });

        (async () => {
            for await (const info of await watcher) {
                try {
                    await fn(info);
                } catch (e) {
                    L.error('Failed to parse KV entry from NATS', e);
                }
            }
        })().catch((e) => L.error('Failed to watch NATS KV Store', e));

        return {
            unsubscribe: () => watcher.then((w) => w.stop()).catch((e) => L.error('Failed to close NATS watcher', e)),
        };
    });

    return subscribe;
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
    const objm = new Objm(nc);
    const js = jetstream(nc);
    const kv = await kvm.open('rabbit');
    const obj = await objm.open('rabbit');

    return { nc, kv, js, obj };
};

export const useNats = () => {
    const context = React.useContext(NatsContext);
    if (context == null) {
        throw new Error('useNats must be used within a NatsProvider');
    }

    return context;
};

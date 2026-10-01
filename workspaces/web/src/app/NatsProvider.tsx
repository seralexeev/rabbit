import { css } from '@emotion/css';
import { type KV, Kvm } from '@nats-io/kv';
import { type Msg, type NatsConnection, wsconnect } from '@nats-io/nats-core';
import React from 'react';

import { useEvent } from '../hooks.ts';
import { L } from '../log.ts';
import { ui } from '../ui/index.ts';

const KV_BUCKET = 'rabbit';
const SERVER = import.meta.env['VITE_NATS_URL'] ?? 'wss://jetson.rabbit:9222';
const HEARTBEAT_SUBJECT = 'rabbit.operator.heartbeat';
const HEARTBEAT_MS = 500;
const DISPLAY_INTERVAL_MS = 100;
const PING_INTERVAL_MS = 3000;
const MAX_PINGS_OUT = 2;

export type LinkState = 'connected' | 'reconnecting' | 'disconnected';

type NatsContextValue = {
    nc: NatsConnection;
    kv: KV;
    link: () => LinkState;
    onLink: (fn: (state: LinkState) => void) => () => void;
};

const NatsContext = React.createContext<NatsContextValue | null>(null);

type Connection = { state: 'connecting' } | { state: 'error'; message: string } | { state: 'ready'; value: NatsContextValue };

const connect = async (): Promise<{ nc: NatsConnection; kv: KV }> => {
    L.info('Connecting to NATS server...');
    const nc = await wsconnect({
        servers: [SERVER],
        reconnect: true,
        maxReconnectAttempts: -1,
        waitOnFirstConnect: true,
        pingInterval: PING_INTERVAL_MS,
        maxPingOut: MAX_PINGS_OUT,
        name: 'rabbit-web',
    });
    try {
        const kv = await new Kvm(nc).open(KV_BUCKET);
        return { nc, kv };
    } catch (error) {
        await nc.close();
        throw error;
    }
};

const createLink = (nc: NatsConnection) => {
    let state: LinkState = 'connected';
    const listeners = new Set<(state: LinkState) => void>();
    const set = (next: LinkState) => {
        if (next === state) return;
        state = next;
        for (const fn of listeners) fn(next);
    };
    void (async () => {
        for await (const status of nc.status()) {
            if (status.type === 'disconnect') set('disconnected');
            else if (status.type === 'reconnecting' || status.type === 'staleConnection') set('reconnecting');
            else if (status.type === 'reconnect') set('connected');
            else if (status.type === 'close') set('disconnected');
        }
    })().catch((error) => L.error('NATS status monitor failed', error));
    return {
        link: () => state,
        onLink: (fn: (state: LinkState) => void) => {
            listeners.add(fn);
            return () => {
                listeners.delete(fn);
            };
        },
    };
};

export const NatsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [connection, setConnection] = React.useState<Connection>({ state: 'connecting' });
    const [attempt, setAttempt] = React.useState(0);

    React.useEffect(() => {
        let cancelled = false;
        let opened: NatsConnection | null = null;
        setConnection({ state: 'connecting' });
        connect()
            .then(({ nc, kv }) => {
                opened = nc;
                if (cancelled) {
                    void nc.close();
                    return;
                }
                L.info('Connected to NATS server');
                setConnection({ state: 'ready', value: { nc, kv, ...createLink(nc) } });
            })
            .catch((error: unknown) => {
                L.error('Failed to connect to NATS server', error);
                if (!cancelled)
                    setConnection({ state: 'error', message: error instanceof Error ? error.message : String(error) });
            });
        return () => {
            cancelled = true;
            void opened?.close();
        };
    }, [attempt]);

    if (connection.state === 'connecting') {
        return <ui.SplashSpinner children='Connecting to NATS server...' />;
    }
    if (connection.state === 'error') {
        return (
            <div className={errorCss}>
                <div>NATS LINK FAILED</div>
                <div className={errorDetailCss}>{connection.message}</div>
                <button className={retryCss} onClick={() => setAttempt((value) => value + 1)}>
                    RETRY
                </button>
            </div>
        );
    }

    return (
        <NatsContext.Provider value={connection.value}>
            <Heartbeat />
            {children}
        </NatsContext.Provider>
    );
};

const Heartbeat: React.FC = () => {
    const { nc, link } = useNats();

    React.useEffect(() => {
        const timer = window.setInterval(() => {
            if (link() !== 'connected' || document.visibilityState !== 'visible') return;
            nc.publish(HEARTBEAT_SUBJECT, JSON.stringify({ ts: Date.now() }));
        }, HEARTBEAT_MS);
        return () => window.clearInterval(timer);
    }, [nc, link]);

    return null;
};

export const useNats = () => {
    const context = React.useContext(NatsContext);
    if (context == null) {
        throw new Error('useNats must be used within a NatsProvider');
    }
    return context;
};

export const useLinkState = () => {
    const { link, onLink } = useNats();
    const [state, setState] = React.useState(link);
    React.useEffect(() => {
        setState(link());
        return onLink(setState);
    }, [link, onLink]);
    return state;
};

export const useSubjectState = <T,>(subject: string, parse: (msg: Msg) => T, intervalMs = DISPLAY_INTERVAL_MS) => {
    const { nc } = useNats();
    const parseEvent = useEvent(parse);
    const [value, setValue] = React.useState<T | null>(null);

    React.useEffect(() => {
        let latest: Msg | null = null;
        let timer: number | null = null;

        const flush = () => {
            timer = null;
            if (latest == null) {
                return;
            }

            const msg = latest;
            latest = null;

            try {
                setValue(parseEvent(msg));
            } catch (e) {
                L.error(`Failed to parse message from subject ${subject}`, e);
            }
        };

        const sub = nc.subscribe(subject, {
            callback: (err, msg) => {
                if (err) {
                    L.error(`Error in subscription to subject ${subject}`, err);
                    return;
                }

                latest = msg;
                if (timer == null) {
                    timer = window.setTimeout(flush, intervalMs);
                }
            },
        });

        return () => {
            sub.unsubscribe();
            if (timer != null) {
                window.clearTimeout(timer);
            }
        };
    }, [nc, subject, intervalMs]);

    return value;
};

const errorCss = css`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    height: 100%;
    color: var(--hud-alert);
    letter-spacing: 0.12em;
`;

const errorDetailCss = css`
    color: var(--hud-dim);
    font-size: 10px;
    letter-spacing: 0.04em;
`;

const retryCss = css`
    padding: 4px 14px;
    border: 1px solid var(--hud);
    background: none;
    color: var(--hud);
    font: inherit;
    letter-spacing: 0.12em;
    cursor: pointer;
`;

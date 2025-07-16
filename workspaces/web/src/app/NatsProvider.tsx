import { type NatsConnection, wsconnect } from '@nats-io/nats-core';
import { useQuery } from '@tanstack/react-query';
import React from 'react';

import { L } from '../terminal/LogProvider.tsx';
import { ui } from '../ui/index.ts';

const NatsContext = React.createContext<NatsConnection | null>(null);

export const useNats = () => {
    const context = React.useContext(NatsContext);
    if (context == null) {
        throw new Error('useNats must be used within a NatsProvider');
    }

    return context;
};

const NATS_SERVERS = {
    JETSON: 'ws://192.168.1.53:9222',
    LOCAL: 'ws://127.0.0.1:9222',
};

export const NatsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const query = useQuery({
        queryKey: ['nats'],
        queryFn: () => {
            L.info('Connecting to NATS server...');

            return wsconnect({
                servers: [NATS_SERVERS.JETSON],
                reconnect: true,
                maxReconnectAttempts: -1,
                waitOnFirstConnect: true,
                name: 'rabbit-web',
            });
        },
    });

    React.useEffect(() => {
        if (query.isError) {
            L.error('Failed to connect to NATS server', query.error);
        } else if (query.isSuccess) {
            L.info('Connected to NATS server');
        }
    }, [query]);

    if (query.data == null) {
        return <ui.SplashSpinner children='Connecting to NATS server...' />;
    }

    return <NatsContext.Provider value={query.data}>{children}</NatsContext.Provider>;
};

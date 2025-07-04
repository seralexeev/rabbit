import { type NatsConnection, wsconnect } from '@nats-io/nats-core';
import { useQuery } from '@tanstack/react-query';
import React from 'react';

const NatsContext = React.createContext<NatsConnection | null>(null);

export const useNats = () => {
    const context = React.useContext(NatsContext);
    if (context == null) {
        throw new Error('useNats must be used within a NatsProvider');
    }

    return context;
};

export const NatsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const query = useQuery({
        queryKey: ['nats'],
        queryFn: () => {
            return wsconnect({
                servers: ['ws://localhost:9222'],
                reconnect: true,
                maxReconnectAttempts: -1,
                waitOnFirstConnect: true,
            });
        },
    });

    if (query.data == null) {
        return <div>Connecting to NATS...</div>;
    }

    return <NatsContext.Provider value={query.data}>{children}</NatsContext.Provider>;
};

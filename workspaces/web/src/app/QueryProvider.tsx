import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            refetchOnWindowFocus: false,
        },
    },
});

type QueryProviderProps = {
    children: React.ReactNode;
};

export const QueryProvider: React.FC<QueryProviderProps> = React.memo(({ children }) => {
    return <QueryClientProvider client={queryClient} children={children} />;
});

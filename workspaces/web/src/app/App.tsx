import React from 'react';

import { GamepadProvider } from '../controller/GamepadProvider.tsx';
import { MainLayout } from '../layout/MainLayout.tsx';
import { LogProvider } from '../terminal/LogProvider.tsx';
import { NatsProvider } from './NatsProvider.tsx';
import { QueryProvider } from './QueryProvider.tsx';

export const App: React.FC = React.memo(() => {
    return (
        <React.StrictMode>
            <LogProvider>
                <QueryProvider>
                    <NatsProvider>
                        <GamepadProvider>
                            <MainLayout />
                        </GamepadProvider>
                    </NatsProvider>
                </QueryProvider>
            </LogProvider>
        </React.StrictMode>
    );
});

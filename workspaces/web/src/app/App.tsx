import { css } from '@emotion/css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { GamepadController } from './controller/GamepadController.tsx';
import { GamepadProvider } from './controller/GamepadProvider.tsx';
import { NatsProvider } from './realtime/NatsProvider.tsx';

const queryClient = new QueryClient();

export const App: React.FC = () => {
    return (
        <React.StrictMode>
            <QueryClientProvider client={queryClient}>
                <div
                    className={css`
                        width: 100%;
                        height: 100%;
                        display: flex;
                        flex-direction: column;
                    `}>
                    <NatsProvider>
                        <GamepadProvider>
                            <GamepadController />
                        </GamepadProvider>
                    </NatsProvider>
                </div>
            </QueryClientProvider>
        </React.StrictMode>
    );
};

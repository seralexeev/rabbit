import { css } from '@emotion/css';
import React from 'react';

import { GamepadController } from './controller/GamepadController.tsx';
import { GamepadProvider } from './controller/GamepadProvider.tsx';
import { WebSocketProvider } from './realtime/WebSocketProvider.tsx';

export const App: React.FC = () => {
    return (
        <div
            className={css`
                width: 100%;
                height: 100%;
                display: flex;
                flex-direction: column;
            `}>
            <WebSocketProvider>
                <GamepadProvider>
                    <GamepadController />
                </GamepadProvider>
            </WebSocketProvider>
        </div>
    );
};

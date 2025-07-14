import { css } from '@emotion/css';
import React from 'react';

import { CameraView } from '../camera/CameraView.tsx';
import { GamepadController } from '../controller/GamepadController.tsx';
import { GamepadProvider } from '../controller/GamepadProvider.tsx';
import { TelemetryBar } from '../telemetry/TelemetryBar.tsx';
import { LogProvider } from './LogProvider.tsx';
import { NatsProvider } from './NatsProvider.tsx';
import { QueryProvider } from './QueryProvider.tsx';

export const App: React.FC = React.memo(() => {
    return (
        <React.StrictMode>
            <LogProvider>
                <QueryProvider>
                    <NatsProvider>
                        <div
                            className={css`
                                padding: 8px;
                                width: 100%;
                                height: 100%;
                            `}>
                            <TelemetryBar />
                            <GamepadProvider>
                                {/* <GamepadController /> */}
                                {/* <CameraView /> */}
                            </GamepadProvider>
                        </div>
                    </NatsProvider>
                </QueryProvider>
            </LogProvider>
        </React.StrictMode>
    );
});

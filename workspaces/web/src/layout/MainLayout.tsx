import { css } from '@emotion/css';
import React from 'react';

import { useSubscribe } from '../app/NatsProvider.tsx';
import { CameraView } from '../camera/CameraView.tsx';
import { L } from '../terminal/LogProvider.tsx';
import { ui } from '../ui/index.ts';

export const MainLayout: React.FC = () => {
    useSubscribe('rabbit.camera.sensor', {
        callback: (msg) => {
            L.info('IMU data received', {
                subject: msg.subject,
                data: msg.json(),
            });
        },
    });

    return (
        <div
            className={css`
                padding: 8px;
                width: 100%;
                height: 100%;
                padding-top: 56px;
            `}>
            <div
                className={css`
                    display: flex;
                    flex-direction: row;
                    gap: 8px;
                    width: 100%;
                    height: 100%;
                `}>
                <div
                    className={css`
                        width: 300px;
                        flex-shrink: 0;
                    `}>
                    <ui.Card header='TELEMETRY'>...</ui.Card>
                </div>
                <div
                    className={css`
                        width: 100%;
                        flex: 1;
                    `}>
                    <CameraView />
                </div>
            </div>
        </div>
    );
};

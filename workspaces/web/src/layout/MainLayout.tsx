import { css } from '@emotion/css';
import React from 'react';

import { CameraView } from '../camera/CameraView.tsx';
import { GamepadController } from '../controller/GamepadController.tsx';
import { ui } from '../ui/index.ts';

export const MainLayout: React.FC = () => {
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
                    overflow: hidden;
                `}>
                <div
                    className={css`
                        width: 300px;
                        flex-shrink: 0;
                        height: 100%;
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                    `}>
                    <div
                        className={css`
                            flex: 1;
                        `}>
                        <ui.Card header='TELEMETRY'>...</ui.Card>
                    </div>
                    <div
                        className={css`
                            flex: 1;
                        `}>
                        <ui.Card header='CONTROLLER'>
                            <GamepadController />
                        </ui.Card>
                    </div>
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

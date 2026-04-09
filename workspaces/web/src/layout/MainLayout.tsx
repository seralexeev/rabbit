import { css } from '@emotion/css';
import React from 'react';

import { CameraView } from '../camera/CameraView.tsx';
import { GamepadController } from '../controller/GamepadController.tsx';
import { PointCloud } from '../perception/PointCloud.tsx';
import { ui } from '../ui/index.ts';
import { Sidebar } from './Sidebar.tsx';

export const MainLayout: React.FC = () => {
    return (
        <div
            className={css`
                padding: 8px;
                width: 100%;
                height: 100%;
                padding-top: 56px;
                display: flex;
                gap: 8px;
            `}>
            <div
                className={css`
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    flex: 1;
                    height: 100%;
                    overflow: hidden;
                    min-width: 0;
                    flex-shrink: 1;
                `}>
                <div
                    className={css`
                        display: flex;
                        gap: 8px;
                        flex: 0 0 auto;
                        min-height: 180px;
                        max-height: 30%;
                    `}>
                    <div
                        className={css`
                            flex: 1;
                            min-width: 0;
                        `}>
                        <CameraView subject='rabbit.zed.frame' />
                    </div>
                    <div
                        className={css`
                            flex: 0 0 auto;
                            display: flex;
                            align-items: stretch;
                        `}>
                        <ui.Card header='GAMEPAD'>
                            <div
                                className={css`
                                    padding: 16px;
                                    display: flex;
                                    align-items: center;
                                    height: 100%;
                                `}>
                                <GamepadController />
                            </div>
                        </ui.Card>
                    </div>
                </div>
                <div
                    className={css`
                        width: 100%;
                        flex: 1 1 0;
                        min-height: 0;
                    `}>
                    <ui.Card header='PERCEPTION'>
                        <PointCloud />
                    </ui.Card>
                </div>
            </div>
            <Sidebar />
        </div>
    );
};

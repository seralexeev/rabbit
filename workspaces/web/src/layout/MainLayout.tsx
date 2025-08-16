import { css } from '@emotion/css';
import React from 'react';

import { CameraSettings } from '../camera/CameraSettings.tsx';
import { CameraView } from '../camera/CameraView.tsx';
import { SpatialMapping } from '../perception/SpatialMapping.tsx';
import { ui } from '../ui/index.ts';

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
                    width: 400px;
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    height: 100%;
                `}>
                <ui.Card header='CONTROLLER'>
                    <CameraSettings />
                    {/* <GamepadController /> */}
                </ui.Card>
                <ui.Card header='CAMERA SETTINGS'>
                    <CameraSettings />
                </ui.Card>
            </div>
            <div
                className={css`
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    flex: 1;
                    width: 100%;
                    height: 100%;
                    overflow: hidden;
                `}>
                <div
                    className={css`
                        width: 100%;
                        flex: 1;
                    `}>
                    <CameraView subject='rabbit.zed.depth' />
                </div>

                <div
                    className={css`
                        width: 100%;
                        flex: 1;
                    `}>
                    <ui.Card header='PERCEPTION'>
                        <SpatialMapping />
                    </ui.Card>
                </div>
            </div>
        </div>
    );
};

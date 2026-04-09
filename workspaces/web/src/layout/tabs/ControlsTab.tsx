import { css } from '@emotion/css';
import React from 'react';

import { CameraSettings } from '../../camera/CameraSettings.tsx';
import { ui } from '../../ui/index.ts';

export const ControlsTab: React.FC = () => {
    return (
        <div
            className={css`
                display: flex;
                flex-direction: column;
                gap: 8px;
                padding: 8px;
            `}>
            <ui.Card header='CAMERA'>
                <CameraSettings />
            </ui.Card>
        </div>
    );
};

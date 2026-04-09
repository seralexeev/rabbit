import { css } from '@emotion/css';
import React from 'react';

import { TelemetryBar } from '../../telemetry/TelemetryBar.tsx';
import { ui } from '../../ui/index.ts';

export const SysTab: React.FC = () => {
    return (
        <div
            className={css`
                display: flex;
                flex-direction: column;
                gap: 8px;
                padding: 8px;
            `}>
            <ui.Card header='SYSTEM'>
                <div
                    className={css`
                        padding: 12px;
                    `}>
                    <TelemetryBar />
                </div>
            </ui.Card>
        </div>
    );
};

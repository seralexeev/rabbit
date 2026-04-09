import { css } from '@emotion/css';
import React from 'react';

import { NodeHealthBar } from '../../telemetry/NodeHealthBar.tsx';
import { TelemetryBar } from '../../telemetry/TelemetryBar.tsx';
import { ui } from '../../ui/index.ts';

export const StatsTab: React.FC = () => {
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
            <ui.Card header='NODES'>
                <div
                    className={css`
                        padding: 12px;
                    `}>
                    <NodeHealthBar />
                </div>
            </ui.Card>
        </div>
    );
};

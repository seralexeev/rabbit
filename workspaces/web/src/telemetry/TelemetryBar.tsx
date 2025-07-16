import { css } from '@emotion/css';
import React from 'react';

type TelemetryBarProps = {};

export const TelemetryBar: React.FC<TelemetryBarProps> = ({}) => {
    return (
        <div
            className={css`
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: space-between;
            `}>
            TELEMETRY
            <div
                className={css`
                    display: flex;
                    gap: 16px;
                    align-items: center;
                `}>
                <div>FPS:60</div>
                <div>RAM:2.5/8GB</div>
                <div>NET:1.2MB/s</div>
                <div>DSK:200MB/s</div>
                <div>CPU:12%</div>
                <div>TMP:75C</div>
                <div>BAT:84%</div>
            </div>
        </div>
    );
};

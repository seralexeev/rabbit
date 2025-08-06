import { css } from '@emotion/css';
import { byte } from '@untype/toolbox';
import React from 'react';

import { ui } from '../ui/index.ts';
import { CameraSettings } from './CameraSettings.tsx';
import { useCameraStream } from './useCamera.tsx';

export const CameraView: React.FC = () => {
    const { canvas, stats } = useCameraStream();

    const getHeader = () => {
        if (stats == null) {
            return `VIDEO STREAM`;
        }

        return (
            <div
                className={css`
                    width: 100%;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    overflow-x: auto;
                `}>
                VIDEO STREAM
                <div
                    className={css`
                        display: flex;
                        gap: 16px;
                        align-items: center;
                        font-variant-numeric: tabular-nums;
                    `}>
                    <div>{byte.prettify(stats.throughput, { whitespace: false })}/s</div>
                    <div>{byte.prettify(stats.bytes, { whitespace: false })}</div>
                    <div>{byte.prettify(stats.frameSize, { whitespace: false })}</div>
                    <div>
                        {stats.width}x{stats.height}@{stats.fps}
                    </div>
                    <div>{stats.type}</div>
                </div>
            </div>
        );
    };

    return (
        <div
            className={css`
                display: flex;
                width: 100%;
                height: 100%;
            `}>
            <ui.Card header={getHeader()}>
                {stats != null ? (
                    <div
                        className={css`
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            width: 100%;
                            height: 100%;
                        `}>
                        <canvas
                            className={css`
                                max-width: 100%;
                                max-height: 100%;
                            `}
                            ref={canvas}
                        />
                    </div>
                ) : (
                    <ui.SplashSpinner />
                )}
            </ui.Card>
        </div>
    );
};

import { css } from '@emotion/css';
import React from 'react';

import { useCameraStream } from './useCamera.tsx';

const UNITS = ['B', 'KB', 'MB', 'GB'];

const formatBytes = (bytes: number) => {
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < UNITS.length - 1) {
        value /= 1024;
        unit++;
    }
    return `${value.toFixed(unit === 0 ? 0 : 1)}${UNITS[unit]}`;
};

export const VideoFeed: React.FC<{ subject: string; objects?: string }> = ({ subject, objects }) => {
    const { canvas, stats } = useCameraStream({ subject, objects });
    const live = stats?.live === true;

    return (
        <div className={frameCss}>
            <canvas ref={canvas} className={canvasCss} />
            <div className={statsCss}>
                {stats == null || !live ? null : (
                    <>
                        <span>{`${stats.width}x${stats.height}@${stats.fps}`}</span>
                        <span>{`${formatBytes(stats.throughput)}/s`}</span>
                        <span>{formatBytes(stats.frameSize)}</span>
                    </>
                )}
            </div>
            <span className={recCss} data-live={live}>
                {live ? '● LIVE' : '○ NO SIGNAL'}
            </span>
        </div>
    );
};

const frameCss = css`
    position: relative;
    aspect-ratio: 16 / 9;
    margin-bottom: 6px;
    background: #000;
    border: 1px solid var(--hud-faint);
    overflow: hidden;
`;

const canvasCss = css`
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
`;

const statsCss = css`
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    justify-content: space-between;
    padding: 1px 4px;
    font-size: 8px;
    background: linear-gradient(0deg, rgba(0, 0, 0, 0.7), transparent);
    text-transform: none;
`;

const recCss = css`
    position: absolute;
    top: 3px;
    left: 3px;
    padding: 0 4px;
    font-size: 8px;
    background: rgba(0, 0, 0, 0.7);
    color: var(--hud-alert);
    text-shadow: 0 0 4px rgba(255, 90, 74, 0.6);

    &[data-live='false'] {
        color: var(--hud-amber);
        text-shadow: none;
    }
`;

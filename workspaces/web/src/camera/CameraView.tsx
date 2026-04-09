import { css } from '@emotion/css';
import { byte } from '@untype/toolbox';
import React from 'react';

import { useNats } from '../app/NatsProvider.tsx';
import { ui } from '../ui/index.ts';
import { useCameraStream } from './useCamera.tsx';

type ZedHealth = {
    frame_number: number;
    camera_fps: number;
    bundle_messages: number;
    bundle_bytes: number;
    preview_messages: number;
    preview_bytes: number;
    pose_messages: number;
    pose_drop_count: number;
    last_capture_duration_ms: number;
    last_pose_state: string;
};

function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}G`;
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)}K`;
    return `${bytes}B`;
}

type CameraViewProps = {
    subject: string;
};

export const CameraView: React.FC<CameraViewProps> = ({ subject }) => {
    const { nc } = useNats();
    const { canvas, stats } = useCameraStream({ subject });
    const [zed, setZed] = React.useState<ZedHealth | null>(null);

    React.useEffect(() => {
        const sub = nc.subscribe('rabbit.health.zed', {
            callback: (_, msg) => {
                try { setZed(msg.json() as ZedHealth); } catch {}
            },
        });
        return () => { sub.unsubscribe(); };
    }, [nc]);

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
                            position: relative;
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
                        {zed && (
                            <div
                                className={css`
                                    position: absolute;
                                    left: 8px;
                                    bottom: 8px;
                                    background: rgba(0, 0, 0, 0.7);
                                    border: 1px solid rgba(0, 255, 65, 0.15);
                                    border-radius: 4px;
                                    padding: 6px 10px;
                                    font-size: 10px;
                                    font-variant-numeric: tabular-nums;
                                    display: flex;
                                    flex-direction: column;
                                    gap: 2px;
                                    pointer-events: none;
                                `}>
                                <OverlayRow label='FRAME' value={`#${zed.frame_number}`} />
                                <OverlayRow label='CAPTURE' value={`${zed.last_capture_duration_ms.toFixed(1)}ms`} warn={zed.last_capture_duration_ms > 50} />
                                <OverlayRow label='POSE' value={zed.last_pose_state.replace('POSITIONAL_TRACKING_STATE.', '')} ok={zed.last_pose_state.includes('OK')} />
                                <OverlayRow label='POSE DROP' value={`${zed.pose_drop_count}`} warn={zed.pose_drop_count > 0} />
                                <OverlayRow label='BUNDLES' value={`${zed.bundle_messages}`} />
                                <OverlayRow label='BUNDLE BW' value={formatSize(zed.bundle_bytes)} />
                                <OverlayRow label='PREVIEW' value={`${zed.preview_messages} / ${formatSize(zed.preview_bytes)}`} />
                            </div>
                        )}
                    </div>
                ) : (
                    <ui.SplashSpinner />
                )}
            </ui.Card>
        </div>
    );
};

const OverlayRow: React.FC<{ label: string; value: string; warn?: boolean; ok?: boolean }> = ({ label, value, warn, ok }) => (
    <div
        className={css`
            display: flex;
            justify-content: space-between;
            gap: 12px;
        `}>
        <span className={css`opacity: 0.5;`}>{label}</span>
        <span
            className={css`
                color: ${warn ? '#ff5533' : ok ? '#00ff41' : 'inherit'};
                ${warn ? 'text-shadow: 0 0 6px #ff553344;' : ''}
                ${ok ? 'text-shadow: 0 0 6px #00ff4144;' : ''}
            `}>
            {value}
        </span>
    </div>
);

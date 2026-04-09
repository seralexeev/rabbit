import { css } from '@emotion/css';
import React from 'react';

import { useNats } from '../app/NatsProvider.tsx';
import { ui } from '../ui/index.ts';

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

export const ZedHealthPanel: React.FC = () => {
    const { nc } = useNats();
    const [zed, setZed] = React.useState<ZedHealth | null>(null);

    React.useEffect(() => {
        const sub = nc.subscribe('rabbit.health.zed', {
            callback: (_, msg) => {
                try { setZed(msg.json() as ZedHealth); } catch {}
            },
        });
        return () => { sub.unsubscribe(); };
    }, [nc]);

    return (
        <div
            className={css`
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 3px;
                font-variant-numeric: tabular-nums;
            `}>
            {zed == null ? (
                <ui.Placeholder label='OFFLINE' />
            ) : (
                <>
                    <Row label='FRAME' value={`#${zed.frame_number}`} />
                    <Row label='CAPTURE' value={`${zed.last_capture_duration_ms.toFixed(1)}ms`} warn={zed.last_capture_duration_ms > 50} />
                    <Row label='POSE' value={zed.last_pose_state.replace('POSITIONAL_TRACKING_STATE.', '')} ok={zed.last_pose_state.includes('OK')} />
                    <Row label='POSE TX' value={`${zed.pose_messages}`} />
                    <Row label='POSE DROP' value={`${zed.pose_drop_count}`} warn={zed.pose_drop_count > 0} />
                    <Row label='BUNDLES' value={`${zed.bundle_messages}`} />
                    <Row label='BUNDLE BW' value={formatSize(zed.bundle_bytes)} />
                    <Row label='PREVIEW' value={`${zed.preview_messages} / ${formatSize(zed.preview_bytes)}`} />
                </>
            )}
        </div>
    );
};

const Row: React.FC<{ label: string; value: string; warn?: boolean; ok?: boolean }> = ({ label, value, warn, ok }) => (
    <div
        className={css`
            display: flex;
            justify-content: space-between;
            font-size: 11px;
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

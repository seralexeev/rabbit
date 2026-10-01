import { css, cx } from '@emotion/css';
import React from 'react';

import { useSubjectState } from '../../app/NatsProvider.tsx';
import { CameraSettings } from '../../camera/CameraSettings.tsx';
import { VideoFeed } from '../../camera/VideoFeed.tsx';
import { ui } from '../../ui/index.ts';
import { HudPanel } from '../HudPanel.tsx';
import { fixed, sectionCss, toneCss } from '../fields.ts';
import { useStale } from '../useStale.ts';

const HEALTH_INTERVAL_MS = 1000;
const STALE_MS = 3500;

type ZedHealth = {
    frame_number: number;
    current_fps: number;
    camera_fps: number;
    last_capture_duration_ms: number;
    last_pose_state: string;
    pose_drop_count: number;
    frames_dropped?: number;
    odometry_status?: string;
    spatial_memory_status?: string;
    tracking_fusion_status?: string;
    low_image_quality?: boolean;
    low_lighting?: boolean;
    low_depth_reliability?: boolean;
    low_motion_sensors_reliability?: boolean;
    exposure?: number;
    gain?: number;
    whitebalance_temperature?: number;
    camera_moving_state?: string;
    temperature?: Record<string, number>;
    mapping_state: string;
    map_points: number;
    map_chunks: number;
    map_bytes: number;
};

const FLAGS = [
    ['low_image_quality', 'IMG'],
    ['low_lighting', 'LIGHT'],
    ['low_depth_reliability', 'DEPTH'],
    ['low_motion_sensors_reliability', 'IMU'],
] as const;

const formatSize = (bytes: number) => {
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}G`;
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
    return `${(bytes / 1024).toFixed(0)}K`;
};

const BAD_STATUSES = new Set(['OFF', 'LOST', 'SEARCHING', 'INITIALIZING', 'UNAVAILABLE']);

const isOk = (status: string | undefined) => status == null || !BAD_STATUSES.has(status);

export const ZedPanel: React.FC = () => {
    const zed = useSubjectState('rabbit.health.zed', (msg) => msg.json() as ZedHealth, HEALTH_INTERVAL_MS);
    const live = useStale(zed, STALE_MS);
    const [settingsOpen, setSettingsOpen] = React.useState(false);

    return (
        <HudPanel
            id='zed'
            code='ZD'
            title='ZED // VISION'
            live={live}
            detail={
                <div className={detailCss}>
                    <VideoFeed subject='rabbit.zed.frame.preview' />
                    <div>
                        <div className={sectionCss}>HEALTH</div>
                        <div className={gridCss}>
                            {zed == null ? (
                                <ui.Placeholder label='WAITING FOR CAMERA' />
                            ) : (
                                Object.entries(zed).map(([key, value]) => (
                                    <Pair
                                        key={key}
                                        label={key.replace(/_/g, ' ')}
                                        value={
                                            typeof value === 'object' && value != null ? JSON.stringify(value) : String(value)
                                        }
                                    />
                                ))
                            )}
                        </div>
                        <div className={sectionCss}>CAMERA SETTINGS</div>
                        <CameraSettings />
                    </div>
                </div>
            }>
            <VideoFeed subject='rabbit.zed.frame.preview' />
            {zed == null ? (
                <ui.Placeholder label='WAITING FOR CAMERA' />
            ) : (
                <>
                    <div className={gridCss}>
                        <Pair
                            label='FPS'
                            value={`${fixed(zed.current_fps, 1)}/${fixed(zed.camera_fps, 0)}`}
                            warn={zed.current_fps < zed.camera_fps * 0.8}
                        />
                        <Pair
                            label='CAP'
                            value={fixed(zed.last_capture_duration_ms, 1, 'ms')}
                            warn={zed.last_capture_duration_ms > 30}
                        />
                        <Pair label='POSE' value={zed.last_pose_state} warn={zed.last_pose_state !== 'OK'} />
                        <Pair
                            label='DROP'
                            value={`${zed.pose_drop_count}/${zed.frames_dropped ?? 0}`}
                            warn={zed.pose_drop_count > 0}
                        />
                        <Pair label='ODOM' value={zed.odometry_status ?? '—'} warn={!isOk(zed.odometry_status)} />
                        <Pair label='SMEM' value={zed.spatial_memory_status ?? '—'} warn={!isOk(zed.spatial_memory_status)} />
                        <Pair label='FUSE' value={zed.tracking_fusion_status ?? '—'} />
                        <Pair label='MOVE' value={zed.camera_moving_state ?? '—'} />
                        <Pair label='EXP' value={`${zed.exposure ?? '—'}`} />
                        <Pair label='GAIN' value={`${zed.gain ?? '—'}`} />
                        <Pair label='WB' value={`${zed.whitebalance_temperature ?? '—'}K`} />
                        {Object.entries(zed.temperature ?? {}).map(([name, value]) => (
                            <Pair
                                key={name}
                                label={name.replace('onboard_', '').slice(0, 5)}
                                value={fixed(value, 1, '°')}
                                warn={value > 65}
                            />
                        ))}
                    </div>
                    <div className={flagsCss}>
                        {FLAGS.map(([key, label]) => (
                            <span key={key} className={cx(flagCss, toneCss)} data-tone={zed[key] === true ? 'warn' : 'normal'}>
                                {zed[key] === true ? `LOW ${label}` : `${label} OK`}
                            </span>
                        ))}
                    </div>
                    <div className={sectionCss}>SPATIAL MAP</div>
                    <div className={gridCss}>
                        <Pair label='MAP' value={zed.mapping_state} warn={zed.mapping_state !== 'OK'} />
                        <Pair label='PTS' value={zed.map_points?.toLocaleString() ?? '—'} />
                        <Pair label='CHNK' value={zed.map_chunks?.toLocaleString() ?? '—'} />
                        <Pair label='TX' value={formatSize(zed.map_bytes)} />
                    </div>
                </>
            )}
            <button className={settingsButtonCss} onClick={() => setSettingsOpen((open) => !open)}>
                {settingsOpen ? '▾ CAMERA SETTINGS' : '▸ CAMERA SETTINGS'}
            </button>
            {settingsOpen && <CameraSettings />}
        </HudPanel>
    );
};

const Pair: React.FC<{ label: string; value: string; warn?: boolean }> = ({ label, value, warn }) => (
    <div className={pairCss}>
        <span>{label}</span>
        <span className={toneCss} data-tone={warn === true ? 'warn' : 'normal'}>
            {value}
        </span>
    </div>
);

const detailCss = css`
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
    gap: 14px;
    align-items: start;
`;

const gridCss = css`
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 10px;
`;

const pairCss = css`
    display: flex;
    justify-content: space-between;
    gap: 4px;
    font-size: 9px;
    line-height: 13px;
    white-space: nowrap;
    overflow: hidden;

    & > span:first-child {
        opacity: 0.55;
    }
`;

const flagsCss = css`
    display: flex;
    gap: 4px;
    margin-top: 4px;
`;

const flagCss = css`
    flex: 1;
    padding: 0 2px;
    font-size: 8px;
    text-align: center;
    border: 1px solid var(--hud-faint);

    &[data-tone='warn'] {
        border-color: var(--hud-amber);
    }
`;

const settingsButtonCss = css`
    margin-top: 6px;
    padding: 2px 0;
    border: none;
    border-top: 1px solid var(--hud-faint);
    background: none;
    color: inherit;
    font: inherit;
    letter-spacing: inherit;
    text-align: left;
    cursor: pointer;
    opacity: 0.7;

    &:hover {
        opacity: 1;
    }
`;

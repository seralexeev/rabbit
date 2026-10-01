import { css } from '@emotion/css';
import type { KV } from '@nats-io/kv';
import React from 'react';
import z from 'zod';

import { useNats } from '../app/NatsProvider.tsx';
import { L } from '../log.ts';
import { ui } from '../ui/index.ts';

const KEY = 'rabbit.zed.camera_settings';
const WRITE_DELAY_MS = 300;

type Sync = { revision: number; own: Set<number>; pending: VideoSettings | null; timer: number };

const watchSettings = (kv: KV, sync: Sync, onRemote: (settings: VideoSettings) => void) => {
    const watcher = kv.watch({ key: KEY });
    void (async () => {
        for await (const entry of await watcher) {
            sync.revision = Math.max(sync.revision, entry.revision);
            if (sync.own.delete(entry.revision) || sync.pending != null) continue;
            try {
                onRemote(VideoSettings.parse(entry.json()));
            } catch (error) {
                L.error('Invalid camera settings in KV', error);
            }
        }
    })().catch((error) => L.error('Camera settings watch failed', error));
    return () => {
        window.clearTimeout(sync.timer);
        void watcher.then((w) => w.stop());
    };
};

const writeSettings = async (kv: KV, sync: Sync, onReload: (settings: VideoSettings) => void) => {
    const next = sync.pending;
    if (next == null) return;
    try {
        const revision = await kv.update(KEY, JSON.stringify(next), sync.revision);
        sync.own.add(revision);
        sync.revision = revision;
    } catch (error) {
        L.warn('Camera settings changed elsewhere; reloading', error);
        const entry = await kv.get(KEY).catch(() => null);
        if (entry != null) {
            sync.revision = entry.revision;
            onReload(VideoSettings.parse(entry.json()));
        }
    }
    if (sync.pending === next) sync.pending = null;
};

const useCameraSettings = () => {
    const { kv } = useNats();
    const [settings, setSettings] = React.useState<VideoSettings | null>(null);
    const sync = React.useRef<Sync>({ revision: 0, own: new Set(), pending: null, timer: 0 });

    React.useEffect(() => watchSettings(kv, sync.current, setSettings), [kv]);

    const change = (key: keyof VideoSettings, value: number) => {
        if (settings == null) return;
        const next = { ...settings, [key]: value };
        const state = sync.current;
        state.pending = next;
        window.clearTimeout(state.timer);
        state.timer = window.setTimeout(() => void writeSettings(kv, state, setSettings), WRITE_DELAY_MS);
        setSettings(next);
    };

    return [settings, change] as const;
};

export const CameraSettings: React.FC = () => {
    const [settings, updateSetting] = useCameraSettings();

    if (settings == null) {
        return <ui.Placeholder label='WAITING FOR CAMERA' />;
    }

    return (
        <div
            className={css`
                display: flex;
                flex-direction: column;
                gap: 6px;
                padding: 4px 0 2px;
            `}>
            <Range
                label='BRIGHTNESS'
                value={settings.BRIGHTNESS}
                min={0}
                max={8}
                onChange={(value) => updateSetting('BRIGHTNESS', value)}
            />
            <Range
                label='CONTRAST'
                value={settings.CONTRAST}
                min={0}
                max={8}
                onChange={(value) => updateSetting('CONTRAST', value)}
            />
            <Range label='HUE' value={settings.HUE} min={0} max={11} onChange={(value) => updateSetting('HUE', value)} />
            <Range
                label='SATURATION'
                value={settings.SATURATION}
                min={0}
                max={8}
                onChange={(value) => updateSetting('SATURATION', value)}
            />
            <Range
                label='SHARPNESS'
                value={settings.SHARPNESS}
                min={0}
                max={8}
                onChange={(value) => updateSetting('SHARPNESS', value)}
            />
            <Range label='GAMMA' value={settings.GAMMA} min={1} max={9} onChange={(value) => updateSetting('GAMMA', value)} />
            <Range
                label='AUTO EXPOSURE'
                value={settings.AEC_AGC}
                min={0}
                max={1}
                onChange={(value) => updateSetting('AEC_AGC', value)}
            />
            {settings.AEC_AGC === 0 && (
                <>
                    <Range
                        label='GAIN'
                        value={settings.GAIN}
                        min={0}
                        max={100}
                        onChange={(value) => updateSetting('GAIN', value)}
                    />
                    <Range
                        label='EXPOSURE'
                        value={settings.EXPOSURE}
                        min={0}
                        max={100}
                        onChange={(value) => updateSetting('EXPOSURE', value)}
                    />
                </>
            )}
            <Range
                label='WHITEBALANCE AUTO'
                value={settings.WHITEBALANCE_AUTO}
                min={0}
                max={1}
                onChange={(value) => updateSetting('WHITEBALANCE_AUTO', value)}
            />
            {settings.WHITEBALANCE_AUTO === 0 && (
                <Range
                    label='WHITEBALANCE TEMPERATURE'
                    value={settings.WHITEBALANCE_TEMPERATURE}
                    min={2800}
                    max={6500}
                    step={100}
                    onChange={(value) => updateSetting('WHITEBALANCE_TEMPERATURE', value)}
                />
            )}
        </div>
    );
};

const Range: React.FC<{
    label: string;
    value: number;
    min: number;
    max: number;
    step?: number;
    onChange: (value: number) => void;
}> = ({ label, value, min, max, step = 1, onChange }) => {
    return (
        <div
            className={css`
                display: flex;
                flex-direction: column;
                gap: 4px;
            `}>
            <label>{label}</label>
            <input
                className={css`
                    width: 100%;

                    -webkit-appearance: none;
                    width: 100%;
                    height: 17px;
                    background: transparent;
                    cursor: pointer;

                    ::-webkit-slider-runnable-track {
                        height: 1px;
                        background: var(--color-primary);
                        border-radius: 0;
                    }

                    ::-webkit-slider-thumb {
                        -webkit-appearance: none;
                        height: 17px;
                        width: 8px;
                        background: var(--color-primary);
                        margin-top: -8px;
                    }
                `}
                type='range'
                min={min}
                max={max}
                value={value}
                step={step}
                onChange={(e) => {
                    const parsed = z.coerce.number().min(min).max(max).safeParse(e.target.value);
                    if (parsed.success) {
                        onChange(parsed.data);
                    }
                }}
            />
        </div>
    );
};

type VideoSettings = z.infer<typeof VideoSettings>;
const VideoSettings = z.object({
    BRIGHTNESS: z.number().min(0).max(8),
    CONTRAST: z.number().min(0).max(8),
    HUE: z.number().min(0).max(11),
    SATURATION: z.number().min(0).max(8),
    SHARPNESS: z.number().min(0).max(8),
    GAMMA: z.number().min(1).max(9),
    AEC_AGC: z.number().min(0).max(1).default(1),
    GAIN: z.number().min(0).max(100),
    EXPOSURE: z.number().min(0).max(100),
    WHITEBALANCE_TEMPERATURE: z.number().min(2800).max(6500),
    WHITEBALANCE_AUTO: z.number().min(0).max(1),
});

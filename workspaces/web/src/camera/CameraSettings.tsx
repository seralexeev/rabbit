import { css } from '@emotion/css';
import React from 'react';
import z from 'zod';

import { useNats } from '../app/NatsProvider.tsx';

type CameraSettingsProps = {};

export const CameraSettings: React.FC<CameraSettingsProps> = ({}) => {
    const { kv } = useNats();
    const [settings, setSettings] = React.useState<z.infer<typeof VideoSettings>>({
        BRIGHTNESS: -1,
        CONTRAST: -1,
        HUE: -1,
        SATURATION: -1,
        SHARPNESS: -1,
        GAMMA: -1,
        GAIN: -1,
        EXPOSURE: -1,
        WHITEBALANCE_TEMPERATURE: -1,
        WHITEBALANCE_AUTO: 1,
    });

    const updateSetting = async (key: keyof z.infer<typeof VideoSettings>, value: number) => {
        setSettings((prev) => ({ ...prev, [key]: value }));
        await kv.put('rabbit.zed.video_settings', JSON.stringify({ ...settings, [key]: value }));
    };

    React.useEffect(() => {
        (async () => {
            const watcher = await kv.watch({ key: 'rabbit.zed.video_settings' });
            for await (const entry of watcher) {
                const data = entry.value ? entry.json() : {};
                console.log('Received video settings:', data);
            }
        })();
    }, []);

    return (
        <div
            className={css`
                display: flex;
                flex-direction: column;
                gap: 8px;
                padding: 16px;
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
            <Range label='GAMMA' value={settings.GAMMA} min={1} max={8} onChange={(value) => updateSetting('GAMMA', value)} />
            <Range label='GAIN' value={settings.GAIN} min={0} max={100} onChange={(value) => updateSetting('GAIN', value)} />
            <Range
                label='EXPOSURE'
                value={settings.EXPOSURE}
                min={0}
                max={100}
                onChange={(value) => updateSetting('EXPOSURE', value)}
            />
            <Range
                label='WHITEBALANCE TEMPERATURE'
                value={settings.WHITEBALANCE_TEMPERATURE}
                min={2800}
                max={6500}
                onChange={(value) => updateSetting('WHITEBALANCE_TEMPERATURE', value)}
            />
            <Range
                label='WHITEBALANCE AUTO'
                value={settings.WHITEBALANCE_AUTO}
                min={0}
                max={1}
                onChange={(value) => updateSetting('WHITEBALANCE_AUTO', value)}
            />
        </div>
    );
};

const Range: React.FC<{
    label: string;
    value: number;
    min: number;
    max: number;
    onChange: (value: number) => void;
}> = ({ label, value, min, max, onChange }) => {
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
                `}
                type='range'
                min={min}
                max={max}
                value={value}
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

const VideoSettings = z.object({
    BRIGHTNESS: z.number().min(0).max(8),
    CONTRAST: z.number().min(0).max(8),
    HUE: z.number().min(0).max(11),
    SATURATION: z.number().min(0).max(8),
    SHARPNESS: z.number().min(0).max(8),
    GAMMA: z.number().min(1).max(8),
    GAIN: z.number().min(0).max(100),
    EXPOSURE: z.number().min(0).max(100),
    WHITEBALANCE_TEMPERATURE: z.number().min(2800).max(6500),
    WHITEBALANCE_AUTO: z.number().min(0).max(1),
});

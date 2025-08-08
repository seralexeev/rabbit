import { css } from '@emotion/css';
import React from 'react';
import z from 'zod';

import { useWatchNats } from '../app/NatsProvider.tsx';

type CameraSettingsProps = {};

export const CameraSettings: React.FC<CameraSettingsProps> = ({}) => {
    const [settings, setSettings] = useWatchNats({
        key: 'rabbit.zed.camera_settings',
        fn: (data) => VideoSettings.parse(data.json()),
    });

    const updateSetting = async (key: keyof VideoSettings, value: number) => {
        return setSettings((prev) => (prev ? { ...prev, [key]: value } : null));
    };

    if (settings == null) {
        return <div>Loading camera settings...</div>;
    }

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
                step={100}
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
    GAIN: z.number().min(0).max(100),
    EXPOSURE: z.number().min(0).max(100),
    WHITEBALANCE_TEMPERATURE: z.number().min(2800).max(6500),
    WHITEBALANCE_AUTO: z.number().min(0).max(1),
});

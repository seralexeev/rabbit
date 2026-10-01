import { css } from '@emotion/css';
import React from 'react';

import { isLive } from '../../perception/Telemetry.ts';
import { HistoryChart, type HistorySignals } from '../HistoryChart.tsx';
import { useHud, useHudFrame, useHudTick } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { Rows } from '../Rows.tsx';
import { detailGridCss } from '../detail.ts';
import { above, fixed, signed, useFields, writeText } from '../fields.ts';

const ROWS = [
    { label: 'X' },
    { label: 'Y' },
    { label: 'Z' },
    { label: 'HDG' },
    { label: 'MAG' },
    { label: 'SOG' },
    { label: 'ODO' },
    { label: 'P/R' },
    { label: 'G' },
    { label: 'BARO' },
    { label: 'CONF' },
] as const;

const NAV_CHARTS = {
    speed: [{ key: 'speed', label: 'SPEED', unit: 'm/s' }],
    attitude: [
        { key: 'pitch', label: 'PITCH', unit: '°' },
        { key: 'roll', label: 'ROLL', unit: '°' },
        { key: 'camera_height', label: 'CAMERA HEIGHT', unit: 'm', axis: 'right' },
    ],
    acceleration: [
        { key: 'lateral_g', label: 'LATERAL', unit: 'g' },
        { key: 'longitudinal_g', label: 'LONGITUDINAL', unit: 'g' },
        { key: 'g', label: 'TOTAL', unit: 'g', axis: 'right' },
    ],
    yaw: [{ key: 'yaw_rate_deg', label: 'YAW RATE', unit: '°/s' }],
} as const satisfies Record<string, HistorySignals>;

const ATTITUDE_PX_PER_DEG = 1.1;
const G_FULL_SCALE = 0.5;
const G_RADIUS = 24;
const LADDER = [-20, -10, 10, 20]
    .map((deg) => {
        const y = -deg * ATTITUDE_PX_PER_DEG;
        const half = deg % 20 === 0 ? 10 : 6;
        return `M${-half} ${y}H${half}`;
    })
    .join('');
const BEZEL = [-60, -30, 0, 30, 60]
    .map((deg) => {
        const a = ((deg - 90) * Math.PI) / 180;
        return `M${Math.cos(a) * 28} ${Math.sin(a) * 28}L${Math.cos(a) * 24} ${Math.sin(a) * 24}`;
    })
    .join('');

export const NavPanel: React.FC = () => {
    const { store } = useHud();
    const fields = useFields();
    const horizonRef = React.useRef<SVGGElement | null>(null);
    const dotRef = React.useRef<SVGCircleElement | null>(null);
    const clipId = `att-${React.useId().replace(/[^a-zA-Z0-9]/g, '')}`;
    const drawn = React.useRef({ attitude: '', dot: '' });

    useHudFrame(() => {
        const d = store.derived;
        const pitch = Math.round(((d.pitch * 180) / Math.PI) * ATTITUDE_PX_PER_DEG);
        const roll = Math.round((d.roll * 180) / Math.PI);
        const attitude = `rotate(${-roll}) translate(0 ${pitch})`;
        if (attitude !== drawn.current.attitude) {
            drawn.current.attitude = attitude;
            horizonRef.current?.setAttribute('transform', attitude);
        }

        const scale = G_RADIUS / G_FULL_SCALE;
        let x = d.lateralG * scale;
        let y = -d.longitudinalG * scale;
        const length = Math.hypot(x, y);
        if (length > G_RADIUS + 2) {
            x *= (G_RADIUS + 2) / length;
            y *= (G_RADIUS + 2) / length;
        }
        const dot = `translate(${Math.round(x)} ${Math.round(y)})`;
        if (dot !== drawn.current.dot) {
            drawn.current.dot = dot;
            dotRef.current?.setAttribute('transform', dot);
        }
    });

    useHudTick((now) => {
        const d = store.derived;
        const [x, y, z, heading, mag, sog, odo, attitude, g, baro, conf] = fields.current.values;
        if (d.hasPose) {
            writeText(x, signed(d.x, 2, ' m'));
            writeText(y, signed(d.y, 2, ' m'));
            writeText(z, signed(d.z, 2, ' m'));
            writeText(heading, fixed(d.heading, 1, '°'));
            writeText(sog, fixed(d.speed, 2, ' m/s'));
            writeText(odo, fixed(d.odometer, 1, ' m'));
            writeText(attitude, `${signed((d.pitch * 180) / Math.PI, 1)}/${signed((d.roll * 180) / Math.PI, 1, '°')}`);
        }
        if (isLive(store.imu, now)) writeText(g, fixed(d.g, 2, ' g'), above(Math.abs(d.g - 1), 0.3, 0.8));

        const magnetometer = store.magnetometer.value;
        if (magnetometer != null) {
            const ok = isLive(store.magnetometer, now) && magnetometer.heading_state === 'GOOD';
            writeText(mag, `${fixed(magnetometer.heading_deg, 0, '°')} ${magnetometer.heading_state}`, ok ? 'normal' : 'warn');
        }
        const barometer = store.barometer.value;
        if (barometer != null) writeText(baro, fixed(barometer.pressure_hpa, 1, ' hPa'));

        const pose = store.pose.value;
        if (pose?.confidence != null) {
            const std =
                pose.position_std == null ? '' : ` ±${fixed(Math.max(...pose.position_std.map((v) => v ?? 0)) * 100, 1, 'cm')}`;
            writeText(conf, `${pose.confidence}%${std}`, pose.confidence < 50 ? 'warn' : 'normal');
        }
    });

    return (
        <HudPanel
            id='nav'
            code='NV'
            title='NAV // POSE'
            source='pose'
            detail={
                <div className={detailGridCss}>
                    <HistoryChart title='SPEED OVER GROUND' signals={NAV_CHARTS.speed} />
                    <HistoryChart title='ATTITUDE / CAMERA HEIGHT' signals={NAV_CHARTS.attitude} />
                    <HistoryChart title='ACCELERATION' signals={NAV_CHARTS.acceleration} />
                    <HistoryChart title='YAW RATE' signals={NAV_CHARTS.yaw} />
                </div>
            }>
            <div className={bodyCss}>
                <div>
                    <Rows rows={ROWS} fields={fields} />
                </div>
                <div className={instrumentsCss}>
                    <svg width={60} height={60} viewBox='-30 -30 60 60'>
                        <defs>
                            <clipPath id={clipId}>
                                <circle r={27} />
                            </clipPath>
                        </defs>
                        <g clipPath={`url(#${clipId})`}>
                            <g ref={horizonRef}>
                                <rect className='ground' x={-80} y={0} width={160} height={120} />
                                <path className='horizon' d='M-80 0H80' />
                                <path className='ladder' d={LADDER} />
                            </g>
                        </g>
                        <circle className='frame' r={28} />
                        <path className='frame' d={BEZEL} />
                        <path className='symbol' d='M-14 0H-5L-2 4L0 0L2 4L5 0H14' />
                    </svg>
                    <svg width={60} height={60} viewBox='-30 -30 60 60'>
                        <circle className='frame' r={G_RADIUS + 4} />
                        <circle className='faint' r={G_RADIUS / 2} />
                        <circle className='faint' r={G_RADIUS} />
                        <path className='faint' d={`M${-G_RADIUS - 4} 0H${G_RADIUS + 4}M0 ${-G_RADIUS - 4}V${G_RADIUS + 4}`} />
                        <circle ref={dotRef} className='dot' r={2.5} />
                    </svg>
                </div>
            </div>
        </HudPanel>
    );
};

const bodyCss = css`
    display: grid;
    grid-template-columns: 1fr 60px;
    gap: 10px;
`;

const instrumentsCss = css`
    display: flex;
    flex-direction: column;
    gap: 8px;

    & svg {
        display: block;
        overflow: visible;
    }

    & .frame {
        fill: none;
        stroke: var(--hud-dim);
        stroke-width: 1;
    }

    & .faint {
        fill: none;
        stroke: var(--hud-faint);
        stroke-width: 1;
    }

    & .ladder {
        fill: none;
        stroke: var(--hud-dim);
        stroke-width: 1;
    }

    & .horizon {
        stroke: var(--hud);
        stroke-width: 1;
    }

    & .ground {
        fill: rgba(255, 181, 71, 0.14);
    }

    & .symbol {
        fill: none;
        stroke: var(--hud-amber);
        stroke-width: 1.5;
    }

    & .dot {
        fill: var(--hud-amber);
    }
`;

import { css, cx } from '@emotion/css';
import React from 'react';

import { isLive } from '../perception/Telemetry.ts';
import { useHud, useHudFrame } from './HudContext.ts';
import { frameCss } from './frame.ts';

const WIDTH = 300;
const HEIGHT = 30;
const PX_PER_DEG = 3;
const FROM = -180;
const TO = 540;
const STRIP_WIDTH = (TO - FROM) * PX_PER_DEG;
const NAMES: Record<number, string> = { 0: 'N', 45: 'NE', 90: 'E', 135: 'SE', 180: 'S', 225: 'SW', 270: 'W', 315: 'NW' };

const STEPS = Array.from({ length: (TO - FROM) / 5 + 1 }, (_, i) => FROM + i * 5);
const TICKS = STEPS.map((deg) => {
    const x = (deg - FROM) * PX_PER_DEG + 0.5;
    const norm = ((deg % 360) + 360) % 360;
    const size = norm % 45 === 0 ? 9 : norm % 15 === 0 ? 6 : 3;
    return `M${x} ${HEIGHT - size}V${HEIGHT}`;
}).join('');
const LABELS = STEPS.filter((deg) => (((deg % 360) + 360) % 360) % 15 === 0).map((deg) => {
    const norm = ((deg % 360) + 360) % 360;
    return { x: (deg - FROM) * PX_PER_DEG, label: NAMES[norm] ?? String(norm).padStart(3, '0') };
});

const shiftFor = (heading: number) => Math.round(WIDTH / 2 - ((((heading % 360) + 360) % 360) - FROM) * PX_PER_DEG);

export const Compass: React.FC = () => {
    const { store } = useHud();
    const stripRef = React.useRef<SVGSVGElement | null>(null);
    const magRef = React.useRef<HTMLDivElement | null>(null);
    const readoutRef = React.useRef<HTMLDivElement | null>(null);
    const drawn = React.useRef({ shift: Number.NaN, mag: Number.NaN, readout: -1 });

    useHudFrame((now) => {
        const heading = store.derived.heading;
        const shift = shiftFor(heading);
        if (shift !== drawn.current.shift) {
            drawn.current.shift = shift;
            if (stripRef.current != null) stripRef.current.style.transform = `translate3d(${shift}px, 0, 0)`;
        }

        const rounded = Math.round(heading) % 360;
        if (rounded !== drawn.current.readout && readoutRef.current != null) {
            drawn.current.readout = rounded;
            readoutRef.current.textContent = `${String(rounded).padStart(3, '0')}°`;
        }

        const magnetometer = isLive(store.magnetometer, now) ? store.magnetometer.value : null;
        const offset = magnetometer == null ? Number.NaN : ((540 - magnetometer.heading_deg) % 360) - 180;
        const mag =
            Math.abs(offset) * PX_PER_DEG > WIDTH / 2 || Number.isNaN(offset)
                ? Number.NaN
                : Math.round(WIDTH / 2 + offset * PX_PER_DEG);
        if (!Object.is(mag, drawn.current.mag) && magRef.current != null) {
            drawn.current.mag = mag;
            magRef.current.style.transform = Number.isNaN(mag) ? 'scale(0)' : `translate3d(${mag}px, 0, 0)`;
        }
    });

    return (
        <div className={rootCss}>
            <div className={tapeCss}>
                <svg ref={stripRef} width={STRIP_WIDTH} height={HEIGHT} viewBox={`0 0 ${STRIP_WIDTH} ${HEIGHT}`}>
                    <path d={TICKS} />
                    {LABELS.map(({ x, label }) => (
                        <text key={x} x={x} y={12}>
                            {label}
                        </text>
                    ))}
                </svg>
                <div ref={magRef} className={magCss} title='Magnetic north' />
            </div>
            <div className={caretCss} />
            <div ref={readoutRef} className={cx(frameCss, readoutCss)}>
                000°
            </div>
        </div>
    );
};

const rootCss = css`
    position: absolute;
    top: 6px;
    left: 50%;
    width: ${WIDTH}px;
    margin-left: ${-WIDTH / 2}px;
    pointer-events: none;
`;

const tapeCss = css`
    position: relative;
    height: ${HEIGHT}px;
    overflow: hidden;
    background: linear-gradient(180deg, rgba(3, 14, 20, 0.75), rgba(3, 14, 20, 0.35));
    mask-image: linear-gradient(90deg, transparent, #000 18%, #000 82%, transparent);
    text-shadow: 0 0 6px var(--hud-glow);

    & svg {
        position: absolute;
        left: 0;
        top: 0;
        will-change: transform;
    }

    & path {
        stroke: var(--hud);
        stroke-width: 1;
        stroke-opacity: 0.7;
    }

    & text {
        fill: var(--hud);
        font-size: 10px;
        font-weight: 600;
        font-family: inherit;
        text-anchor: middle;
    }
`;

const magCss = css`
    position: absolute;
    left: -4px;
    bottom: 0;
    width: 0;
    height: 0;
    border: 4px solid transparent;
    border-bottom: 6px solid var(--hud-amber);
    transform: scale(0);
`;

const caretCss = css`
    width: 0;
    height: 0;
    margin: 2px auto 0;
    border: 5px solid transparent;
    border-top: none;
    border-bottom-color: var(--hud);
`;

const readoutCss = css`
    width: 64px;
    margin: 1px auto 0;
    padding: 1px 0;
    text-align: center;
    font-size: 11px;
    font-weight: 600;
`;

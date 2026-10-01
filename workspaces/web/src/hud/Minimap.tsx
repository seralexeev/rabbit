import { css, cx } from '@emotion/css';
import React from 'react';

import { useLocalState } from '../hooks.ts';
import { TOP_ORIENTATIONS, type TopOrientation } from '../perception/CameraRig.ts';
import { isLive } from '../perception/Telemetry.ts';
import {
    type ArcPose,
    CAMERA_TO_REAR_AXLE,
    CENTERLINE_OFFSET,
    FOOTPRINT,
    curvatureForSteer,
    driveCommand,
    sweepPose,
} from '../perception/drive.ts';
import { type Waypoint, predictWaypoints, remainingMission } from '../perception/mission.ts';
import { useHud, useHudFrame } from './HudContext.ts';

const ORIENTATION_KEY = 'rabbit.minimap.orientation';
const DEFAULT_ZOOM = 45;
const MIN_ZOOM = 8;
const MAX_ZOOM = 320;
const ZOOM_STEP = 1.25;
const REDRAW_MS = 50;
const CLICK_SLOP_PX = 4;
const SCALE_TARGET_PX = 64;
const SCALE_STEPS = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 50];
const CORRIDOR_LENGTH = 1.2;
const CORRIDOR_SAMPLES = 24;
const MAX_WAYPOINTS = 64;
const SCAN_DOT_M = 0.025;
const STALE_MS = 1000;
const NAV_TIMEOUT_MS = 2000;
const EXPLORE_TIMEOUT_MS = 3000;
const REVERSE_COMMAND = -0.02;
const MISSION_MODES = new Set(['driving', 'maneuvering', 'blocked']);
const DEG = Math.PI / 180;
const HUD = '#62e8ff';
const AMBER = '#ffb547';
const ALERT = '#ff5a4a';
const PATH_DASH = [0.08, 0.05];
const TARGET_DASH = [0.05, 0.04];
const SOLID: number[] = [];

const scaleFor = (zoom: number) => {
    let meters = SCALE_STEPS[0]!;
    for (const step of SCALE_STEPS) if (step * zoom <= SCALE_TARGET_PX * 1.5) meters = step;
    return { meters, px: Math.round(meters * zoom), label: meters < 1 ? `${Math.round(meters * 100)} CM` : `${meters} M` };
};

type MinimapProps = {
    fill?: boolean;
    armed: boolean;
    onGoal: (point: { x: number; z: number }, append: boolean) => void;
};

export const Minimap: React.FC<MinimapProps> = ({ fill = false, armed, onGoal }) => {
    const { store, floorPlan } = useHud();
    const [orientation, setOrientation] = useLocalState<TopOrientation>(
        ORIENTATION_KEY,
        (raw) => TOP_ORIENTATIONS.find((item) => item.id === raw)?.id ?? 'north',
        'north',
    );
    const [zoom, setZoom] = React.useState(DEFAULT_ZOOM);
    const [panned, setPanned] = React.useState(false);
    const [empty, setEmpty] = React.useState(true);
    const containerRef = React.useRef<HTMLDivElement | null>(null);
    const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
    const northRef = React.useRef<HTMLDivElement | null>(null);

    const [view] = React.useState(() => ({
        zoom: DEFAULT_ZOOM,
        rotate: false,
        panX: 0,
        panZ: 0,
        version: 0,
        drawnVersion: -1,
        drawnAt: -Infinity,
        signature: new Float64Array(9),
        matrix: { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 },
        north: Number.NaN,
        waypoints: Array.from({ length: MAX_WAYPOINTS }, (): Waypoint => ({ x: 0, z: 0, marker: false })),
        waypointCount: 0,
        navVersion: -1,
        pose: { along: 0, across: 0, theta: 0 } as ArcPose,
        corridor: new Float64Array(CORRIDOR_SAMPLES * 4),
        drag: null as null | { id: number; x: number; y: number; moved: boolean },
    }));

    React.useEffect(() => {
        view.zoom = zoom;
        view.rotate = orientation === 'heading';
        view.version++;
    }, [view, zoom, orientation]);

    const markPanned = (next: boolean) => {
        if (next !== panned) setPanned(next);
    };

    const recenter = () => {
        view.panX = 0;
        view.panZ = 0;
        view.version++;
        markPanned(false);
    };

    React.useEffect(() => {
        const container = containerRef.current;
        const canvas = canvasRef.current;
        if (container == null || canvas == null) return;
        const resize = () => {
            const dpr = window.devicePixelRatio;
            const width = Math.max(1, Math.round(container.clientWidth * dpr));
            const height = Math.max(1, Math.round(container.clientHeight * dpr));
            if (canvas.width !== width || canvas.height !== height) {
                canvas.width = width;
                canvas.height = height;
                view.version++;
            }
        };
        resize();
        const observer = new ResizeObserver(resize);
        observer.observe(container);
        const onWheel = (event: WheelEvent) => {
            event.preventDefault();
            const factor = Math.exp(-event.deltaY * 0.0015);
            setZoom((value) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value * factor)));
        };
        canvas.addEventListener('wheel', onWheel, { passive: false });
        return () => {
            observer.disconnect();
            canvas.removeEventListener('wheel', onWheel);
        };
    }, [view]);

    const toWorld = (event: React.PointerEvent<HTMLCanvasElement>) => {
        const canvas = event.currentTarget;
        const rect = canvas.getBoundingClientRect();
        const px = ((event.clientX - rect.left) * canvas.width) / rect.width;
        const py = ((event.clientY - rect.top) * canvas.height) / rect.height;
        const { a, b, c, d, e, f } = view.matrix;
        const det = a * d - b * c;
        const dx = px - e;
        const dy = py - f;
        return { x: (d * dx - c * dy) / det, z: (-b * dx + a * dy) / det };
    };

    const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
        if (event.button !== 0) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        view.drag = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
    };

    const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
        const drag = view.drag;
        if (drag == null || drag.id !== event.pointerId) return;
        const dx = event.clientX - drag.x;
        const dy = event.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) < CLICK_SLOP_PX) return;
        drag.moved = true;
        drag.x = event.clientX;
        drag.y = event.clientY;
        const canvas = event.currentTarget;
        const ratio = canvas.width / canvas.getBoundingClientRect().width;
        const { a, b, c, d } = view.matrix;
        const det = a * d - b * c;
        view.panX -= (d * dx * ratio - c * dy * ratio) / det;
        view.panZ -= (-b * dx * ratio + a * dy * ratio) / det;
        view.version++;
        markPanned(true);
    };

    const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
        const drag = view.drag;
        if (drag == null || drag.id !== event.pointerId) return;
        view.drag = null;
        if (drag.moved || !armed) return;
        onGoal(toWorld(event), event.shiftKey);
    };

    useHudFrame((now) => {
        const canvas = canvasRef.current;
        const ctx = canvas?.getContext('2d');
        if (canvas == null || ctx == null) return;
        const d = store.derived;
        const signature = view.signature;
        const changed =
            signature[0] !== d.x ||
            signature[1] !== d.z ||
            signature[2] !== d.heading ||
            signature[3] !== floorPlan.version() ||
            signature[4] !== store.obstacle.version ||
            signature[5] !== store.nav.version ||
            signature[6] !== store.steering.version ||
            signature[7] !== store.explore.version ||
            signature[8] !== view.version;
        if (!changed || now - view.drawnAt < REDRAW_MS) return;
        signature[0] = d.x;
        signature[1] = d.z;
        signature[2] = d.heading;
        signature[3] = floorPlan.version();
        signature[4] = store.obstacle.version;
        signature[5] = store.nav.version;
        signature[6] = store.steering.version;
        signature[7] = store.explore.version;
        signature[8] = view.version;
        view.drawnAt = now;

        const raster = floorPlan.raster();
        const isEmpty = raster == null;
        if (isEmpty !== empty) setEmpty(isEmpty);

        const width = canvas.width;
        const height = canvas.height;
        const dpr = width / Math.max(canvas.clientWidth, 1);
        const scale = view.zoom * dpr;
        const heading = d.heading * DEG;
        const rotation = view.rotate ? -heading : 0;
        const cx = d.x + view.panX;
        const cz = d.z + view.panZ;
        const cos = Math.cos(rotation) * scale;
        const sin = Math.sin(rotation) * scale;
        const m = view.matrix;
        m.a = cos;
        m.b = sin;
        m.c = -sin;
        m.d = cos;
        m.e = width / 2 - (cos * cx - sin * cz);
        m.f = height / 2 - (sin * cx + cos * cz);

        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, width, height);
        ctx.setTransform(m.a, m.b, m.c, m.d, m.e, m.f);
        ctx.imageSmoothingEnabled = false;
        if (raster != null) ctx.drawImage(raster.canvas, raster.x, raster.z, raster.width, raster.height);

        const pixel = 1 / view.zoom;
        const fx = Math.sin(heading);
        const fz = -Math.cos(heading);
        const rx = -fz;
        const rz = fx;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';

        const nav = isLive(store.nav, now, NAV_TIMEOUT_MS) ? store.nav.value : null;
        if (nav == null) {
            view.waypointCount = 0;
        } else if (store.nav.version !== view.navVersion) {
            view.navVersion = store.nav.version;
            view.waypointCount = predictWaypoints(
                remainingMission(nav),
                { x: d.x, z: d.z, heading: d.heading },
                view.waypoints,
            );
        }
        const path = nav?.path ?? null;
        if (path != null && path.length > 1) {
            ctx.beginPath();
            for (let i = 0; i < path.length; i++) {
                const point = path[i]!;
                if (i === 0) ctx.moveTo(point[0], point[1]);
                else ctx.lineTo(point[0], point[1]);
            }
            ctx.setLineDash(PATH_DASH);
            ctx.strokeStyle = AMBER;
            ctx.globalAlpha = 0.85;
            ctx.lineWidth = 1.5 * pixel;
            ctx.stroke();
            ctx.setLineDash(SOLID);
        }
        if (view.waypointCount > 0) {
            ctx.beginPath();
            ctx.moveTo(d.x, d.z);
            for (let i = 0; i < view.waypointCount; i++) ctx.lineTo(view.waypoints[i]!.x, view.waypoints[i]!.z);
            ctx.setLineDash(PATH_DASH);
            ctx.strokeStyle = AMBER;
            ctx.globalAlpha = 0.55;
            ctx.lineWidth = pixel;
            ctx.stroke();
            ctx.setLineDash(SOLID);
            ctx.globalAlpha = 0.95;
            ctx.fillStyle = AMBER;
            const size = 3 * pixel;
            for (let i = 0; i < view.waypointCount; i++) {
                const waypoint = view.waypoints[i]!;
                if (!waypoint.marker) continue;
                ctx.beginPath();
                ctx.moveTo(waypoint.x, waypoint.z - size);
                ctx.lineTo(waypoint.x + size, waypoint.z);
                ctx.lineTo(waypoint.x, waypoint.z + size);
                ctx.lineTo(waypoint.x - size, waypoint.z);
                ctx.fill();
            }
        }
        if (nav?.goal != null) {
            ctx.globalAlpha = 1;
            ctx.strokeStyle = nav.mode === 'arrived' ? HUD : AMBER;
            ctx.lineWidth = 1.5 * pixel;
            ctx.beginPath();
            ctx.arc(nav.goal.x, nav.goal.z, Math.max(0.12, 6 * pixel), 0, Math.PI * 2);
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(nav.goal.x, nav.goal.z, 1.5 * pixel, 0, Math.PI * 2);
            ctx.fillStyle = ctx.strokeStyle;
            ctx.fill();
        }

        const explore = isLive(store.explore, now, EXPLORE_TIMEOUT_MS) ? store.explore.value : null;
        const target = explore?.target ?? null;
        if (target != null) {
            const radius = Math.max(0.2, 7 * pixel);
            ctx.globalAlpha = 0.9;
            ctx.strokeStyle = HUD;
            ctx.lineWidth = 1.25 * pixel;
            ctx.setLineDash(TARGET_DASH);
            ctx.beginPath();
            ctx.arc(target.x, target.z, radius, 0, Math.PI * 2);
            ctx.stroke();
            ctx.setLineDash(SOLID);
            ctx.beginPath();
            ctx.moveTo(target.x, target.z);
            ctx.lineTo(target.x + Math.cos(target.theta) * radius * 1.6, target.z + Math.sin(target.theta) * radius * 1.6);
            ctx.stroke();
        }

        const steering = isLive(store.steering, now) ? store.steering.value : null;
        const rearX = d.x + CENTERLINE_OFFSET * rx - CAMERA_TO_REAR_AXLE * fx;
        const rearZ = d.z + CENTERLINE_OFFSET * rz - CAMERA_TO_REAR_AXLE * fz;
        if (d.hasPose && steering != null) {
            const command = driveCommand(store, now);
            const direction = command < REVERSE_COMMAND ? -1 : 1;
            const curvature = curvatureForSteer(steering.angle ?? 0);
            const lead = direction > 0 ? FOOTPRINT.front : FOOTPRINT.rear;
            const points = view.corridor;
            for (let i = 0; i < CORRIDOR_SAMPLES; i++) {
                const u = (CORRIDOR_LENGTH * i) / (CORRIDOR_SAMPLES - 1);
                const pose = sweepPose(curvature, direction * u, view.pose);
                const forwardOffset = pose.along + direction * lead * Math.cos(pose.theta);
                const sideOffset = pose.across + direction * lead * Math.sin(pose.theta);
                const lx = -Math.sin(pose.theta);
                const ly = Math.cos(pose.theta);
                for (let side = 0; side < 2; side++) {
                    const offset = side === 0 ? -FOOTPRINT.halfWidth : FOOTPRINT.halfWidth;
                    const along = forwardOffset + lx * offset;
                    const across = sideOffset + ly * offset;
                    points[i * 4 + side * 2] = rearX + along * fx + across * rx;
                    points[i * 4 + side * 2 + 1] = rearZ + along * fz + across * rz;
                }
            }
            ctx.globalAlpha = nav != null && MISSION_MODES.has(nav.mode) ? 0.45 : 0.85;
            ctx.strokeStyle = HUD;
            ctx.lineWidth = 1.25 * pixel;
            for (let side = 0; side < 2; side++) {
                ctx.beginPath();
                for (let i = 0; i < CORRIDOR_SAMPLES; i++) {
                    const x = points[i * 4 + side * 2]!;
                    const z = points[i * 4 + side * 2 + 1]!;
                    if (i === 0) ctx.moveTo(x, z);
                    else ctx.lineTo(x, z);
                }
                ctx.stroke();
            }
        }

        const scan = isLive(store.obstacle, now, STALE_MS) ? (store.obstacle.value?.scan ?? null) : null;
        if (d.hasPose && scan != null) {
            ctx.globalAlpha = 0.95;
            ctx.fillStyle = ALERT;
            ctx.beginPath();
            const dot = Math.max(SCAN_DOT_M, 2 * pixel);
            for (let i = 0; i < scan.ranges.length; i++) {
                const range = scan.ranges[i];
                if (range == null) continue;
                const angle = (scan.angle_min_deg + (i + 0.5) * scan.angle_step_deg) * DEG;
                const along = range * Math.cos(angle);
                const across = range * Math.sin(angle) + CENTERLINE_OFFSET;
                ctx.rect(d.x + along * fx + across * rx - dot / 2, d.z + along * fz + across * rz - dot / 2, dot, dot);
            }
            ctx.fill();
        }

        if (d.hasPose) {
            ctx.save();
            ctx.translate(rearX, rearZ);
            ctx.rotate(heading);
            ctx.globalAlpha = 1;
            ctx.beginPath();
            ctx.rect(-FOOTPRINT.halfWidth, -FOOTPRINT.front, FOOTPRINT.halfWidth * 2, FOOTPRINT.front + FOOTPRINT.rear);
            ctx.fillStyle = 'rgba(98, 232, 255, 0.28)';
            ctx.fill();
            ctx.strokeStyle = HUD;
            ctx.lineWidth = 1.5 * pixel;
            ctx.stroke();
            ctx.beginPath();
            const tip = FOOTPRINT.front + Math.max(0.08, 8 * pixel);
            const wing = Math.max(0.06, 5 * pixel);
            ctx.moveTo(0, -tip);
            ctx.lineTo(wing, -FOOTPRINT.front);
            ctx.lineTo(-wing, -FOOTPRINT.front);
            ctx.closePath();
            ctx.fillStyle = HUD;
            ctx.fill();
            ctx.restore();
        }
        ctx.globalAlpha = 1;

        const north = Math.round(rotation / DEG);
        if (north !== view.north && northRef.current != null) {
            view.north = north;
            northRef.current.style.transform = `rotate(${north}deg)`;
        }
    });

    const scaleBar = scaleFor(zoom);

    return (
        <div ref={containerRef} className={cx(rootCss, fill && fillCss)} data-armed={armed}>
            <canvas
                ref={canvasRef}
                className={canvasCss}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={() => {
                    view.drag = null;
                }}
            />
            {empty && <div className={emptyCss}>WAITING FOR MAP</div>}
            <div ref={northRef} className={northCss} title='North'>
                <span>N</span>
            </div>
            <div className={toolsCss}>
                {panned && (
                    <button className={toolCss} onClick={recenter} title='Follow the robot'>
                        CENTER
                    </button>
                )}
                <button
                    className={toolCss}
                    onClick={() => setOrientation((value) => (value === 'north' ? 'heading' : 'north'))}
                    title='Toggle north-up / heading-up'>
                    {TOP_ORIENTATIONS.find((item) => item.id === orientation)?.label}
                </button>
                <button
                    className={toolCss}
                    onClick={() => setZoom((value) => Math.max(MIN_ZOOM, value / ZOOM_STEP))}
                    title='Zoom out'>
                    −
                </button>
                <button
                    className={toolCss}
                    onClick={() => setZoom((value) => Math.min(MAX_ZOOM, value * ZOOM_STEP))}
                    title='Zoom in'>
                    +
                </button>
            </div>
            <div className={scaleCss}>
                <div className={scaleBarCss} style={{ width: scaleBar.px }} />
                <span>{scaleBar.label}</span>
            </div>
            {armed && <div className={hintCss}>CLICK TO GO · SHIFT+CLICK TO APPEND</div>}
        </div>
    );
};

const rootCss = css`
    position: relative;
    height: 200px;
    overflow: hidden;
    background: rgba(2, 10, 14, 0.85);
    border: 1px solid var(--hud-faint);
    text-shadow: none;
`;

const fillCss = css`
    height: 100%;
    min-height: 320px;
`;

const canvasCss = css`
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    cursor: grab;
    touch-action: none;

    &:active {
        cursor: grabbing;
    }

    [data-armed='true'] > & {
        cursor: crosshair;
    }
`;

const emptyCss = css`
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    letter-spacing: 0.12em;
    opacity: 0.5;
    pointer-events: none;
`;

const northCss = css`
    position: absolute;
    top: 4px;
    left: 4px;
    width: 18px;
    height: 18px;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    font-size: 8px;
    font-weight: 700;
    line-height: 10px;
    color: var(--hud);
    border: 1px solid var(--hud-faint);
    border-radius: 50%;
    pointer-events: none;

    &::before {
        content: '';
        position: absolute;
        top: -4px;
        left: 50%;
        margin-left: -3px;
        border: 3px solid transparent;
        border-top: none;
        border-bottom: 4px solid var(--hud);
    }

    & > span {
        margin-top: 3px;
    }
`;

const toolsCss = css`
    position: absolute;
    top: 4px;
    right: 4px;
    display: flex;
    gap: 2px;
`;

const toolCss = css`
    min-width: 18px;
    height: 16px;
    padding: 0 4px;
    border: 1px solid var(--hud-faint);
    background: var(--hud-bg);
    color: var(--hud);
    font: inherit;
    font-size: 8px;
    line-height: 14px;
    letter-spacing: 0.08em;
    cursor: pointer;

    &:hover {
        background: var(--hud-faint);
    }
`;

const scaleCss = css`
    position: absolute;
    left: 6px;
    bottom: 5px;
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 8px;
    letter-spacing: 0.08em;
    pointer-events: none;
`;

const scaleBarCss = css`
    height: 4px;
    border: 1px solid var(--hud);
    border-top: none;
`;

const hintCss = css`
    position: absolute;
    right: 6px;
    bottom: 5px;
    font-size: 8px;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: var(--hud-amber);
    pointer-events: none;
`;

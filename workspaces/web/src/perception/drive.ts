import { type TelemetryStore, isLive } from './Telemetry.ts';

const STEER_TABLE = [0, 0.5, 1];
const LEFT_CURVATURE_TABLE = [0, 1.7, 3.34];
const RIGHT_CURVATURE_TABLE = [0, 1.33, 2.49];

export const CAMERA_TO_REAR_AXLE = 0.1845;
export const CENTERLINE_OFFSET = 0.06;
export const FOOTPRINT = { front: 0.2245, rear: 0.07, halfWidth: 0.1 } as const;

export const curvatureForSteer = (steer: number) => {
    const table = steer >= 0 ? RIGHT_CURVATURE_TABLE : LEFT_CURVATURE_TABLE;
    const x = Math.min(Math.abs(steer), 1);
    for (let i = 1; i < STEER_TABLE.length; i++) {
        const x1 = STEER_TABLE[i]!;
        if (x > x1 && i < STEER_TABLE.length - 1) continue;
        const x0 = STEER_TABLE[i - 1]!;
        const y0 = table[i - 1]!;
        return Math.sign(steer) * (y0 + ((table[i]! - y0) * (x - x0)) / (x1 - x0));
    }
    return 0;
};

export type ArcPose = { along: number; across: number; theta: number };

export const sweepPose = (curvature: number, distance: number, out: ArcPose) => {
    out.theta = curvature * distance;
    const straight = Math.abs(curvature) < 1e-6;
    out.along = straight ? distance : Math.sin(out.theta) / curvature;
    out.across = straight ? 0 : (1 - Math.cos(out.theta)) / curvature;
    return out;
};

export const driveCommand = (store: TelemetryStore, now: number) => {
    const roboclaw = isLive(store.roboclaw, now) ? store.roboclaw.value : null;
    return roboclaw == null ? 0 : ((roboclaw.left.command ?? 0) + (roboclaw.right.command ?? 0)) / 2;
};

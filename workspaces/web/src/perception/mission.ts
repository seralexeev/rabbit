import type { NavState } from './Telemetry.ts';

export type MissionStep =
    | { type: 'turn'; degrees: number }
    | { type: 'move'; forward: number; right: number }
    | { type: 'goto'; x: number; z: number }
    | { type: 'path'; points: [number, number, number][] };

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

const readStep = (raw: unknown): MissionStep | null => {
    if (typeof raw !== 'object' || raw == null) return null;
    const step = raw as Record<string, unknown>;
    if (step['type'] === 'turn' && isFiniteNumber(step['degrees'])) return { type: 'turn', degrees: step['degrees'] };
    if (step['type'] === 'move') {
        const forward = step['forward'] ?? 0;
        const right = step['right'] ?? 0;
        if (isFiniteNumber(forward) && isFiniteNumber(right)) return { type: 'move', forward, right };
    }
    if (step['type'] === 'goto' && isFiniteNumber(step['x']) && isFiniteNumber(step['z']))
        return { type: 'goto', x: step['x'], z: step['z'] };
    if (step['type'] === 'path' && Array.isArray(step['points'])) {
        const points = step['points'].filter(
            (point): point is [number, number, number] =>
                Array.isArray(point) && isFiniteNumber(point[0]) && isFiniteNumber(point[1]),
        );
        return points.length > 0 ? { type: 'path', points } : null;
    }
    return null;
};

export const readSteps = (input: unknown): MissionStep[] | null => {
    const raw = typeof input === 'object' && input != null ? (input as Record<string, unknown>)['steps'] : null;
    if (!Array.isArray(raw)) return null;
    const steps = raw.map(readStep);
    return steps.every((step) => step != null) ? (steps as MissionStep[]) : null;
};

const meters = (value: number) => `${Math.abs(value).toFixed(2)} m`;

export const describeStep = (step: MissionStep) => {
    if (step.type === 'turn') return `TURN ${step.degrees >= 0 ? 'RIGHT' : 'LEFT'} ${Math.abs(step.degrees).toFixed(0)}°`;
    if (step.type === 'goto') return `GOTO X ${step.x.toFixed(2)} · Z ${step.z.toFixed(2)}`;
    if (step.type === 'path') {
        const last = step.points[step.points.length - 1];
        return `PATH ${step.points.length} PTS → X ${last?.[0].toFixed(2) ?? '?'} · Z ${last?.[1].toFixed(2) ?? '?'}`;
    }
    const parts = [];
    if (step.forward !== 0) parts.push(`${step.forward > 0 ? 'FWD' : 'BACK'} ${meters(step.forward)}`);
    if (step.right !== 0) parts.push(`${step.right > 0 ? 'RIGHT' : 'LEFT'} ${meters(step.right)}`);
    return `MOVE ${parts.join(' · ') || '0 m'}`;
};

export const remainingMission = (nav: NavState | null): MissionStep[] => {
    if (nav == null || nav.mode === 'idle' || nav.mode === 'arrived' || nav.step == null) return [];
    const queue = nav.queue ?? [];
    const step = nav.step;
    if (step.type === 'turn') {
        const remaining = nav.turn_remaining_deg ?? step.degrees;
        return Math.abs(remaining) < 1 ? queue : [{ type: 'turn', degrees: remaining }, ...queue];
    }
    if (step.type === 'move' && nav.goal != null) return [{ type: 'goto', x: nav.goal.x, z: nav.goal.z }, ...queue];
    return [step, ...queue];
};

export type Waypoint = { x: number; z: number; marker: boolean };

const DEG = Math.PI / 180;

export const predictWaypoints = (
    steps: readonly MissionStep[],
    start: { x: number; z: number; heading: number },
    out: Waypoint[],
) => {
    let { x, z, heading } = start;
    let count = 0;
    const push = (nextX: number, nextZ: number, marker: boolean) => {
        if (count >= out.length) return;
        if (nextX !== x || nextZ !== z) heading = Math.atan2(nextX - x, -(nextZ - z)) / DEG;
        x = nextX;
        z = nextZ;
        const waypoint = out[count++]!;
        waypoint.x = x;
        waypoint.z = z;
        waypoint.marker = marker;
    };
    for (const step of steps) {
        if (step.type === 'turn') {
            heading += step.degrees;
        } else if (step.type === 'goto') {
            push(step.x, step.z, true);
        } else if (step.type === 'path') {
            step.points.forEach(([px, pz, direction], i) => {
                push(px, pz, i === step.points.length - 1);
                if (direction < 0) heading += 180;
            });
        } else {
            const h = heading * DEG;
            const nextX = x + Math.sin(h) * step.forward + Math.cos(h) * step.right;
            const nextZ = z - Math.cos(h) * step.forward + Math.sin(h) * step.right;
            const keep = heading;
            push(nextX, nextZ, true);
            heading = keep;
        }
    }
    return count;
};

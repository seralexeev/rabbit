import { type TelemetryStore, isLive } from './Telemetry.ts';

const SAMPLE_MS = 200;
const CAPACITY = 3000;
const MAX_STEERING_DEG = 30;
const RAD_TO_DEG = 180 / Math.PI;

const SIGNALS = {
    battery_v: (s: TelemetryStore) => s.ina.value?.channels.find((c) => c.ch === 1)?.voltage,
    battery_a: (s: TelemetryStore) => s.ina.value?.channels.find((c) => c.ch === 1)?.current,
    battery_w: (s: TelemetryStore) => s.ina.value?.channels.find((c) => c.ch === 1)?.power,
    charge_pct: (s: TelemetryStore) => s.ina.value?.battery_charge_pct,
    rail_v: (s: TelemetryStore) => s.ina.value?.channels.find((c) => c.ch === 2)?.voltage,
    rail_a: (s: TelemetryStore) => s.ina.value?.channels.find((c) => c.ch === 2)?.current,
    left_cmd: (s: TelemetryStore) => percent(s.roboclaw.value?.left.command),
    left_pwm: (s: TelemetryStore) => percent(s.roboclaw.value?.left.pwm),
    left_a: (s: TelemetryStore) => s.roboclaw.value?.left.current,
    right_cmd: (s: TelemetryStore) => percent(s.roboclaw.value?.right.command),
    right_pwm: (s: TelemetryStore) => percent(s.roboclaw.value?.right.pwm),
    right_a: (s: TelemetryStore) => s.roboclaw.value?.right.current,
    supply_v: (s: TelemetryStore) => s.roboclaw.value?.supply_voltage,
    roboclaw_c: (s: TelemetryStore) => s.roboclaw.value?.temperature,
    steer_deg: (s: TelemetryStore) => (s.steering.value == null ? undefined : s.steering.value.angle * MAX_STEERING_DEG),
    speed: (s: TelemetryStore) => (hasPose(s) ? s.derived.speed : undefined),
    pitch: (s: TelemetryStore) => (hasPose(s) ? s.derived.pitch * RAD_TO_DEG : undefined),
    roll: (s: TelemetryStore) => (hasPose(s) ? s.derived.roll * RAD_TO_DEG : undefined),
    camera_height: (s: TelemetryStore) => (hasPose(s) ? s.pose.value?.translation[1] : undefined),
    g: (s: TelemetryStore) => (hasImu(s) ? s.derived.g : undefined),
    lateral_g: (s: TelemetryStore) => (hasImu(s) ? s.derived.lateralG : undefined),
    longitudinal_g: (s: TelemetryStore) => (hasImu(s) ? s.derived.longitudinalG : undefined),
    yaw_rate_deg: (s: TelemetryStore) => (hasImu(s) ? s.imu.value?.angular_velocity[1] : undefined),
    goal_m: (s: TelemetryStore) => s.nav.value?.distance_to_goal ?? undefined,
    heading_error: (s: TelemetryStore) => s.nav.value?.heading_error_deg ?? undefined,
    left_x: (s: TelemetryStore) => s.joy.value?.sticks.left.x,
    left_y: (s: TelemetryStore) => s.joy.value?.sticks.left.y,
    right_x: (s: TelemetryStore) => s.joy.value?.sticks.right.x,
    right_y: (s: TelemetryStore) => s.joy.value?.sticks.right.y,
    rtt_ms: (s: TelemetryStore) => s.system.value?.wifi?.gateway_rtt_ms ?? undefined,
    signal_dbm: (s: TelemetryStore) => s.system.value?.wifi?.signal_dbm ?? undefined,
    uplink_kbps: (s: TelemetryStore) => kilobytes(s.system.value?.wifi?.tx_bytes_per_s),
    downlink_kbps: (s: TelemetryStore) => kilobytes(s.system.value?.wifi?.rx_bytes_per_s),
    l2: (s: TelemetryStore) => s.joy.value?.buttons.l2.value,
    r2: (s: TelemetryStore) => s.joy.value?.buttons.r2.value,
} satisfies Record<string, (store: TelemetryStore) => number | undefined>;

export type Signal = keyof typeof SIGNALS;

function percent(value: number | undefined) {
    return value == null ? undefined : value * 100;
}

function kilobytes(bytesPerSecond: number | undefined) {
    return bytesPerSecond == null ? undefined : bytesPerSecond / 1024;
}

function hasPose(s: TelemetryStore) {
    return s.derived.hasPose && isLive(s.pose, performance.now());
}

function hasImu(s: TelemetryStore) {
    return isLive(s.imu, performance.now());
}

const NAMES = Object.keys(SIGNALS) as Signal[];

export type History = {
    rows: (signals: readonly Signal[], seconds: number) => Record<string, number | null>[];
    start: () => () => void;
};

export const createHistory = (store: TelemetryStore): History => {
    const times = new Float64Array(CAPACITY);
    const values = Object.fromEntries(NAMES.map((name) => [name, new Float32Array(CAPACITY).fill(Number.NaN)])) as Record<
        Signal,
        Float32Array
    >;
    let head = 0;
    let count = 0;

    const sample = () => {
        times[head] = Date.now();
        for (const name of NAMES) values[name][head] = SIGNALS[name](store) ?? Number.NaN;
        head = (head + 1) % CAPACITY;
        count = Math.min(count + 1, CAPACITY);
    };

    return {
        rows: (signals, seconds) => {
            const since = Date.now() - seconds * 1000;
            const rows: Record<string, number | null>[] = [];
            for (let i = count; i > 0; i--) {
                const index = (head - i + CAPACITY) % CAPACITY;
                const t = times[index]!;
                if (t < since) continue;
                const row: Record<string, number | null> = { t };
                for (const name of signals) {
                    const value = values[name][index]!;
                    row[name] = Number.isNaN(value) ? null : value;
                }
                rows.push(row);
            }
            return rows;
        },
        start: () => {
            const timer = window.setInterval(sample, SAMPLE_MS);
            return () => window.clearInterval(timer);
        },
    };
};

import type { NatsConnection } from '@nats-io/nats-core';

import type { DualSenseState } from '../controller/dualsense.ts';
import type { MissionStep } from './mission.ts';

type Vec3 = [number, number, number];
type Quat = [number, number, number, number];

type Pose = {
    translation: Vec3;
    orientation: Quat;
    timestamp: number;
    velocity?: Vec3;
    position_std?: Vec3;
    confidence?: number;
};
type Motor = { command: number; pwm: number; current: number };
type Roboclaw = {
    left: Motor;
    right: Motor;
    supply_voltage: number;
    temperature: number;
    status: number;
    errors: number;
};
type Steering = { angle: number; pulse_us: number };
type InaChannel = { ch: number; name: string; voltage: number; current: number; power: number };
type Ina = { channels: InaChannel[]; battery_charge_pct: number; errors: number };
type Imu = { acceleration: Vec3; angular_velocity: Vec3; orientation: Quat; g?: number };
type Magnetometer = { field_ut: Vec3; heading_deg: number; heading_state: string };
type Barometer = { pressure_hpa: number };
type Wifi = {
    connected: boolean;
    ssid: string | null;
    frequency_mhz: number | null;
    signal_dbm: number | null;
    rx_bitrate_mbps: number | null;
    tx_bitrate_mbps: number | null;
    gateway_rtt_ms: number | null;
    tx_bytes_per_s?: number;
    rx_bytes_per_s?: number;
    tx_errors: number;
    rx_errors: number;
    tx_dropped: number;
    rx_dropped: number;
    tx_errors_per_s?: number;
    rx_errors_per_s?: number;
    tx_dropped_per_s?: number;
    rx_dropped_per_s?: number;
};
type ContainerStats = {
    name: string;
    cpu: number;
    mem: number;
    mem_limit: number;
};

export type SystemTelemetry = {
    cpu: number[];
    cpu_freq_mhz: number[];
    gpu: number;
    gpu_freq_mhz: number;
    ram: { used: number; total: number };
    swap: { used: number; total: number };
    temp: Record<string, number>;
    power: number;
    disk: { used: number; total: number };
    uptime: string;
    fan: number;
    fan_rpm: number;
    containers: ContainerStats[];
    wifi?: Wifi;
};

export type Contact = { distance: number; point: Vec3; bearing_deg: number };
export type Scan = {
    angle_min_deg: number;
    angle_step_deg: number;
    ranges: (number | null)[];
    blind_fraction: number;
    blind: boolean;
};
type Obstacle = { nearest: Contact | null; ahead: Contact | null; scan?: Scan };
type NavMode = 'idle' | 'driving' | 'maneuvering' | 'blocked' | 'arrived' | 'fault';
export type NavState = {
    mode: NavMode;
    goal: { x: number; z: number } | null;
    path: [number, number][];
    distance_to_goal: number | null;
    heading_error_deg: number | null;
    speed: number;
    steer: number;
    step?: MissionStep | null;
    step_index?: number;
    steps_total?: number;
    queue?: MissionStep[];
    turn_remaining_deg?: number | null;
    fault?: string | null;
};
export type ExploreTarget = { x: number; z: number; theta: number; cells: number; path_length: number; reverse_length: number };
type ExplorePhase = 'idle' | 'planning' | 'driving' | 'done' | 'failed';
export type ExploreState = {
    phase: ExplorePhase;
    message: string | null;
    elapsed_s: number | null;
    travelled_m: number | null;
    limits: Record<string, number | null> | null;
    frontiers: number | null;
    failed_frontiers: number | null;
    target: ExploreTarget | null;
    planning_ms: number | null;
    map_chunks: number | null;
};

type Channels = {
    pose: Pose;
    roboclaw: Roboclaw;
    steering: Steering;
    ina: Ina;
    imu: Imu;
    joy: DualSenseState;
    magnetometer: Magnetometer;
    barometer: Barometer;
    obstacle: Obstacle;
    nav: NavState;
    system: SystemTelemetry;
    explore: ExploreState;
};

export type ChannelName = keyof Channels;

type Channel<T> = { value: T | null; receivedAt: number; version: number };

type Derived = {
    hasPose: boolean;
    x: number;
    y: number;
    z: number;
    heading: number;
    pitch: number;
    roll: number;
    speed: number;
    odometer: number;
    lateralG: number;
    longitudinalG: number;
    g: number;
};

export type TelemetryStore = { [K in ChannelName]: Channel<Channels[K]> } & {
    derived: Derived;
    connect: (nc: NatsConnection) => () => void;
};

const SUBJECTS: Record<ChannelName, string> = {
    pose: 'rabbit.zed.pose',
    roboclaw: 'rabbit.roboclaw',
    steering: 'rabbit.steering',
    ina: 'rabbit.ina',
    imu: 'rabbit.zed.imu',
    joy: 'rabbit.cmd.joy',
    magnetometer: 'rabbit.zed.magnetometer',
    barometer: 'rabbit.zed.barometer',
    obstacle: 'rabbit.zed.obstacle',
    nav: 'rabbit.nav.state',
    system: 'rabbit.telemetry',
    explore: 'rabbit.explore.state',
};

const CHANNEL_NAMES = Object.keys(SUBJECTS) as ChannelName[];

const STALE_MS = 1500;

const channel = <T>(): Channel<T> => ({ value: null, receivedAt: -Infinity, version: 0 });

export const createTelemetryStore = (): TelemetryStore => {
    const store: TelemetryStore = {
        pose: channel(),
        roboclaw: channel(),
        steering: channel(),
        ina: channel(),
        imu: channel(),
        joy: channel(),
        magnetometer: channel(),
        barometer: channel(),
        obstacle: channel(),
        nav: channel(),
        system: channel(),
        explore: channel(),
        derived: {
            hasPose: false,
            x: 0,
            y: 0,
            z: 0,
            heading: 0,
            pitch: 0,
            roll: 0,
            speed: 0,
            odometer: 0,
            lateralG: 0,
            longitudinalG: 0,
            g: 1,
        },
        connect: (nc) => {
            const subs = CHANNEL_NAMES.map((name) => {
                const target = store[name] as Channel<unknown>;
                return nc.subscribe(SUBJECTS[name], {
                    callback: (err, msg) => {
                        if (err) return;
                        try {
                            target.value = msg.json();
                            target.receivedAt = performance.now();
                            target.version++;
                        } catch {}
                    },
                });
            });
            return () => {
                for (const sub of subs) sub.unsubscribe();
            };
        },
    };
    return store;
};

export const isLive = (channel: Channel<unknown>, now: number, timeoutMs = STALE_MS) => now - channel.receivedAt < timeoutMs;

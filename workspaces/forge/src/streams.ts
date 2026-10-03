import type { Msg } from '@nats-io/transport-node';
import z from 'zod';

import { ForgeError } from './errors.ts';

export type Row = Record<string, unknown>;

type Stream = {
  subject: string;
  table: string;
  toRows: (msg: Msg, receivedAt: string) => Row[];
};

const TS = /"ts":\s*(\d+)/;

const EARLIEST_NS = 1_500_000_000_000_000_000n;
const LATEST_NS = 4_000_000_000_000_000_000n;

export const nanos = (text: string) => {
  const match = TS.exec(text)?.[1];
  if (match == null) {
    throw new ForgeError('Payload has no ts');
  }
  const value = BigInt(match);
  if (value < EARLIEST_NS || value > LATEST_NS) {
    throw new ForgeError('Payload ts is not a wall-clock time in nanoseconds', {
      internal: { ts: match },
    });
  }
  return match;
};

const nanosField = (text: string, key: string) =>
  new RegExp(`"${key}":\\s*(\\d+)`).exec(text)?.[1] ?? null;

const EARLIEST_MS = 1_500_000_000_000n;
const LATEST_MS = 4_000_000_000_000n;

const commandTime = (text: string, receivedAt: string) => {
  const match = TS.exec(text)?.[1];
  if (match == null) {
    return receivedAt;
  }
  const value = BigInt(match);
  if (value >= EARLIEST_NS && value <= LATEST_NS) {
    return match;
  }
  return value >= EARLIEST_MS && value <= LATEST_MS
    ? `${value * 1_000_000n}`
    : receivedAt;
};

const Source = z.object({ source: z.string().default('hud') });

const parsed = new WeakMap<Msg, { text: string; value: unknown }>();

const json = <T extends z.ZodType>(schema: T, msg: Msg) => {
  let cached = parsed.get(msg);
  if (cached == null) {
    const text = msg.string();
    cached = { text, value: JSON.parse(text) as unknown };
    parsed.set(msg, cached);
  }
  return { text: cached.text, payload: schema.parse(cached.value) };
};

const Motor = z.object({
  command: z.number(),
  pwm: z.number(),
  current: z.number(),
  speed: z.number(),
  encoder: z.number(),
});

const Roboclaw = z.object({
  left: Motor,
  right: Motor,
  supply_voltage: z.number(),
  duty_max: z.number().nullish(),
  temperature: z.number(),
  status: z.number(),
  errors: z.number(),
  retries: z.number().default(0),
  reconnects: z.number().default(0),
});

const Channel = z.object({
  name: z.string(),
  voltage: z.number(),
  current: z.number(),
  power: z.number(),
  clipped: z.boolean().nullish(),
});

const Ina = z.object({
  channels: z.array(Channel),
  battery_charge_pct: z.number(),
  errors: z.number(),
});

const channel = (channels: Array<z.infer<typeof Channel>>, name: string) => {
  const found = channels.find((candidate) => candidate.name === name);
  if (found == null) {
    throw new ForgeError('Power channel missing', { internal: { name } });
  }
  return found;
};

const LidarHealth = z.object({
  connected: z.boolean(),
  model: z.number().nullish(),
  firmware: z.string().nullish(),
  device_health: z.string().nullish(),
  error_code: z.number().nullish(),
  scan_hz: z.number(),
  points: z.number(),
  measurements: z.number(),
  rotation_s: z.number().nullish(),
  scan_age_s: z.number().nullish(),
  rotations: z.number(),
  bad_nodes: z.number(),
  skipped_bytes: z.number(),
  short_rotations: z.number(),
  restarts: z.number(),
  reconnects: z.number(),
  errors: z.number(),
  sector_min_m: z.array(z.number().nullable()),
});

const TofHealth = z.object({
  power_cycles: z.number(),
  sensors: z.array(
    z.object({
      sensor: z.string(),
      bus: z.number(),
      state: z.string(),
      hz: z.number(),
      frame_age_s: z.number().nullish(),
      valid: z.number().nullish(),
      floor: z.number().nullish(),
      overhead: z.number().nullish(),
      obstacles: z.number(),
      nearest_m: z.number().nullish(),
      errors: z.number(),
      resets: z.number(),
      init_s: z.number().nullish(),
    }),
  ),
});

const SafetyState = z.object({
  mode: z.string(),
  reason: z.string(),
  reasons: z.array(z.string()),
  shadow: z.boolean(),
  estop_line: z.boolean(),
  estop_latched: z.boolean(),
  estop_source: z.string().nullish(),
  self_test: z.string(),
  speed: z.number(),
  steer: z.number(),
  requested_speed: z.number(),
  requested_steer: z.number(),
  source: z.string(),
  owner: z.string(),
  cap_fwd: z.number(),
  cap_rev: z.number(),
  clearance_fwd_m: z.number().nullish(),
  clearance_rev_m: z.number().nullish(),
  brain_ok: z.boolean(),
  bumper_front: z.boolean(),
  bumper_rear: z.boolean(),
  battery_low: z.boolean(),
  battery_critical: z.boolean(),
  power_state: z.string(),
  input_age_s: z.record(z.string(), z.number().nullable()),
});

const PowerState = z.object({
  state: z.string(),
  reason: z.string(),
  state_s: z.number(),
  battery_v: z.number().nullish(),
  battery_low: z.boolean(),
  charge_pct: z.number().nullish(),
  jetson_a: z.number().nullish(),
  brain_ok: z.boolean(),
  safety_ready: z.boolean(),
  button: z.boolean(),
  jetson_cycles_last_hour: z.number(),
});

const known = (ages: Record<string, number | null>) =>
  Object.fromEntries(
    Object.entries(ages).filter(
      (entry): entry is [string, number] => entry[1] != null,
    ),
  );

const Steering = z.object({
  angle: z.number(),
  pulse_us: z.number(),
  errors: z.number().default(0),
});

const Vector3 = z.tuple([z.number(), z.number(), z.number()]);
const Quaternion = z.tuple([z.number(), z.number(), z.number(), z.number()]);

const Imu = z.object({
  acceleration: Vector3,
  angular_velocity: Vector3,
  orientation: Quaternion,
  g: z.number().optional(),
  samples: z.number().optional(),
});

const Pose = z.object({
  frame_number: z.number(),
  translation: Vector3,
  orientation: Quaternion,
  euler_deg: Vector3,
  velocity: Vector3,
  angular_velocity: Vector3,
  position_std: Vector3,
  confidence: z.number(),
});

export const ZED_EULER = { pitch: 0, yaw: 1, roll: 2 } as const;

export const zedEuler = (euler: [number, number, number]) => ({
  roll_deg: euler[ZED_EULER.roll],
  pitch_deg: euler[ZED_EULER.pitch],
  yaw_deg: euler[ZED_EULER.yaw],
});

const Magnetometer = z.object({
  field_ut: Vector3,
  heading_deg: z.number(),
  heading_state: z.string(),
});

const Barometer = z.object({ pressure_hpa: z.number() });

const Containers = z.object({
  containers: z.array(
    z.object({
      name: z.string(),
      cpu: z.number(),
      mem: z.number(),
      mem_limit: z.number(),
    }),
  ),
});

const Wifi = z.object({
  wifi: z
    .object({
      connected: z.boolean(),
      ssid: z.string().nullish(),
      frequency_mhz: z.number().nullish(),
      signal_dbm: z.number().nullish(),
      rx_bitrate_mbps: z.number().nullish(),
      tx_bitrate_mbps: z.number().nullish(),
      gateway_rtt_ms: z.number().nullish(),
      tx_bytes_per_s: z.number().nullish(),
      rx_bytes_per_s: z.number().nullish(),
      tx_errors_per_s: z.number().nullish(),
      rx_errors_per_s: z.number().nullish(),
      tx_dropped_per_s: z.number().nullish(),
      rx_dropped_per_s: z.number().nullish(),
    })
    .optional(),
});

const Telemetry = z.object({
  cpu: z.array(z.number()),
  cpu_freq_mhz: z.array(z.number()),
  gpu: z.number(),
  gpu_freq_mhz: z.number(),
  ram: z.object({
    used: z.number(),
    total: z.number(),
    shared: z.number().nullish(),
  }),
  swap: z.object({ used: z.number() }),
  temp: z.object({
    cpu: z.number(),
    gpu: z.number(),
    soc0: z.number(),
    soc1: z.number(),
    soc2: z.number(),
    tj: z.number(),
  }),
  power: z.number(),
  input_mv: z.number(),
  input_ma: z.number(),
  rails_mw: z.object({ VDD_CPU_GPU_CV: z.number(), VDD_SOC: z.number() }),
  disk: z.object({ used: z.number() }),
  uptime: z.string(),
  fan: z.number(),
  fan_rpm: z.number(),
  clocks: z
    .object({
      cpu_cur_mhz: z.array(z.number()).default([]),
      cpu_min_mhz: z.array(z.number()).default([]),
      gpu_min_mhz: z.number().nullish(),
      gpu_max_mhz: z.number().nullish(),
      emc_mhz: z.number().nullish(),
      oc_events: z.array(z.number().nullable()).nullish(),
      oc_throttle_ticks: z.number().nullish(),
      power_mode: z.string().default(''),
    })
    .optional(),
  boot_id: z.string().default(''),
});

const NatsServer = z.object({
  boot_id: z.string().default(''),
  nats: z
    .object({
      connections: z.number().nullish(),
      subscriptions: z.number().nullish(),
      slow_consumers: z.number().nullish(),
      in_msgs: z.number().nullish(),
      out_msgs: z.number().nullish(),
      in_bytes: z.number().nullish(),
      out_bytes: z.number().nullish(),
      mem: z.number().nullish(),
      cpu: z.number().nullish(),
      slow_consumer_stats: z.record(z.string(), z.number()).nullish(),
    })
    .optional(),
});

const NodeMetrics = z.object({
  node: z.string(),
  instance_id: z.string().default(''),
  boot_id: z.string().default(''),
  uptime_s: z.number(),
  interval_s: z.number().nullish(),
  cpu_pct: z.number().nullish(),
  rss_bytes: z.number().nullish(),
  threads: z.number().nullish(),
  loop_lag_max_ms: z.number().nullish(),
  loop_lag_mean_ms: z.number().nullish(),
  sent_msgs: z.number().default(0),
  sent_bytes: z.number().default(0),
  received_msgs: z.number().default(0),
  received_bytes: z.number().default(0),
  reconnects: z.number().default(0),
  dropped_publishes: z.number().default(0),
  log_dropped: z.number().default(0),
  events: z.number().default(0),
  events_suppressed: z.number().default(0),
  events_dropped: z.number().default(0),
  callback_errors: z.number().default(0),
  values: z.record(z.string(), z.number()).default({}),
});

const LocMapOdom = z.object({
  keyframe_ts: z.number().nullish(),
  status: z.string(),
  mode: z.string(),
  map_id: z.string(),
  odom_session: z.string().nullish(),
  translation: z.tuple([z.number(), z.number(), z.number()]).nullish(),
  orientation: z
    .tuple([z.number(), z.number(), z.number(), z.number()])
    .nullish(),
  matches: z.number(),
  corrections: z.number(),
  pending: z.number(),
  grown_nodes: z.number().default(0),
  last_match_ts: z.number().nullish(),
});

const LocShadow = z
  .object({
    status: z.string().nullish(),
    gen3_from_loc: z.tuple([z.number(), z.number(), z.number()]).nullish(),
  })
  .nullish();

const ZedHealth = z.object({
  camera_fps: z.number(),
  current_fps: z.number(),
  last_capture_duration_ms: z.number(),
  last_pose_state: z.string(),
  pose_messages: z.number(),
  pose_drop_count: z.number(),
  frames_dropped: z.number(),
  tracking_fusion_status: z.string(),
  odometry_status: z.string(),
  spatial_memory_status: z.string(),
  camera_moving_state: z.string(),
  low_image_quality: z.boolean(),
  low_lighting: z.boolean(),
  low_depth_reliability: z.boolean(),
  low_motion_sensors_reliability: z.boolean(),
  preview_skipped: z.number(),
  mapping_state: z.string(),
  map_chunks: z.number(),
  map_points: z.number(),
  map_triangles: z.number().default(0),
  relocalizing: z.boolean().nullish(),
  map_mode: z.string().nullish(),
  map_id: z.string().nullish(),
  map_session: z.string().nullish(),
  idle: z.boolean().nullish(),
  implausible_poses: z.number().nullish(),
  held_poses: z.number().nullish(),
  odom_rejected: z.number().nullish(),
  dropped_publishes: z.number().nullish(),
  corrupted_frames: z.number().nullish(),
  map_rebuilds: z.number().nullish(),
  stored_frames: z.number().nullish(),
  keyframes: z.number().nullish(),
  integrate_ms: z.number().nullish(),
  mesh_ms: z.number().nullish(),
  grid_ms: z.number().nullish(),
  skipped_jumps: z.number().nullish(),
  floor_y: z.number().nullish(),
  detector_ms: z.number().nullish(),
  pose_tilt_deg: z.number().nullish(),
  imu_tilt_deg: z.number().nullish(),
  loc: LocShadow,
  temperature: z.object({
    imu: z.number(),
    barometer: z.number(),
    onboard_left: z.number(),
    onboard_right: z.number(),
  }),
});

const ObstaclePoint = z
  .object({ distance: z.number(), point: Vector3, bearing_deg: z.number() })
  .nullable();

const Scan = z.object({
  angle_min_deg: z.number(),
  angle_step_deg: z.number(),
  ranges: z.array(z.number().nullable()),
  blind_fraction: z.number().nullish(),
  blind: z.boolean().default(false),
});

const Obstacle = z.object({
  nearest: ObstaclePoint,
  ahead: ObstaclePoint,
  scan: Scan.nullish(),
});

const DetectedObjects = z.object({
  objects: z.array(
    z.object({
      id: z.number(),
      label: z.string(),
      confidence: z.number(),
      position: Vector3,
      dimensions: Vector3,
      box: z.array(z.number()),
      moving: z.boolean(),
    }),
  ),
});

const NavState = z.object({
  mode: z.string(),
  goal: z.object({ x: z.number(), z: z.number() }).nullable(),
  path: z.array(z.unknown()),
  distance_to_goal: z.number(),
  heading_error_deg: z.number(),
  speed: z.number(),
  steer: z.number(),
  step: z.object({ type: z.string() }).nullish(),
  step_index: z.number().nullish(),
  steps_total: z.number().nullish(),
  turn_remaining_deg: z.number().nullish(),
  free_distance: z.number().nullish(),
  fault: z.string().nullish(),
  hold: z.string().nullish(),
  mission_id: z.string().nullish(),
  mission_source: z.string().nullish(),
  trip_id: z.string().nullish(),
});

const Mission = Source.extend({ steps: z.array(z.unknown()) });

const Drive = Source.extend({ speed: z.number(), steer: z.number() });

const Goal = Source.extend({ x: z.number(), z: z.number() });

const ExploreState = z.object({
  exploration_id: z.string().nullish(),
  phase: z.string(),
  message: z.string().nullish(),
  elapsed_s: z.number().nullish(),
  travelled_m: z.number(),
  limits: z
    .object({
      max_duration_s: z.number().optional(),
      max_distance_m: z.number().optional(),
    })
    .default({}),
  frontiers: z.number(),
  failed_frontiers: z.number(),
  target: z
    .object({
      x: z.number(),
      z: z.number(),
      path_length: z.number().nullish(),
    })
    .nullish(),
  planning_ms: z.number().nullish(),
  map_chunks: z.number(),
});

const PlannerState = z.object({
  trip_id: z.string().nullish(),
  phase: z.string(),
  source: z.string().nullish(),
  preview: z.boolean().nullish(),
  target: z
    .object({
      kind: z.string(),
      label: z.string().nullish(),
      x: z.number(),
      z: z.number(),
    })
    .nullish(),
  goal: z
    .object({ x: z.number(), z: z.number(), heading_deg: z.number().nullish() })
    .nullish(),
  path_length_m: z.number().nullish(),
  remaining_m: z.number().nullish(),
  replans: z.number().default(0),
  recoveries: z.number().default(0),
  reason: z.string().nullish(),
  message: z.string().nullish(),
  plan_ms: z.number().nullish(),
  expansions: z.number().nullish(),
  mission_id: z.string().nullish(),
  exploration_id: z.string().nullish(),
});

const FINISHED_TRIP = new Set(['arrived', 'failed', 'cancelled', 'planned']);

const plannerStream = (): Stream => {
  let lastFinished = '';
  return {
    subject: 'rabbit.planner.state',
    table: 'planner_state',
    toRows: (msg) => {
      const { text, payload } = json(PlannerState, msg);
      if (payload.trip_id == null) {
        return [];
      }
      const finished = FINISHED_TRIP.has(payload.phase)
        ? `${payload.trip_id}:${payload.phase}`
        : '';
      if (finished !== '' && finished === lastFinished) {
        return [];
      }
      lastFinished = finished;
      return [
        {
          ts: nanos(text),
          trip_id: payload.trip_id,
          phase: payload.phase,
          source: payload.source ?? '',
          preview: payload.preview ?? false,
          target_kind: payload.target?.kind ?? '',
          target_label: payload.target?.label ?? '',
          target_x: payload.target?.x ?? null,
          target_z: payload.target?.z ?? null,
          goal_x: payload.goal?.x ?? null,
          goal_z: payload.goal?.z ?? null,
          goal_heading_deg: payload.goal?.heading_deg ?? null,
          path_length_m: payload.path_length_m ?? null,
          remaining_m: payload.remaining_m ?? null,
          replans: payload.replans,
          recoveries: payload.recoveries,
          reason: payload.reason ?? '',
          message: payload.message ?? '',
          plan_ms: payload.plan_ms ?? null,
          expansions: payload.expansions ?? 0,
          mission_id: payload.mission_id ?? '',
          exploration_id: payload.exploration_id ?? '',
        },
      ];
    },
  };
};

const natsServerStream = (): Stream => {
  let last: number | null = null;
  return {
    subject: 'rabbit.telemetry',
    table: 'nats_server',
    toRows: (msg) => {
      const { text, payload } = json(NatsServer, msg);
      const nats = payload.nats;
      if (nats?.in_msgs == null || nats.in_msgs === last) {
        return [];
      }
      last = nats.in_msgs;
      return [
        {
          ts: nanos(text),
          boot_id: payload.boot_id,
          connections: nats.connections ?? 0,
          subscriptions: nats.subscriptions ?? 0,
          slow_consumers: nats.slow_consumers ?? 0,
          in_msgs: nats.in_msgs,
          out_msgs: nats.out_msgs ?? 0,
          in_bytes: nats.in_bytes ?? 0,
          out_bytes: nats.out_bytes ?? 0,
          mem_bytes: nats.mem ?? 0,
          cpu_pct: nats.cpu ?? 0,
          slow_consumer_stats: nats.slow_consumer_stats ?? {},
        },
      ];
    },
  };
};

const commandEvent = (subject: string): Stream => ({
  subject,
  table: 'command_events',
  toRows: (msg, receivedAt) => {
    const text = msg.string();
    const payload = text.length === 0 ? {} : (JSON.parse(text) as unknown);
    return [
      {
        ts: commandTime(text, receivedAt),
        subject,
        source: Source.parse(payload).source,
        payload: text,
      },
    ];
  },
});

const obstacleColumns = (
  prefix: 'nearest' | 'ahead',
  point: z.infer<typeof ObstaclePoint>,
) => ({
  [`${prefix}_distance`]: point?.distance ?? null,
  [`${prefix}_bearing_deg`]: point?.bearing_deg ?? null,
  [`${prefix}_x`]: point?.point[0] ?? null,
  [`${prefix}_y`]: point?.point[1] ?? null,
  [`${prefix}_z`]: point?.point[2] ?? null,
});

const Joy = z.object({
  buttons: z
    .object({
      r2: z.object({ value: z.number() }).optional(),
      l2: z.object({ value: z.number() }).optional(),
    })
    .optional(),
  sticks: z.object({ left: z.object({ x: z.number() }).optional() }).optional(),
});

const UPTIME_UNITS: Record<string, number> = {
  d: 86_400,
  h: 3600,
  m: 60,
  s: 1,
};

const uptimeSeconds = (uptime: string) =>
  [...uptime.matchAll(/(\d+)([dhms])/g)].reduce(
    (total, [, value, unit]) =>
      total + Number(value) * (UPTIME_UNITS[unit ?? 's'] ?? 0),
    0,
  );

const motorColumns = (
  side: 'left' | 'right',
  motor: z.infer<typeof Motor>,
) => ({
  [`${side}_command`]: motor.command,
  [`${side}_pwm`]: motor.pwm,
  [`${side}_current`]: motor.current,
  [`${side}_speed`]: motor.speed,
  [`${side}_encoder`]: motor.encoder,
});

const mapChunks = { session: '', sizes: new Map<number, string>() };

const MAP_CHUNK_HEADER_BYTES = 24;

const mapChunkRows = (
  data: Uint8Array,
  session: string,
  receivedAt: string,
): Row[] => {
  if (session !== mapChunks.session) {
    mapChunks.session = session;
    mapChunks.sizes.clear();
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const rows: Row[] = [];
  let offset = 0;
  while (offset + MAP_CHUNK_HEADER_BYTES <= view.byteLength) {
    const chunkIndex = view.getUint32(offset, true);
    const vertices = view.getUint32(offset + 4, true);
    const triangles = view.getUint32(offset + 8, true);
    const origin = [
      view.getFloat32(offset + 12, true),
      view.getFloat32(offset + 16, true),
      view.getFloat32(offset + 20, true),
    ] as const;
    const positions = offset + MAP_CHUNK_HEADER_BYTES;
    const size = vertices * 6 + triangles * 6;
    offset = positions + size + (-size & 3);
    if (mapChunks.sizes.get(chunkIndex) === `${vertices}:${triangles}`) {
      continue;
    }
    mapChunks.sizes.set(chunkIndex, `${vertices}:${triangles}`);
    let [sx, sy, sz] = [0, 0, 0];
    for (let i = 0; i < vertices; i++) {
      sx += view.getInt16(positions + i * 6, true);
      sy += view.getInt16(positions + i * 6 + 2, true);
      sz += view.getInt16(positions + i * 6 + 4, true);
    }
    const centroid = (sum: number, axis: 0 | 1 | 2) =>
      vertices === 0 ? 0 : origin[axis] + sum / vertices / 1000;
    rows.push({
      ts: receivedAt,
      session,
      chunk_index: chunkIndex,
      vertices,
      triangles,
      cx: centroid(sx, 0),
      cy: centroid(sy, 1),
      cz: centroid(sz, 2),
    });
  }
  return rows;
};

export const STREAMS: Stream[] = [
  {
    subject: 'rabbit.roboclaw',
    table: 'roboclaw',
    toRows: (msg) => {
      const { text, payload } = json(Roboclaw, msg);
      return [
        {
          ts: nanos(text),
          ...motorColumns('left', payload.left),
          ...motorColumns('right', payload.right),
          supply_voltage: payload.supply_voltage,
          duty_max: payload.duty_max ?? null,
          temperature: payload.temperature,
          status: payload.status,
          errors: payload.errors,
          retries: payload.retries,
          reconnects: payload.reconnects,
        },
      ];
    },
  },
  {
    subject: 'rabbit.ina',
    table: 'power',
    toRows: (msg) => {
      const { text, payload } = json(Ina, msg);
      const battery = channel(payload.channels, 'battery');
      const rail = channel(payload.channels, 'rail_6v');
      return [
        {
          ts: nanos(text),
          battery_voltage: battery.voltage,
          battery_current: battery.current,
          battery_power: battery.power,
          battery_charge_pct: payload.battery_charge_pct,
          battery_clipped: battery.clipped ?? null,
          rail_6v_voltage: rail.voltage,
          rail_6v_current: rail.current,
          rail_6v_power: rail.power,
          rail_6v_clipped: rail.clipped ?? null,
          errors: payload.errors,
        },
      ];
    },
  },
  {
    subject: 'rabbit.steering',
    table: 'steering',
    toRows: (msg) => {
      const { text, payload } = json(Steering, msg);
      return [{ ts: nanos(text), ...payload }];
    },
  },
  {
    subject: 'rabbit.zed.imu',
    table: 'imu',
    toRows: (msg) => {
      const { text, payload } = json(Imu, msg);
      const [ax, ay, az] = payload.acceleration;
      const [gx, gy, gz] = payload.angular_velocity;
      const [qx, qy, qz, qw] = payload.orientation;
      return [
        {
          ts: nanos(text),
          accel_x: ax,
          accel_y: ay,
          accel_z: az,
          gyro_x: gx,
          gyro_y: gy,
          gyro_z: gz,
          qx,
          qy,
          qz,
          qw,
          ...(payload.g == null ? {} : { g: payload.g }),
          ...(payload.samples == null ? {} : { samples: payload.samples }),
        },
      ];
    },
  },
  {
    subject: 'rabbit.zed.pose',
    table: 'pose',
    toRows: (msg) => {
      const { text, payload } = json(Pose, msg);
      const [x, y, z] = payload.translation;
      const [qx, qy, qz, qw] = payload.orientation;
      const [vx, vy, vz] = payload.velocity;
      const [wx, wy, wz] = payload.angular_velocity;
      const [stdX, stdY, stdZ] = payload.position_std;
      return [
        {
          ts: nanos(text),
          frame_number: payload.frame_number,
          x,
          y,
          z,
          qx,
          qy,
          qz,
          qw,
          ...zedEuler(payload.euler_deg),
          vx,
          vy,
          vz,
          wx,
          wy,
          wz,
          std_x: stdX,
          std_y: stdY,
          std_z: stdZ,
          confidence: payload.confidence,
        },
      ];
    },
  },
  {
    subject: 'rabbit.zed.magnetometer',
    table: 'magnetometer',
    toRows: (msg) => {
      const { text, payload } = json(Magnetometer, msg);
      const [fx, fy, fz] = payload.field_ut;
      return [
        {
          ts: nanos(text),
          field_x: fx,
          field_y: fy,
          field_z: fz,
          heading_deg: payload.heading_deg,
          heading_state: payload.heading_state,
        },
      ];
    },
  },
  {
    subject: 'rabbit.zed.barometer',
    table: 'barometer',
    toRows: (msg) => {
      const { text, payload } = json(Barometer, msg);
      return [{ ts: nanos(text), pressure_hpa: payload.pressure_hpa }];
    },
  },
  {
    subject: 'rabbit.telemetry',
    table: 'jetson',
    toRows: (msg) => {
      const { text, payload } = json(Telemetry, msg);
      return [
        {
          ts: nanos(text),
          cpu_load: payload.cpu,
          cpu_freq_mhz: payload.cpu_freq_mhz,
          gpu_load: payload.gpu,
          gpu_freq_mhz: payload.gpu_freq_mhz,
          ram_used_bytes: payload.ram.used,
          ram_total_bytes: payload.ram.total,
          ram_shared_bytes: payload.ram.shared ?? null,
          boot_id: payload.boot_id,
          swap_used_bytes: payload.swap.used,
          temp_cpu: payload.temp.cpu,
          temp_gpu: payload.temp.gpu,
          temp_soc0: payload.temp.soc0,
          temp_soc1: payload.temp.soc1,
          temp_soc2: payload.temp.soc2,
          temp_tj: payload.temp.tj,
          power_mw: payload.power,
          input_mv: payload.input_mv,
          input_ma: payload.input_ma,
          rail_cpu_gpu_cv_mw: payload.rails_mw.VDD_CPU_GPU_CV,
          rail_soc_mw: payload.rails_mw.VDD_SOC,
          disk_used_gb: payload.disk.used,
          uptime_s: uptimeSeconds(payload.uptime),
          fan_pct: payload.fan,
          fan_rpm: payload.fan_rpm,
          ...(payload.clocks == null
            ? {}
            : {
                cpu_actual_mhz: payload.clocks.cpu_cur_mhz,
                cpu_min_freq_mhz: payload.clocks.cpu_min_mhz,
                gpu_min_freq_mhz: payload.clocks.gpu_min_mhz ?? null,
                gpu_max_freq_mhz: payload.clocks.gpu_max_mhz ?? null,
                emc_freq_mhz: payload.clocks.emc_mhz ?? null,
                oc1_events: payload.clocks.oc_events?.[0] ?? null,
                oc2_events: payload.clocks.oc_events?.[1] ?? null,
                oc3_events: payload.clocks.oc_events?.[2] ?? null,
                oc_throttle_ticks: payload.clocks.oc_throttle_ticks ?? null,
                power_mode: payload.clocks.power_mode,
              }),
        },
      ];
    },
  },
  {
    subject: 'rabbit.telemetry',
    table: 'jetson_containers',
    toRows: (msg) => {
      const { text, payload } = json(Containers, msg);
      const ts = nanos(text);
      return payload.containers.map((container) => ({
        ts,
        name: container.name,
        cpu: container.cpu,
        mem_bytes: container.mem,
        mem_limit_bytes: container.mem_limit,
      }));
    },
  },
  natsServerStream(),
  {
    subject: 'rabbit.metrics.*',
    table: 'node_metrics',
    toRows: (msg) => {
      const { text, payload } = json(NodeMetrics, msg);
      return [
        {
          ts: nanos(text),
          node: payload.node,
          instance_id: payload.instance_id,
          boot_id: payload.boot_id,
          uptime_s: payload.uptime_s,
          interval_s: payload.interval_s ?? null,
          cpu_pct: payload.cpu_pct ?? null,
          rss_bytes: payload.rss_bytes ?? null,
          threads: payload.threads ?? null,
          loop_lag_max_ms: payload.loop_lag_max_ms ?? null,
          loop_lag_mean_ms: payload.loop_lag_mean_ms ?? null,
          sent_msgs: payload.sent_msgs,
          sent_bytes: payload.sent_bytes,
          received_msgs: payload.received_msgs,
          received_bytes: payload.received_bytes,
          reconnects: payload.reconnects,
          dropped_publishes: payload.dropped_publishes,
          log_dropped: payload.log_dropped,
          events: payload.events,
          events_suppressed: payload.events_suppressed,
          events_dropped: payload.events_dropped,
          callback_errors: payload.callback_errors,
          values: payload.values,
        },
      ];
    },
  },
  {
    subject: 'rabbit.telemetry',
    table: 'wifi',
    toRows: (msg) => {
      const { text, payload } = json(Wifi, msg);
      return payload.wifi == null ? [] : [{ ts: nanos(text), ...payload.wifi }];
    },
  },
  {
    subject: 'rabbit.health.zed',
    table: 'zed_health',
    toRows: (msg) => {
      const { text, payload } = json(ZedHealth, msg);
      return [
        {
          ts: nanos(text),
          camera_fps: payload.camera_fps,
          current_fps: payload.current_fps,
          capture_ms: payload.last_capture_duration_ms,
          pose_state: payload.last_pose_state,
          pose_messages: payload.pose_messages,
          pose_drop_count: payload.pose_drop_count,
          frames_dropped: payload.frames_dropped,
          tracking_state: payload.tracking_fusion_status,
          odometry_status: payload.odometry_status,
          spatial_memory_status: payload.spatial_memory_status,
          camera_moving_state: payload.camera_moving_state,
          low_image_quality: payload.low_image_quality,
          low_lighting: payload.low_lighting,
          low_depth_reliability: payload.low_depth_reliability,
          low_motion_sensors_reliability:
            payload.low_motion_sensors_reliability,
          preview_skipped: payload.preview_skipped,
          mapping_state: payload.mapping_state,
          map_chunks: payload.map_chunks,
          map_points: payload.map_points,
          map_triangles: payload.map_triangles,
          temp_imu: payload.temperature.imu,
          temp_barometer: payload.temperature.barometer,
          temp_onboard_left: payload.temperature.onboard_left,
          temp_onboard_right: payload.temperature.onboard_right,
          loc_status: payload.loc?.status ?? '',
          gen3_from_loc_x: payload.loc?.gen3_from_loc?.[0] ?? null,
          gen3_from_loc_z: payload.loc?.gen3_from_loc?.[1] ?? null,
          gen3_from_loc_yaw_deg: payload.loc?.gen3_from_loc?.[2] ?? null,
          relocalizing: payload.relocalizing ?? null,
          map_mode: payload.map_mode ?? '',
          map_id: payload.map_id ?? '',
          map_session: payload.map_session ?? '',
          idle: payload.idle ?? null,
          implausible_poses: payload.implausible_poses ?? null,
          held_poses: payload.held_poses ?? null,
          odom_rejected: payload.odom_rejected ?? null,
          dropped_publishes: payload.dropped_publishes ?? null,
          corrupted_frames: payload.corrupted_frames ?? null,
          map_rebuilds: payload.map_rebuilds ?? null,
          stored_frames: payload.stored_frames ?? null,
          keyframes: payload.keyframes ?? null,
          integrate_ms: payload.integrate_ms ?? null,
          mesh_ms: payload.mesh_ms ?? null,
          grid_ms: payload.grid_ms ?? null,
          skipped_jumps: payload.skipped_jumps ?? null,
          floor_y: payload.floor_y ?? null,
          detector_ms: payload.detector_ms ?? null,
          pose_tilt_deg: payload.pose_tilt_deg ?? null,
          imu_tilt_deg: payload.imu_tilt_deg ?? null,
        },
      ];
    },
  },
  {
    subject: 'rabbit.loc.map_odom',
    table: 'loc',
    toRows: (msg) => {
      const { text, payload } = json(LocMapOdom, msg);
      const [qx, qy, qz, qw] = payload.orientation ?? [0, 0, 0, 1];
      return [
        {
          ts: nanos(text),
          keyframe_ts: nanosField(text, 'keyframe_ts'),
          status: payload.status,
          mode: payload.mode,
          map_id: payload.map_id,
          odom_session: payload.odom_session ?? '',
          x: payload.translation?.[0] ?? null,
          y: payload.translation?.[1] ?? null,
          z: payload.translation?.[2] ?? null,
          yaw_deg:
            payload.orientation == null
              ? null
              : (Math.atan2(
                  2 * (qx * qz + qy * qw),
                  1 - 2 * (qx * qx + qy * qy),
                ) *
                  180) /
                Math.PI,
          matches: payload.matches,
          corrections: payload.corrections,
          pending: payload.pending,
          grown_nodes: payload.grown_nodes,
          last_match_ts: nanosField(text, 'last_match_ts'),
        },
      ];
    },
  },
  {
    subject: 'rabbit.cmd.joy',
    table: 'joy',
    toRows: (msg, receivedAt) => {
      const { text, payload } = json(Joy, msg);
      const r2 = payload.buttons?.r2?.value ?? 0;
      const l2 = payload.buttons?.l2?.value ?? 0;
      return [
        {
          ts: receivedAt,
          throttle: r2 - l2,
          steer: payload.sticks?.left?.x ?? 0,
          raw: text,
        },
      ];
    },
  },
  {
    subject: 'rabbit.zed.obstacle',
    table: 'obstacle',
    toRows: (msg) => {
      const { text, payload } = json(Obstacle, msg);
      return [
        {
          ts: nanos(text),
          ...obstacleColumns('nearest', payload.nearest),
          ...obstacleColumns('ahead', payload.ahead),
          blind: payload.scan?.blind ?? false,
          blind_fraction: payload.scan?.blind_fraction ?? null,
          scan_angle_min_deg: payload.scan?.angle_min_deg ?? null,
          scan_angle_step_deg: payload.scan?.angle_step_deg ?? null,
          scan_ranges: payload.scan?.ranges ?? [],
        },
      ];
    },
  },
  {
    subject: 'rabbit.zed.objects',
    table: 'objects',
    toRows: (msg) => {
      const { text, payload } = json(DetectedObjects, msg);
      const ts = nanos(text);
      return payload.objects.map((object) => ({
        ts,
        object_id: object.id,
        label: object.label,
        confidence: object.confidence,
        x: object.position[0],
        y: object.position[1],
        z: object.position[2],
        width: object.dimensions[0],
        height: object.dimensions[1],
        length: object.dimensions[2],
        box: object.box,
        moving: object.moving,
      }));
    },
  },
  {
    subject: 'rabbit.nav.state',
    table: 'nav_state',
    toRows: (msg) => {
      const { text, payload } = json(NavState, msg);
      return [
        {
          ts: nanos(text),
          mode: payload.mode,
          goal_x: payload.goal?.x ?? null,
          goal_z: payload.goal?.z ?? null,
          distance_to_goal: payload.distance_to_goal,
          heading_error_deg: payload.heading_error_deg,
          speed: payload.speed,
          steer: payload.steer,
          path_points: payload.path.length,
          step_type: payload.step?.type ?? '',
          step_index: payload.step_index ?? 0,
          steps_total: payload.steps_total ?? 0,
          turn_remaining_deg: payload.turn_remaining_deg ?? null,
          free_distance: payload.free_distance ?? null,
          fault: payload.fault ?? '',
          hold: payload.hold ?? '',
          mission_id: payload.mission_id ?? '',
          mission_source: payload.mission_source ?? '',
          trip_id: payload.trip_id ?? '',
        },
      ];
    },
  },
  {
    subject: 'rabbit.cmd.drive',
    table: 'drive',
    toRows: (msg, receivedAt) => {
      const { text, payload } = json(Drive, msg);
      return [{ ts: commandTime(text, receivedAt), ...payload }];
    },
  },
  {
    subject: 'rabbit.nav.goal',
    table: 'nav_events',
    toRows: (msg, receivedAt) => {
      const { text, payload } = json(Goal, msg);
      return [
        {
          ts: commandTime(text, receivedAt),
          event: 'goal',
          goal_x: payload.x,
          goal_z: payload.z,
          source: payload.source,
        },
      ];
    },
  },
  {
    subject: 'rabbit.nav.mission',
    table: 'nav_events',
    toRows: (msg, receivedAt) => {
      const { text, payload } = json(Mission, msg);
      return [
        {
          ts: commandTime(text, receivedAt),
          event: 'mission',
          goal_x: null,
          goal_z: null,
          steps: JSON.stringify(payload.steps),
          source: payload.source,
        },
      ];
    },
  },
  {
    subject: 'rabbit.nav.cancel',
    table: 'nav_events',
    toRows: (msg, receivedAt) => {
      const { text, payload } = json(Source, msg);
      return [
        {
          ts: commandTime(text, receivedAt),
          event: 'cancel',
          goal_x: null,
          goal_z: null,
          source: payload.source,
        },
      ];
    },
  },
  {
    subject: 'rabbit.explore.state',
    table: 'explore_state',
    toRows: (msg) => {
      const { text, payload } = json(ExploreState, msg);
      return [
        {
          ts: nanos(text),
          exploration_id: payload.exploration_id ?? '',
          phase: payload.phase,
          message: payload.message ?? '',
          elapsed_s: payload.elapsed_s ?? null,
          travelled_m: payload.travelled_m,
          max_duration_s: payload.limits.max_duration_s ?? null,
          max_distance_m: payload.limits.max_distance_m ?? null,
          frontiers: payload.frontiers,
          failed_frontiers: payload.failed_frontiers,
          target_x: payload.target?.x ?? null,
          target_z: payload.target?.z ?? null,
          target_path_m: payload.target?.path_length ?? null,
          planning_ms: payload.planning_ms ?? null,
          map_chunks: payload.map_chunks,
        },
      ];
    },
  },
  {
    subject: 'rabbit.operator.heartbeat',
    table: 'operator_heartbeat',
    toRows: (msg, receivedAt) => {
      const sent = commandTime(msg.string(), receivedAt);
      return [
        {
          ts: sent,
          round_trip_ms: Number(BigInt(receivedAt) - BigInt(sent)) / 1e6,
        },
      ];
    },
  },
  plannerStream(),
  commandEvent('rabbit.planner.goal'),
  commandEvent('rabbit.nav.explore'),
  commandEvent('rabbit.map.save'),
  commandEvent('rabbit.map.reset'),
  commandEvent('rabbit.safety.estop'),
  commandEvent('rabbit.safety.reset'),
  commandEvent('rabbit.power.request'),
  {
    subject: 'rabbit.health.lidar',
    table: 'lidar_health',
    toRows: (msg) => {
      const { text, payload } = json(LidarHealth, msg);
      return [
        {
          ts: nanos(text),
          ...payload,
          model: payload.model ?? null,
          firmware: payload.firmware ?? '',
          device_health: payload.device_health ?? '',
          error_code: payload.error_code ?? null,
          rotation_s: payload.rotation_s ?? null,
          scan_age_s: payload.scan_age_s ?? null,
        },
      ];
    },
  },
  {
    subject: 'rabbit.health.tof',
    table: 'tof_health',
    toRows: (msg) => {
      const { text, payload } = json(TofHealth, msg);
      return payload.sensors.map((sensor) => ({
        ts: nanos(text),
        ...sensor,
        frame_age_s: sensor.frame_age_s ?? null,
        valid: sensor.valid ?? null,
        floor: sensor.floor ?? null,
        overhead: sensor.overhead ?? null,
        nearest_m: sensor.nearest_m ?? null,
        init_s: sensor.init_s ?? null,
        power_cycles: payload.power_cycles,
      }));
    },
  },
  {
    subject: 'rabbit.safety.state',
    table: 'safety_state',
    toRows: (msg) => {
      const { text, payload } = json(SafetyState, msg);
      return [
        {
          ts: nanos(text),
          ...payload,
          estop_source: payload.estop_source ?? '',
          clearance_fwd_m: payload.clearance_fwd_m ?? null,
          clearance_rev_m: payload.clearance_rev_m ?? null,
          input_age_s: known(payload.input_age_s),
        },
      ];
    },
  },
  {
    subject: 'rabbit.power.state',
    table: 'power_state',
    toRows: (msg) => {
      const { text, payload } = json(PowerState, msg);
      return [
        {
          ts: nanos(text),
          ...payload,
          battery_v: payload.battery_v ?? null,
          charge_pct: payload.charge_pct ?? null,
          jetson_a: payload.jetson_a ?? null,
        },
      ];
    },
  },
  {
    subject: 'rabbit.map.chunks',
    table: 'map_chunks',
    toRows: (msg, receivedAt) => {
      const format = msg.headers?.get('format');
      if (format !== 'mesh') {
        throw new ForgeError('Map chunk is not a mesh', {
          internal: { format },
        });
      }
      return mapChunkRows(
        msg.data,
        msg.headers?.get('session') ?? '',
        receivedAt,
      );
    },
  },
];

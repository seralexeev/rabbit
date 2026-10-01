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
  ram: z.object({ used: z.number(), total: z.number() }),
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
});

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
  mission_id: z.string().nullish(),
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
    .object({ x: z.number(), z: z.number(), path_length: z.number() })
    .nullish(),
  planning_ms: z.number().nullish(),
  map_chunks: z.number(),
});

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
          rail_6v_voltage: rail.voltage,
          rail_6v_current: rail.current,
          rail_6v_power: rail.power,
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
      const [roll, pitch, yaw] = payload.euler_deg;
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
          roll_deg: roll,
          pitch_deg: pitch,
          yaw_deg: yaw,
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
          mission_id: payload.mission_id ?? '',
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
  commandEvent('rabbit.nav.explore'),
  commandEvent('rabbit.map.save'),
  commandEvent('rabbit.map.reset'),
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

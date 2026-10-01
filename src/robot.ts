import { type NatsConnection, connect } from '@nats-io/transport-node';
import z from 'zod';

import { reader, select } from './clickhouse.ts';
import { config } from './config.ts';
import { ForgeError, errorMessage } from './errors.ts';
import { forgeTool } from './forge_tool.ts';
import { startRun, stopRun } from './runs.ts';

const FLUSH_TIMEOUT_MS = 3000;
const MAX_STATUS_AGE_S = 3;
const MAX_STEP_M = 3;
const MAX_GOTO_M = 5;
const MAX_MISSION_M = 10;
const OBSTACLE_MARGIN_M = 0.3;

let connection: Promise<NatsConnection> | null = null;

const nats = async () => {
  if (connection == null) {
    const pending = connect({
      servers: config.natsUrl,
      name: 'forge-chat',
      timeout: 5000,
      maxReconnectAttempts: -1,
      reconnectTimeWait: 1000,
    });
    connection = pending;
    pending.then(
      (nc) => {
        void nc.closed().then(() => {
          if (connection === pending) {
            connection = null;
          }
        });
      },
      () => {
        if (connection === pending) {
          connection = null;
        }
      },
    );
  }
  try {
    return await connection;
  } catch (error) {
    throw new ForgeError('Robot is unreachable', {
      llm: 'Could not connect to the robot NATS server; the robot may be off or out of Wi-Fi range.',
      cause: error,
    });
  }
};

const withTimeout = async <T>(promise: Promise<T>, ms: number) => {
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          reject(
            new ForgeError('Robot did not confirm the command in time', {
              llm: 'The command may not have reached the robot; check robot_status.',
            }),
          );
        }, ms);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
};

const publish = async (subject: string, payload: object) => {
  const nc = await nats();
  nc.publish(
    subject,
    JSON.stringify({ ts: Date.now(), source: 'forge', ...payload }),
  );
  await withTimeout(nc.flush(), FLUSH_TIMEOUT_MS);
};

const Step = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('turn'),
    degrees: z
      .number()
      .min(-360)
      .max(360)
      .describe(
        'Relative heading change; positive turns right (clockwise from above), 180 turns around',
      ),
  }),
  z
    .object({
      type: z.literal('move'),
      forward: z
        .number()
        .min(-MAX_STEP_M)
        .max(MAX_STEP_M)
        .describe(
          'Metres forward from the pose where the step starts; negative reverses',
        ),
      right: z
        .number()
        .min(-MAX_STEP_M)
        .max(MAX_STEP_M)
        .describe('Metres to the right of that pose; negative is left'),
    })
    .refine((step) => Math.hypot(step.forward, step.right) <= MAX_STEP_M, {
      message: `A move step is at most ${MAX_STEP_M} m`,
    }),
  z.object({
    type: z.literal('goto'),
    x: z.number().describe('World x, m'),
    z: z.number().describe('World z, m'),
  }),
]);

type MissionStep = z.infer<typeof Step>;

const checkMission = async (steps: MissionStep[]) => {
  const status = await robotStatus();
  const pose = status.pose;
  if (pose == null || pose.age_s > MAX_STATUS_AGE_S) {
    throw new ForgeError('Robot pose is stale', {
      llm: 'Forge has no robot pose from the last 3 s, so the mission was not sent; check that the robot and the Forge writer are running.',
    });
  }
  if (status.camera?.pose_state !== 'OK') {
    throw new ForgeError('Camera tracking is not OK', {
      llm: 'Positional tracking is not OK, so the robot cannot follow a mission; wait for tracking to recover.',
    });
  }
  let total = 0;
  for (const step of steps) {
    if (step.type === 'move') {
      total += Math.hypot(step.forward, step.right);
    }
    if (step.type === 'goto') {
      const distance = Math.hypot(step.x - pose.x, step.z - pose.z);
      if (distance > MAX_GOTO_M) {
        throw new ForgeError('Goto target is too far', {
          llm: `A goto target must be within ${MAX_GOTO_M} m of the robot; this one is ${distance.toFixed(2)} m away.`,
        });
      }
      total += distance;
    }
  }
  if (total > MAX_MISSION_M) {
    throw new ForgeError('Mission is too long', {
      llm: `A mission may cover at most ${MAX_MISSION_M} m in total; this one covers about ${total.toFixed(1)} m.`,
    });
  }
  const [first] = steps;
  const ahead = status.obstacle?.ahead_distance;
  if (
    first?.type === 'move' &&
    first.forward > 0 &&
    ahead != null &&
    ahead < first.forward + OBSTACLE_MARGIN_M
  ) {
    throw new ForgeError('Obstacle ahead', {
      llm: `There is an obstacle ${ahead.toFixed(2)} m ahead, too close for a ${first.forward} m move; the mission was not sent.`,
    });
  }
  return { pose, obstacle: status.obstacle };
};

const obstaclePoints = (obstacle: ObstacleSection | null) =>
  obstacle == null
    ? []
    : (
        [
          [obstacle.nearest_x, obstacle.nearest_z],
          [obstacle.ahead_x, obstacle.ahead_z],
        ] as const
      ).flatMap(([x, z]) => (x == null || z == null ? [] : [{ x, z }]));

export const runMissionTool = forgeTool({
  title: 'Run mission',
  description:
    "Sends the robot a mission: an ordered list of steps it executes on board, replacing any current mission. Steps: turn {degrees} (relative, + is right, 180 turns around), move {forward, right} (metres relative to the pose when the step starts, at most 3 m per step), goto {x, z} (world metres from robot_status, within 5 m). At most 10 steps and 10 m in total. Translate the user's words into the fewest steps, for example 'turn around and drive 1 m forward slightly to the right' is [turn 180, move forward 1.0 right 0.15]. The operator must approve the mission; Forge re-checks the pose, tracking and the obstacle ahead before sending. Use stop to cancel.",
  input: z.object({ steps: z.array(Step).min(1).max(10) }),
  requiresApproval: true,
  run: async ({ steps }) => {
    const { pose, obstacle } = await checkMission(steps);
    await publish('rabbit.nav.mission', { steps });
    return {
      ok: true,
      published: 'rabbit.nav.mission',
      steps,
      start: { x: pose.x, z: pose.z, heading_deg: pose.heading_deg },
      obstacles: obstaclePoints(obstacle),
    };
  },
  forModel: ({ start: _start, obstacles: _obstacles, ...sent }) => sent,
});

export const stopTool = forgeTool({
  title: 'Stop',
  description:
    'Stops the robot immediately: cancels the mission queue and commands zero speed. Needs no approval; use it whenever the user says stop.',
  input: z.object({}),
  run: async () => {
    const results = await Promise.allSettled([
      publish('rabbit.nav.cancel', {}),
      publish('rabbit.cmd.drive', { speed: 0, steer: 0 }),
    ]);
    const report = {
      cancel:
        results[0].status === 'fulfilled'
          ? 'sent'
          : errorMessage(results[0].reason),
      zero_drive:
        results[1].status === 'fulfilled'
          ? 'sent'
          : errorMessage(results[1].reason),
    };
    if (results.every((result) => result.status === 'rejected')) {
      throw new ForgeError('Stop could not be sent', {
        llm: 'Neither the cancel nor the zero-speed command reached the robot; use the physical stop.',
        internal: report,
      });
    }
    return { ok: true, ...report };
  },
});

export const saveMapTool = forgeTool({
  title: 'Save map',
  description:
    'Asks the ZED node to save the current spatial map and area file on the robot.',
  input: z.object({}),
  run: async () => {
    await publish('rabbit.map.save', {});
    return { ok: true, published: 'rabbit.map.save' };
  },
});

export const startRunTool = forgeTool({
  title: 'Start run',
  description:
    'Starts recording a named run in Forge; data from now on is tagged with it.',
  input: z.object({
    name: z.string().min(1),
    note: z.string().default(''),
  }),
  run: async ({ name, note }) => ({
    ok: true,
    run_id: await startRun(name, note),
  }),
});

export const stopRunTool = forgeTool({
  title: 'Stop run',
  description: 'Stops the run that is recording.',
  input: z.object({}),
  run: async () => ({ ok: true, run_id: await stopRun() }),
});

const LIVE_MAX_AGE_S = 5;

type ObstacleSection = Section & {
  ahead_distance: Num;
  nearest_x: Num;
  nearest_z: Num;
  ahead_x: Num;
  ahead_z: Num;
};

type Section = Record<string, unknown> & {
  age_s: number;
  source: 'live' | 'recorded';
};

type Num = number | null;

const num = (value: unknown, digits = 3): Num =>
  typeof value === 'number' && Number.isFinite(value)
    ? Math.round(value * 10 ** digits) / 10 ** digits
    : null;

type Json = Record<string, unknown>;

const field = (value: unknown, key: string): unknown =>
  value != null && typeof value === 'object' ? (value as Json)[key] : undefined;

const headingDeg = (orientation: unknown) => {
  const [x, y, z, w] = Array.isArray(orientation)
    ? orientation.map(Number)
    : [];
  if (x == null || y == null || z == null || w == null) {
    return null;
  }
  return num(
    (Math.atan2(-2 * (x * z + w * y), 1 - 2 * (x * x + y * y)) * 180) / Math.PI,
    1,
  );
};

const pointXz = (contact: unknown) => {
  const point = field(contact, 'point');
  return Array.isArray(point) ? [num(point[0]), num(point[2])] : [null, null];
};

const LIVE_SECTIONS = {
  pose: {
    subject: 'rabbit.zed.pose',
    read: (p) => {
      const [x, y, z] =
        (field(p, 'translation') as unknown[] | undefined) ?? [];
      const [vx, vy, vz] = (
        (field(p, 'velocity') as unknown[] | undefined) ?? []
      ).map(Number);
      return {
        x: num(x),
        y: num(y),
        z: num(z),
        yaw_deg: num((field(p, 'euler_deg') as unknown[] | undefined)?.[2], 1),
        heading_deg: headingDeg(field(p, 'orientation')),
        speed_mps: num(
          Math.hypot(vx ?? Number.NaN, vy ?? Number.NaN, vz ?? Number.NaN),
        ),
        confidence: num(field(p, 'confidence'), 0),
      };
    },
  },
  nav: {
    subject: 'rabbit.nav.state',
    read: (p) => ({
      mode: field(p, 'mode') ?? null,
      goal_x: num(field(field(p, 'goal'), 'x')),
      goal_z: num(field(field(p, 'goal'), 'z')),
      distance_to_goal: num(field(p, 'distance_to_goal')),
      heading_error_deg: num(field(p, 'heading_error_deg'), 1),
      step_type: field(field(p, 'step'), 'type') ?? '',
      step_index: num(field(p, 'step_index'), 0) ?? 0,
      steps_total: num(field(p, 'steps_total'), 0) ?? 0,
      turn_remaining_deg: num(field(p, 'turn_remaining_deg'), 1),
    }),
  },
  battery: {
    subject: 'rabbit.ina',
    read: (p) => {
      const channels = (field(p, 'channels') as unknown[] | undefined) ?? [];
      const battery = channels.find(
        (channel) => field(channel, 'name') === 'battery',
      );
      return {
        voltage: num(field(battery, 'voltage'), 2),
        current_a: num(field(battery, 'current'), 2),
        charge_pct: num(field(p, 'battery_charge_pct'), 1),
      };
    },
  },
  obstacle: {
    subject: 'rabbit.zed.obstacle',
    read: (p) => {
      const [nearestX, nearestZ] = pointXz(field(p, 'nearest'));
      const [aheadX, aheadZ] = pointXz(field(p, 'ahead'));
      return {
        nearest_distance: num(field(field(p, 'nearest'), 'distance')),
        nearest_bearing_deg: num(field(field(p, 'nearest'), 'bearing_deg'), 1),
        nearest_x: nearestX,
        nearest_z: nearestZ,
        ahead_distance: num(field(field(p, 'ahead'), 'distance')),
        ahead_bearing_deg: num(field(field(p, 'ahead'), 'bearing_deg'), 1),
        ahead_x: aheadX,
        ahead_z: aheadZ,
      };
    },
  },
  camera: {
    subject: 'rabbit.health.zed',
    read: (p) => ({
      current_fps: num(field(p, 'current_fps'), 1),
      pose_state: field(p, 'last_pose_state') ?? null,
      tracking_state: field(p, 'tracking_fusion_status') ?? null,
      spatial_memory_status: field(p, 'spatial_memory_status') ?? null,
      camera_moving_state: field(p, 'camera_moving_state') ?? null,
      temp_imu: num(field(field(p, 'temperature'), 'imu'), 1),
    }),
  },
} satisfies Record<string, { subject: string; read: (payload: Json) => Json }>;

type SectionName = keyof typeof LIVE_SECTIONS;

const liveLatest = new Map<string, { payload: Json; receivedAt: number }>();

let liveStarted = false;

export const startLiveStatus = () => {
  if (liveStarted) {
    return;
  }
  liveStarted = true;
  nats()
    .then((nc) => {
      for (const { subject } of Object.values(LIVE_SECTIONS)) {
        nc.subscribe(subject, {
          callback: (error, msg) => {
            if (error != null) {
              return;
            }
            try {
              liveLatest.set(subject, {
                payload: msg.json<Json>(),
                receivedAt: Date.now(),
              });
            } catch {
              return;
            }
          },
        });
      }
    })
    .catch(() => {
      liveStarted = false;
    });
};

const AGE = "dateDiff('millisecond', ts, now64(3)) / 1000 AS age_s";
const RECENT =
  'WHERE ts > now64(3) - INTERVAL 10 MINUTE ORDER BY ts DESC LIMIT 1';

const RECORDED: Record<SectionName, string> = {
  pose: `SELECT round(x, 3) AS x, round(y, 3) AS y, round(z, 3) AS z, round(yaw_deg, 1) AS yaw_deg, round(degrees(atan2(-2 * (qx * qz + qw * qy), 1 - 2 * (qx * qx + qy * qy))), 1) AS heading_deg, round(sqrt(vx * vx + vy * vy + vz * vz), 3) AS speed_mps, confidence, ${AGE} FROM pose ${RECENT}`,
  nav: `SELECT mode, goal_x, goal_z, round(distance_to_goal, 3) AS distance_to_goal, heading_error_deg, step_type, step_index, steps_total, turn_remaining_deg, ${AGE} FROM nav_state ${RECENT}`,
  battery: `SELECT round(battery_voltage, 2) AS voltage, round(battery_current, 2) AS current_a, battery_charge_pct AS charge_pct, ${AGE} FROM power ${RECENT}`,
  obstacle: `SELECT nearest_distance, nearest_bearing_deg, round(nearest_x, 3) AS nearest_x, round(nearest_z, 3) AS nearest_z, ahead_distance, ahead_bearing_deg, round(ahead_x, 3) AS ahead_x, round(ahead_z, 3) AS ahead_z, ${AGE} FROM obstacle ${RECENT}`,
  camera: `SELECT current_fps, pose_state, tracking_state, spatial_memory_status, camera_moving_state, temp_imu, ${AGE} FROM zed_health ${RECENT}`,
};

const section = async (
  name: SectionName,
  notes: string[],
): Promise<Section | null> => {
  const spec = LIVE_SECTIONS[name];
  const live = liveLatest.get(spec.subject);
  const liveAge = live == null ? null : (Date.now() - live.receivedAt) / 1000;
  if (live != null && liveAge != null && liveAge <= LIVE_MAX_AGE_S) {
    return {
      ...spec.read(live.payload),
      age_s: num(liveAge, 2) ?? 0,
      source: 'live',
    };
  }
  try {
    const [row] = await select<Json & { age_s: number }>(
      reader,
      RECORDED[name],
    );
    if (row == null) {
      notes.push(`${name}: no live or recorded data in the last 10 minutes`);
      return null;
    }
    notes.push(
      `${name}: no live message in ${LIVE_MAX_AGE_S} s, showing the last recorded sample`,
    );
    return { ...row, source: 'recorded' };
  } catch (error) {
    notes.push(`${name}: unavailable (${errorMessage(error).slice(0, 120)})`);
    return null;
  }
};

const robotStatus = async () => {
  startLiveStatus();
  const notes: string[] = [];
  const [pose, nav, battery, obstacle, camera] = await Promise.all(
    (['pose', 'nav', 'battery', 'obstacle', 'camera'] as const).map(
      async (name) => await section(name, notes),
    ),
  );
  return {
    kind: 'status' as const,
    pose: pose as (Section & { x: number; z: number; heading_deg: Num }) | null,
    nav,
    battery,
    obstacle: obstacle as ObstacleSection | null,
    camera: camera as (Section & { pose_state: unknown }) | null,
    notes,
  };
};

export const robotStatusTool = forgeTool({
  title: 'Robot status',
  description:
    'Latest robot state: pose (world x, y, z, yaw, and heading_deg where 0 faces world -z and positive turns right), mission and navigation state, battery, obstacles and camera tracking health, each with its age in seconds and source (live from the robot, or the last recorded sample when no live message arrived). A section is null when neither is available; notes explain any degraded section.',
  input: z.object({}),
  run: robotStatus,
});

export const ROBOT_TOOLS = {
  robot_status: robotStatusTool,
  run_mission: runMissionTool,
  stop: stopTool,
  save_map: saveMapTool,
  start_run: startRunTool,
  stop_run: stopRunTool,
};

import { type NatsConnection, connect } from '@nats-io/transport-node';
import { randomUUID } from 'node:crypto';
import z from 'zod';

import { config } from './config.ts';
import { ForgeError, errorMessage } from './errors.ts';
import { forgeTool } from './forge_tool.ts';
import { startRun, stopRun } from './runs.ts';
import { select } from './store/engine.ts';
import { ZED_EULER } from './streams.ts';

const FLUSH_TIMEOUT_MS = 3000;
const MAX_STATUS_AGE_S = 3;
const MAX_STEP_M = 3;
const MAX_GOTO_M = 5;
const MAX_MISSION_M = 10;
const OBSTACLE_MARGIN_M = 0.3;
const MISSION_ACK_MS = 3000;
const MISSION_ACK_POLL_MS = 100;
const NAV_STATE_SUBJECT = 'rabbit.nav.state';
const PLANNER_STATE_SUBJECT = 'rabbit.planner.state';
const PLANNER_GOAL_SUBJECT = 'rabbit.planner.goal';
const PLACES_SUBJECT = 'rabbit.planner.places';
const PLACE_SAVE_SUBJECT = 'rabbit.planner.places.save';
const PLANNER_REPLY_MS = 3000;
const TRIP_START_MS = 6000;
const TRIP_POLL_MS = 100;
const MAX_ROUTE_POINTS = 120;

let connection: Promise<NatsConnection> | null = null;
let liveStarted = false;

const nats = async () => {
  if (connection == null) {
    const pending = connect({
      servers: config.natsUrl,
      name: 'forge-chat',
      pingInterval: config.natsPingIntervalMs,
      maxPingOut: config.natsMaxPingOut,
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
            liveStarted = false;
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

type Pose2d = { x: number; z: number; heading_deg: number };

const MAX_AHEAD_HEADING_DEG = 10;

const radians = (degrees: number) => (degrees * Math.PI) / 180;

const wrapDegrees = (degrees: number) =>
  ((((degrees + 180) % 360) + 360) % 360) - 180;

export const planMission = (start: Pose2d, steps: MissionStep[]) => {
  let pose = start;
  let total = 0;
  let firstLeg: { forward: number; turned_deg: number } | null = null;
  for (const step of steps) {
    if (step.type === 'turn') {
      pose = { ...pose, heading_deg: pose.heading_deg + step.degrees };
      continue;
    }
    const h = radians(pose.heading_deg);
    const target =
      step.type === 'move'
        ? {
            x: pose.x + step.forward * Math.sin(h) + step.right * Math.cos(h),
            z: pose.z - step.forward * Math.cos(h) + step.right * Math.sin(h),
          }
        : { x: step.x, z: step.z };
    const dx = target.x - pose.x;
    const dz = target.z - pose.z;
    const distance = Math.hypot(dx, dz);
    if (step.type === 'goto' && distance > MAX_GOTO_M) {
      throw new ForgeError('Goto target is too far', {
        llm: `A goto target must be within ${MAX_GOTO_M} m of where the robot is when that step starts; this one is ${distance.toFixed(2)} m away.`,
      });
    }
    if (distance === 0) {
      continue;
    }
    const forward = dx * Math.sin(h) - dz * Math.cos(h);
    firstLeg ??= {
      forward,
      turned_deg: wrapDegrees(pose.heading_deg - start.heading_deg),
    };
    total += distance;
    const reversing = step.type === 'move' && step.forward < 0;
    pose = {
      ...target,
      heading_deg:
        (Math.atan2(reversing ? -dx : dx, reversing ? dz : -dz) * 180) /
        Math.PI,
    };
  }
  if (total > MAX_MISSION_M) {
    throw new ForgeError('Mission is too long', {
      llm: `A mission may cover at most ${MAX_MISSION_M} m in total; this one covers about ${total.toFixed(1)} m.`,
    });
  }
  return { total, firstLeg };
};

const isFresh = (section: Section | null) =>
  section != null && section.age_s <= MAX_STATUS_AGE_S;

const checkMission = async (steps: MissionStep[]) => {
  const status = await robotStatus();
  const pose = status.pose;
  if (
    pose == null ||
    !isFresh(pose) ||
    pose.x == null ||
    pose.z == null ||
    pose.heading_deg == null
  ) {
    throw new ForgeError('Robot pose is stale', {
      llm: 'Forge has no complete robot pose from the last 3 s, so the mission was not sent; check that the robot and the Forge writer are running.',
    });
  }
  if (!isFresh(status.camera) || status.camera?.pose_state !== 'OK') {
    throw new ForgeError('Camera tracking is not OK', {
      llm: 'Positional tracking is not reported OK within the last 3 s, so the robot cannot follow a mission; wait for tracking to recover.',
    });
  }
  if (!isFresh(status.obstacle)) {
    throw new ForgeError('Obstacle data is stale', {
      llm: 'Forge has no obstacle reading from the last 3 s, so it cannot check the path ahead; the mission was not sent.',
    });
  }
  const start = { x: pose.x, z: pose.z, heading_deg: pose.heading_deg };
  const { firstLeg } = planMission(start, steps);
  const ahead = status.obstacle?.ahead_distance;
  if (
    firstLeg != null &&
    Math.abs(firstLeg.turned_deg) <= MAX_AHEAD_HEADING_DEG &&
    firstLeg.forward > 0 &&
    ahead != null &&
    ahead < firstLeg.forward + OBSTACLE_MARGIN_M
  ) {
    throw new ForgeError('Obstacle ahead', {
      llm: `There is an obstacle ${ahead.toFixed(2)} m ahead, too close for the first ${firstLeg.forward.toFixed(2)} m forward leg; the mission was not sent.`,
    });
  }
  return { pose: start, obstacle: status.obstacle };
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

type MissionOutcome =
  | { status: 'accepted' }
  | { status: 'rejected'; fault: string }
  | { status: 'pending' };

export const missionOutcome = (
  missionId: string,
  sentAt: number,
  faultBefore: unknown,
  state: { payload: Json; receivedAt: number } | undefined,
): MissionOutcome => {
  if (state == null || state.receivedAt <= sentAt) {
    return { status: 'pending' };
  }
  if (field(state.payload, 'mission_id') === missionId) {
    return { status: 'accepted' };
  }
  const fault = field(state.payload, 'fault');
  return typeof fault === 'string' &&
    fault.startsWith('rejected') &&
    fault !== faultBefore
    ? { status: 'rejected', fault }
    : { status: 'pending' };
};

const awaitMission = async (
  missionId: string,
  sentAt: number,
  faultBefore: unknown,
) => {
  const deadline = sentAt + MISSION_ACK_MS;
  for (;;) {
    const outcome = missionOutcome(
      missionId,
      sentAt,
      faultBefore,
      liveLatest.get(NAV_STATE_SUBJECT),
    );
    if (outcome.status === 'accepted' || Date.now() >= deadline) {
      return outcome;
    }
    await new Promise((resolve) => setTimeout(resolve, MISSION_ACK_POLL_MS));
  }
};

export const runMissionTool = forgeTool({
  title: 'Run mission',
  description:
    "Sends the robot a mission: an ordered list of steps it executes on board, replacing any current mission. Steps: turn {degrees} (relative, + is right, 180 turns around), move {forward, right} (metres relative to the pose when the step starts, at most 3 m per step), goto {x, z} (world metres from robot_status, within 5 m). At most 10 steps and 10 m in total. Translate the user's words into the fewest steps, for example 'turn around and drive 1 m forward slightly to the right' is [turn 180, move forward 1.0 right 0.15]. The operator must approve the mission; Forge re-checks the pose, tracking and the obstacle ahead before sending, then waits up to 3 s for navigation to adopt the mission_id: accepted true means it is executing, false means no confirmation yet (check robot_status), and a refusal fails with the reason. Use stop to cancel.",
  input: z.object({ steps: z.array(Step).min(1).max(10) }),
  requiresApproval: true,
  run: async ({ steps }) => {
    const { pose, obstacle } = await checkMission(steps);
    const missionId = `forge-${randomUUID()}`;
    const faultBefore = field(
      liveLatest.get(NAV_STATE_SUBJECT)?.payload,
      'fault',
    );
    const sentAt = Date.now();
    await publish('rabbit.nav.mission', { id: missionId, steps });
    const outcome = await awaitMission(missionId, sentAt, faultBefore);
    if (outcome.status === 'rejected') {
      throw new ForgeError('Robot rejected the mission', {
        llm: `Navigation refused the mission (${outcome.fault}), so it was not started.`,
        internal: { missionId, fault: outcome.fault },
      });
    }
    return {
      ok: true,
      published: 'rabbit.nav.mission',
      mission_id: missionId,
      accepted: outcome.status === 'accepted',
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

export const resetMapTool = forgeTool({
  title: 'Reset map',
  description:
    "Discards the robot's saved room map and restarts the camera with an empty one. The old map is archived on the robot, not deleted. The camera is unavailable for about 10 seconds while it restarts, so the robot must not be driving.",
  input: z.object({}),
  requiresApproval: true,
  run: async () => {
    await publish('rabbit.map.reset', { source: 'forge' });
    return { ok: true, published: 'rabbit.map.reset' };
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
        yaw_deg: num(
          (field(p, 'euler_deg') as unknown[] | undefined)?.[ZED_EULER.yaw],
          1,
        ),
        heading_deg: headingDeg(field(p, 'orientation')),
        speed_mps: num(
          Math.hypot(vx ?? Number.NaN, vy ?? Number.NaN, vz ?? Number.NaN),
        ),
        confidence: num(field(p, 'confidence'), 0),
      };
    },
  },
  nav: {
    subject: NAV_STATE_SUBJECT,
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
      fault: field(p, 'fault') ?? null,
      mission_id: field(p, 'mission_id') ?? null,
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
  objects: {
    subject: 'rabbit.zed.objects',
    read: (p) => ({
      in_view: ((field(p, 'objects') as unknown[] | undefined) ?? []).map(
        (object) => {
          const [x, , z] =
            (field(object, 'position') as number[] | undefined) ?? [];
          return {
            label: field(object, 'label') ?? null,
            x: num(x, 2),
            z: num(z, 2),
            confidence: num(field(object, 'confidence'), 0),
          };
        },
      ),
    }),
  },
  trip: {
    subject: PLANNER_STATE_SUBJECT,
    read: (p) => ({
      phase: field(p, 'phase') ?? null,
      trip_id: field(p, 'trip_id') ?? null,
      target:
        field(field(p, 'target'), 'label') ??
        field(field(p, 'target'), 'kind') ??
        null,
      target_x: num(field(field(p, 'target'), 'x'), 2),
      target_z: num(field(field(p, 'target'), 'z'), 2),
      remaining_m: num(field(p, 'remaining_m'), 2),
      path_length_m: num(field(p, 'path_length_m'), 2),
      replans: num(field(p, 'replans'), 0),
      recoveries: num(field(p, 'recoveries'), 0),
      message: field(p, 'message') ?? null,
    }),
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
  nav: `SELECT mode, goal_x, goal_z, round(distance_to_goal, 3) AS distance_to_goal, heading_error_deg, step_type, step_index, steps_total, turn_remaining_deg, fault, mission_id, ${AGE} FROM nav_state ${RECENT}`,
  battery: `SELECT round(battery_voltage, 2) AS voltage, round(battery_current, 2) AS current_a, battery_charge_pct AS charge_pct, ${AGE} FROM power ${RECENT}`,
  obstacle: `SELECT nearest_distance, nearest_bearing_deg, round(nearest_x, 3) AS nearest_x, round(nearest_z, 3) AS nearest_z, ahead_distance, ahead_bearing_deg, round(ahead_x, 3) AS ahead_x, round(ahead_z, 3) AS ahead_z, ${AGE} FROM obstacle ${RECENT}`,
  objects: `SELECT groupArray(CAST((label, round(x, 2), round(z, 2), round(confidence)), 'Tuple(label String, x Float32, z Float32, confidence Float32)')) AS in_view, dateDiff('millisecond', max(ts), now64(3)) / 1000 AS age_s FROM objects WHERE ts = (SELECT max(ts) FROM objects WHERE ts > now64(3) - INTERVAL 10 MINUTE) HAVING count() > 0`,
  trip: `SELECT phase, trip_id, if(target_label = '', target_kind, target_label) AS target, round(target_x, 2) AS target_x, round(target_z, 2) AS target_z, round(remaining_m, 2) AS remaining_m, round(path_length_m, 2) AS path_length_m, replans, recoveries, message, ${AGE} FROM planner_state ${RECENT}`,
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
    const [row] = await select<Json & { age_s: number }>(RECORDED[name]);
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
  const [pose, nav, trip, battery, obstacle, objects, camera] =
    await Promise.all(
      (
        [
          'pose',
          'nav',
          'trip',
          'battery',
          'obstacle',
          'objects',
          'camera',
        ] as const
      ).map(async (name) => await section(name, notes)),
    );
  return {
    kind: 'status' as const,
    pose: pose as (Section & { x: Num; z: Num; heading_deg: Num }) | null,
    nav,
    trip,
    battery,
    obstacle: obstacle as ObstacleSection | null,
    objects,
    camera: camera as (Section & { pose_state: unknown }) | null,
    notes,
  };
};

export const robotStatusTool = forgeTool({
  title: 'Robot status',
  description:
    'Latest robot state: pose (world x, y, z, yaw, and heading_deg where 0 faces world -z and positive turns right), mission and navigation state, the planned trip (go_to: phase, target, metres left, replans, status message), battery, obstacles, the objects the detector sees right now (label, world x and z, confidence 0..100) and camera tracking health, each with its age in seconds and source (live from the robot, or the last recorded sample when no live message arrived). A section is null when neither is available; notes explain any degraded section.',
  input: z.object({}),
  run: robotStatus,
});

export const DETECTOR_CLASSES = [
  'person',
  'cat',
  'dog',
  'robot vacuum',
  'chair',
  'office chair',
  'stool',
  'sofa',
  'armchair',
  'bed',
  'dining table',
  'coffee table',
  'desk',
  'nightstand',
  'tv stand',
  'low wooden cabinet',
  'wardrobe',
  'cabinet',
  'chest of drawers',
  'shelf',
  'bookshelf',
  'kitchen island',
  'refrigerator',
  'oven',
  'stove',
  'microwave',
  'kettle',
  'washing machine',
  'dishwasher',
  'sink',
  'toilet',
  'bathtub',
  'shower',
  'television',
  'computer monitor',
  'laptop',
  'lamp',
  'floor lamp',
  'potted plant',
  'door',
  'mirror',
  'radiator',
  'fan',
  'air conditioner',
  'trash can',
  'laundry basket',
  'box',
  'bag',
  'backpack',
  'suitcase',
  'shoe',
  'bottle',
  'cup',
  'pillow',
  'rug',
  'curtain',
  'picture frame',
  'clock',
];

const ALIASES: Record<string, string[]> = {
  fridge: ['refrigerator'],
  freezer: ['refrigerator'],
  tv: ['television'],
  telly: ['television'],
  couch: ['sofa'],
  settee: ['sofa'],
  table: ['dining table', 'coffee table', 'desk'],
  bin: ['trash can'],
  trash: ['trash can'],
  rubbish: ['trash can'],
  garbage: ['trash can'],
  plant: ['potted plant'],
  monitor: ['computer monitor'],
  screen: ['computer monitor', 'television'],
  washer: ['washing machine'],
  vacuum: ['robot vacuum'],
  roomba: ['robot vacuum'],
  cooker: ['oven', 'stove'],
  hob: ['stove'],
  closet: ['wardrobe'],
  drawers: ['chest of drawers'],
  bookcase: ['bookshelf'],
  bath: ['bathtub'],
  tub: ['bathtub'],
  island: ['kitchen island'],
  basket: ['laundry basket'],
  ac: ['air conditioner'],
};

export const ROOMS: Record<string, string[]> = {
  kitchen: [
    'refrigerator',
    'oven',
    'stove',
    'microwave',
    'kettle',
    'dishwasher',
    'kitchen island',
  ],
  bathroom: ['toilet', 'bathtub', 'shower'],
  toilet: ['toilet'],
  bedroom: ['bed', 'wardrobe', 'nightstand', 'chest of drawers'],
  'living room': ['sofa', 'television', 'coffee table', 'armchair', 'tv stand'],
  lounge: ['sofa', 'television', 'coffee table', 'armchair', 'tv stand'],
  laundry: ['washing machine', 'laundry basket'],
  office: ['desk', 'office chair', 'computer monitor'],
  study: ['desk', 'office chair', 'computer monitor'],
  'dining room': ['dining table'],
};

const normalize = (text: string) =>
  text
    .trim()
    .toLowerCase()
    .replace(/^(the|a|an|my|our)\s+/, '')
    .replaceAll(/\s+/g, ' ');

export const labelsFor = (query: string): string[] => {
  const name = normalize(query);
  const candidates = [name, name.replace(/s$/, ''), name.replace(/es$/, '')];
  for (const candidate of candidates) {
    if (DETECTOR_CLASSES.includes(candidate)) {
      return [candidate];
    }
    const alias = ALIASES[candidate];
    if (alias != null) {
      return alias;
    }
  }
  return [];
};

export type Sighting = {
  label: string;
  x: number;
  z: number;
  width: number;
  length: number;
  frames: number;
  confidence: number;
  last_seen: string;
};

const MERGE_M = 0.8;

export const confirmedSighting = (sighting: Sighting) =>
  sighting.frames >= 10 || (sighting.frames >= 3 && sighting.confidence >= 55);

export const clusterSightings = (cells: Sighting[]): Sighting[] => {
  const parent = cells.map((_, i) => i);
  const root = (i: number): number => {
    let r = i;
    while (parent[r] !== r) {
      r = parent[r] ?? r;
    }
    return r;
  };
  for (const [i, a] of cells.entries()) {
    for (const [j, b] of cells.entries()) {
      if (
        j > i &&
        a.label === b.label &&
        Math.hypot(a.x - b.x, a.z - b.z) <= MERGE_M
      ) {
        parent[root(j)] = root(i);
      }
    }
  }
  const groups = new Map<number, Sighting[]>();
  for (const [i, cell] of cells.entries()) {
    groups.set(root(i), [...(groups.get(root(i)) ?? []), cell]);
  }
  return [...groups.values()]
    .map((group) => {
      const frames = group.reduce((sum, cell) => sum + cell.frames, 0);
      const mean = (key: 'x' | 'z' | 'width' | 'length') =>
        group.reduce((sum, cell) => sum + cell[key] * cell.frames, 0) / frames;
      return {
        label: group[0]?.label ?? '',
        x: num(mean('x'), 2) ?? 0,
        z: num(mean('z'), 2) ?? 0,
        width: num(mean('width'), 2) ?? 0,
        length: num(mean('length'), 2) ?? 0,
        frames,
        confidence: Math.max(...group.map((cell) => cell.confidence)),
        last_seen:
          group
            .map((cell) => cell.last_seen)
            .toSorted()
            .at(-1) ?? '',
      };
    })
    .toSorted((a, b) => b.frames - a.frames);
};

const MAP_EPOCH = `WITH greatest(
  ifNull((
    SELECT max(ts) FROM logs
    WHERE node = 'rabbit-zed'
      AND (message LIKE 'Archived%' OR message LIKE 'Restarting the camera process: map reset%')
  ), toDateTime64(0, 9, 'UTC')),
  ifNull((SELECT max(ts) FROM command_events WHERE subject = 'rabbit.map.reset'), toDateTime64(0, 9, 'UTC')),
  fromUnixTimestamp64Nano(toInt64({map_ns:UInt64}), 'UTC')
) AS epoch`;

const SIGHTINGS_SQL = `
${MAP_EPOCH}
SELECT
  label,
  avg(x) AS cell_x,
  avg(z) AS cell_z,
  quantile(0.5)(width) AS cell_width,
  quantile(0.5)(length) AS cell_length,
  count() AS frames,
  round(max(confidence)) AS best_confidence,
  toString(max(ts)) AS seen
FROM (
  SELECT o.ts AS ts, o.label AS label, o.x AS x, o.z AS z, o.width AS width, o.length AS length, o.confidence AS confidence
  FROM (
    SELECT run_id, ts, label, x, z, width, length, confidence FROM objects
    WHERE ts > epoch AND label IN {labels:Array(String)} AND confidence >= {min_confidence:Float32}
  ) AS o
  ASOF JOIN (SELECT run_id, ts, spatial_memory_status FROM zed_health WHERE ts > epoch) AS h
    ON o.run_id = h.run_id AND o.ts >= h.ts
  WHERE h.spatial_memory_status NOT IN ('INITIALIZING', 'SEARCHING')
)
GROUP BY label, round(x / 0.4), round(z / 0.4)
HAVING frames >= 3`;

const SEEN_FROM_SQL = `
${MAP_EPOCH}
SELECT o.x AS object_x, o.z AS object_z, p.x AS camera_x, p.z AS camera_z, o.confidence AS confidence
FROM (
  SELECT run_id, ts, x, z, confidence FROM objects
  WHERE ts > epoch AND label = {label:String} AND confidence >= {min_confidence:Float32}
) AS o
ASOF JOIN (SELECT run_id, ts, x, z FROM pose WHERE ts > epoch) AS p ON o.run_id = p.run_id AND o.ts >= p.ts
ASOF JOIN (SELECT run_id, ts, spatial_memory_status FROM zed_health WHERE ts > epoch) AS h
  ON o.run_id = h.run_id AND o.ts >= h.ts
WHERE h.spatial_memory_status NOT IN ('INITIALIZING', 'SEARCHING')
ORDER BY confidence DESC
LIMIT 2000`;

const SEEN_FROM_RADIUS_M = 0.8;
const SEEN_FROM_CELL_M = 0.3;
const MAX_SEEN_FROM = 12;

export const seenFromSpots = (
  rows: Array<{
    object_x: number;
    object_z: number;
    camera_x: number;
    camera_z: number;
  }>,
  center: { x: number; z: number },
) => {
  const spots = new Map<string, [number, number]>();
  for (const row of rows) {
    if (
      Math.hypot(row.object_x - center.x, row.object_z - center.z) >
        SEEN_FROM_RADIUS_M ||
      spots.size >= MAX_SEEN_FROM
    ) {
      continue;
    }
    const key = `${Math.round(row.camera_x / SEEN_FROM_CELL_M)}:${Math.round(row.camera_z / SEEN_FROM_CELL_M)}`;
    if (!spots.has(key)) {
      spots.set(key, [num(row.camera_x, 2) ?? 0, num(row.camera_z, 2) ?? 0]);
    }
  }
  return [...spots.values()];
};

const seenFrom = async (sighting: Sighting) =>
  seenFromSpots(
    await select<{
      object_x: number;
      object_z: number;
      camera_x: number;
      camera_z: number;
    }>(SEEN_FROM_SQL, {
      label: sighting.label,
      min_confidence: 50,
      map_ns: mapCreatedNs(),
    }),
    sighting,
  );

const mapCreatedNs = () => {
  const mapId = field(liveLatest.get('rabbit.health.zed')?.payload, 'map_id');
  return typeof mapId === 'string' && /^\d+$/.test(mapId) ? mapId : '0';
};

type SightingRow = {
  label: string;
  cell_x: number;
  cell_z: number;
  cell_width: number;
  cell_length: number;
  frames: number | string;
  best_confidence: number;
  seen: string;
};

const sightings = async (labels: string[]) =>
  clusterSightings(
    (
      await select<SightingRow>(SIGHTINGS_SQL, {
        labels,
        min_confidence: 40,
        map_ns: mapCreatedNs(),
      })
    ).map((row) => ({
      label: row.label,
      x: row.cell_x,
      z: row.cell_z,
      width: row.cell_width,
      length: row.cell_length,
      frames: Number(row.frames),
      confidence: row.best_confidence,
      last_seen: row.seen,
    })),
  ).filter(confirmedSighting);

const Place = z.object({
  name: z.string(),
  x: z.number(),
  z: z.number(),
  heading_deg: z.number().nullish(),
  current_map: z.boolean().default(true),
});

const PlannerReply = z.object({
  ok: z.boolean(),
  error: z.string().nullish(),
  place: Place.partial().nullish(),
  places: z.array(Place).default([]),
});

const plannerRequest = async (subject: string, payload: object) => {
  const nc = await nats();
  let reply;
  try {
    reply = await nc.request(
      subject,
      JSON.stringify({ ts: Date.now(), source: 'forge', ...payload }),
      { timeout: PLANNER_REPLY_MS },
    );
  } catch (error) {
    throw new ForgeError('The route planner did not answer', {
      llm: 'rabbit-planner did not reply. It may be restarting (it needs about 30 s after a deploy) or down; check robot_status.',
      cause: error,
    });
  }
  return PlannerReply.parse(reply.json());
};

const savedPlaces = async () =>
  (await plannerRequest(PLACES_SUBJECT, {})).places.filter(
    (place) => place.current_map,
  );

const Destination = z.object({
  object: z
    .string()
    .optional()
    .describe(
      `A thing the robot has seen, in English: a detector class (${DETECTOR_CLASSES.join(', ')}) or a common name such as fridge, tv, couch, bin`,
    ),
  place: z
    .string()
    .optional()
    .describe(
      'A room or saved place: kitchen, bathroom, bedroom, living room, laundry, office, dining room, or a name saved with save_place',
    ),
  x: z.number().optional().describe('World x of a point, m'),
  z: z.number().optional().describe('World z of a point, m'),
});

type Destination = z.infer<typeof Destination>;

type Resolved = {
  request: Json;
  target: {
    kind: string;
    label: string | null;
    x: number;
    z: number;
    frames?: number;
    confidence?: number;
    last_seen?: string;
  };
  alternatives: Sighting[];
};

const fromSightings = async (
  found: Sighting[],
  label: string,
): Promise<Resolved> => {
  const [best, ...rest] = found;
  if (best == null) {
    throw new ForgeError('Never seen it', {
      llm: `No ${label} has been seen in the current map often enough to trust (at least 10 detection frames, or 3 at 55 % confidence); brief detections are ignored as likely false positives.`,
    });
  }
  return {
    request: {
      object: {
        label: best.label,
        x: best.x,
        z: best.z,
        width: best.width,
        length: best.length,
        seen_from: await seenFrom(best),
      },
    },
    target: {
      kind: 'object',
      label: best.label,
      x: best.x,
      z: best.z,
      frames: best.frames,
      confidence: best.confidence,
      last_seen: best.last_seen,
    },
    alternatives: rest.slice(0, 3),
  };
};

export const resolveDestination = async (
  destination: Destination,
): Promise<Resolved> => {
  if (destination.x != null && destination.z != null) {
    return {
      request: { x: destination.x, z: destination.z },
      target: {
        kind: 'point',
        label: null,
        x: destination.x,
        z: destination.z,
      },
      alternatives: [],
    };
  }
  if (destination.place != null) {
    const name = normalize(destination.place);
    const places = await savedPlaces();
    const saved = places.find((place) => place.name === name);
    if (saved != null) {
      return {
        request: { place: name },
        target: {
          kind: 'place',
          label: name,
          x: saved.x,
          z: saved.z,
        },
        alternatives: [],
      };
    }
    const room = ROOMS[name];
    if (room == null) {
      const known = places.map((place) => place.name);
      throw new ForgeError('Unknown place', {
        llm: `There is no saved place called ${name}. Saved places: ${known.length > 0 ? known.join(', ') : 'none'}. Rooms found by their objects: ${Object.keys(ROOMS).join(', ')}. The operator can drive there and ask to save_place.`,
      });
    }
    const found = await sightings(room);
    if (found.length === 0) {
      throw new ForgeError('Room not found', {
        llm: `The robot has not seen any ${room.join(', ')} in the current map, so it cannot tell where the ${name} is. Drive or explore there first, or save the place with save_place when the robot is in it.`,
      });
    }
    const resolved = await fromSightings(found, name);
    return {
      ...resolved,
      target: {
        ...resolved.target,
        kind: 'room',
        label: `${name} (${resolved.target.label})`,
      },
    };
  }
  if (destination.object != null) {
    const labels = labelsFor(destination.object);
    if (labels.length === 0) {
      throw new ForgeError('Unknown object', {
        llm: `The detector has no class for "${destination.object}". Its classes: ${DETECTOR_CLASSES.join(', ')}.`,
      });
    }
    return await fromSightings(await sightings(labels), labels.join(' or '));
  }
  throw new ForgeError('No destination', {
    llm: 'Give an object, a place, or x and z.',
  });
};

const routeOf = (path: unknown) => {
  const points = Array.isArray(path) ? (path as unknown[][]) : [];
  const step = Math.max(1, Math.ceil(points.length / MAX_ROUTE_POINTS));
  return points
    .filter((_, i) => i % step === 0 || i === points.length - 1)
    .map((point) => ({ x: num(point[0], 2), z: num(point[1], 2) }));
};

const startTrip = async (destination: Destination, preview: boolean) => {
  const status = await robotStatus();
  const pose = status.pose;
  if (pose == null || !isFresh(pose) || pose.x == null || pose.z == null) {
    throw new ForgeError('Robot pose is stale', {
      llm: 'Forge has no robot pose from the last 3 s, so it cannot plan a route.',
    });
  }
  const resolved = await resolveDestination(destination);
  const tripId = `forge-${randomUUID()}`;
  const reply = await plannerRequest(PLANNER_GOAL_SUBJECT, {
    id: tripId,
    preview,
    ...resolved.request,
  });
  if (!reply.ok) {
    throw new ForgeError('The planner refused the trip', {
      llm: `The route planner refused: ${reply.error ?? 'no reason given'}.`,
    });
  }
  const deadline = Date.now() + TRIP_START_MS;
  let state: Json | undefined;
  for (;;) {
    const latest = liveLatest.get(PLANNER_STATE_SUBJECT)?.payload;
    if (
      field(latest, 'trip_id') === tripId &&
      field(latest, 'phase') !== 'planning'
    ) {
      state = latest;
      break;
    }
    if (Date.now() >= deadline) {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, TRIP_POLL_MS));
  }
  const phase = field(state, 'phase');
  if (phase === 'failed') {
    throw new ForgeError('No route', {
      llm: `The planner could not find a route to the ${resolved.target.label ?? 'target'}: ${String(field(state, 'message'))}.`,
      internal: { tripId },
    });
  }
  return {
    ok: true,
    trip_id: tripId,
    phase: phase ?? 'planning',
    target: resolved.target,
    goal: field(state, 'goal') ?? null,
    path_length_m: num(field(state, 'path_length_m'), 1),
    plan_ms: num(field(state, 'plan_ms'), 0),
    message: field(state, 'message') ?? 'still planning; check robot_status',
    other_sightings: resolved.alternatives.map(({ label, x, z, frames }) => ({
      label,
      x,
      z,
      frames,
    })),
    start: { x: pose.x, z: pose.z, heading_deg: pose.heading_deg ?? 0 },
    route: routeOf(field(state, 'path')),
  };
};

export const findObjectTool = forgeTool({
  title: 'Find object',
  description:
    'The answer to "where is X" and "where did you see X": where the robot has seen something in the current map (detections since the last map reset), so its coordinates are valid for go_to. object is a detector class or a common name like fridge; place is a room such as kitchen, found by its typical objects, or a saved place. Use objects_seen only for what was seen during a run as history. Returns the best match with world x and z, the detection frames and best confidence it rests on (a handful of frames is an uncertain sighting: say so), plus other sightings; objects seen too briefly are not returned. Read-only; use it for "where is the fridge" or before go_to when unsure.',
  input: Destination.pick({ object: true, place: true }),
  run: async (destination) => {
    const resolved = await resolveDestination(destination);
    return {
      ok: true,
      target: resolved.target,
      other_sightings: resolved.alternatives,
    };
  },
});

export const planRouteTool = forgeTool({
  title: 'Plan route',
  description:
    'Plans a route on the map to an object, a place (room or saved place) or a point without moving the robot, and shows it. Use it for "can you get to X" or "how far is X"; it fails with the reason when there is no route.',
  input: Destination,
  run: async (destination) => await startTrip(destination, true),
  forModel: ({ start: _start, route: _route, ...summary }) => summary,
});

export const goToTool = forgeTool({
  title: 'Go to',
  description:
    'Drives the robot to an object it has seen (it stops in front of it, facing it), a place (a room found by its objects, or a saved place) or a world point, along a route planned on the map. The robot replans around new obstacles on its own. The operator approves the trip. Returns once the route is planned (phase driving) or fails with the reason; follow progress with robot_status (trip). Use stop to cancel.',
  input: Destination,
  requiresApproval: true,
  run: async (destination) => await startTrip(destination, false),
  forModel: ({ start: _start, route: _route, ...summary }) => summary,
});

export const listPlacesTool = forgeTool({
  title: 'List places',
  description:
    'Places saved on the robot for the current map, with world x and z.',
  input: z.object({}),
  run: async () => ({ ok: true, places: await savedPlaces() }),
});

export const savePlaceTool = forgeTool({
  title: 'Save place',
  description:
    'Saves where the robot is now under a name (for example kitchen or charger), so go_to with that place works later. It belongs to the current map.',
  input: z.object({ name: z.string().min(1).max(40) }),
  run: async ({ name }) => {
    const reply = await plannerRequest(PLACE_SAVE_SUBJECT, { name });
    if (!reply.ok) {
      throw new ForgeError('Place not saved', {
        llm: `The planner did not save it: ${reply.error ?? 'no reason given'}.`,
      });
    }
    return { ok: true, place: reply.place };
  },
});

export const ROBOT_TOOLS = {
  robot_status: robotStatusTool,
  go_to: goToTool,
  plan_route: planRouteTool,
  find_object: findObjectTool,
  list_places: listPlacesTool,
  save_place: savePlaceTool,
  run_mission: runMissionTool,
  stop: stopTool,
  save_map: saveMapTool,
  reset_map: resetMapTool,
  start_run: startRunTool,
  stop_run: stopRunTool,
};

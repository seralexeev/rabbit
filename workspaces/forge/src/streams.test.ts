import type { Msg } from '@nats-io/transport-node';
import { describe, expect, it } from 'vitest';

import { STREAMS } from './streams.ts';

const message = (payload: object) =>
  ({ string: () => JSON.stringify(payload) }) as unknown as Msg;

describe('pose rows', () => {
  it('stores the ZED rotation about the vertical y axis as yaw', () => {
    const half = (30 * Math.PI) / 360;
    const pose = STREAMS.find((stream) => stream.table === 'pose');
    const [row] =
      pose?.toRows(
        message({
          ts: 1_790_000_000_000_000_000,
          frame_number: 1,
          translation: [0, 0, 0],
          orientation: [0, Math.sin(half), 0, Math.cos(half)],
          euler_deg: [2, 30, -1],
          velocity: [0, 0, 0],
          angular_velocity: [0, 0, 0],
          position_std: [0, 0, 0],
          confidence: 90,
        }),
        '0',
      ) ?? [];
    expect(row).toMatchObject({ pitch_deg: 2, yaw_deg: 30, roll_deg: -1 });
  });
});

const locRows = (payload: object) =>
  STREAMS.find((stream) => stream.subject === 'rabbit.loc.map_odom')?.toRows(
    {
      string: () =>
        JSON.stringify(payload).replace('"KF"', '1790000000123456789'),
    } as unknown as Msg,
    '0',
  ) ?? [];

describe('rabbit-loc rows', () => {
  it('keeps nanosecond keyframe stamps and turns the quaternion into yaw about +y', () => {
    const half = (-170 * Math.PI) / 360;
    const [row] = locRows({
      ts: 1_790_000_000_200_000_000,
      keyframe_ts: 'KF',
      status: 'localized',
      mode: 'growing',
      map_id: '1790',
      odom_session: 's1',
      translation: [0.2, 0, -0.58],
      orientation: [0, Math.sin(half), 0, Math.cos(half)],
      matches: 5,
      corrections: 1,
      pending: 0,
      grown_nodes: 12,
      last_match_ts: null,
    });
    expect(row).toMatchObject({
      keyframe_ts: '1790000000123456789',
      status: 'localized',
      mode: 'growing',
      x: 0.2,
      z: -0.58,
      last_match_ts: null,
    });
    expect(row?.yaw_deg).toBeCloseTo(-170, 9);
  });

  it('stores nulls before the first fix', () => {
    const [row] = locRows({
      ts: 1_790_000_000_200_000_000,
      keyframe_ts: null,
      status: 'relocalizing',
      mode: 'localization',
      map_id: '1790',
      odom_session: null,
      translation: null,
      orientation: null,
      matches: 0,
      corrections: 0,
      pending: 1,
      last_match_ts: null,
    });
    expect(row).toMatchObject({
      keyframe_ts: null,
      x: null,
      yaw_deg: null,
      odom_session: '',
      grown_nodes: 0,
    });
  });
});

const rowsOf = (subject: string, payload: object) =>
  STREAMS.find((stream) => stream.subject === subject)?.toRows(
    message(payload),
    '0',
  ) ?? [];

describe('Rabbit 2.0 body rows', () => {
  it('keeps the safety decision with the inputs that were heard', () => {
    const [row] = rowsOf('rabbit.safety.state', {
      ts: 1_790_000_000_000_000_000,
      seq: 9,
      mode: 'stopped',
      reason: 'obstacle behind 0.04 m',
      reasons: ['obstacle behind 0.04 m', 'lidar stale'],
      shadow: false,
      estop_line: true,
      estop_latched: false,
      estop_source: null,
      self_test: 'passed',
      speed: 0,
      steer: 0,
      requested_speed: -0.32,
      requested_steer: 0,
      source: 'nav',
      owner: 'auto',
      cap_fwd: 1,
      cap_rev: 0,
      clearance_fwd_m: 1,
      clearance_rev_m: 0.04,
      brain_ok: true,
      bumper_front: false,
      bumper_rear: false,
      battery_low: false,
      battery_critical: false,
      power_state: 'running',
      input_age_s: { command: 0.01, lidar: 0.31, tof_RR: null },
      sensors: ['bumpers', 'lidar', 'tof'],
    });
    expect(row).toMatchObject({
      mode: 'stopped',
      requested_speed: -0.32,
      estop_source: '',
      input_age_s: { command: 0.01, lidar: 0.31 },
    });
    expect(row).not.toHaveProperty('seq');
    expect(row?.input_age_s).not.toHaveProperty('tof_RR');
  });

  it('writes one ToF health row per sensor', () => {
    const sensor = (name: string, bus: number) => ({
      sensor: name,
      bus,
      state: 'ranging',
      hz: 15,
      frame_age_s: 0.02,
      valid: 60,
      floor: 8,
      overhead: 0,
      obstacles: 52,
      nearest_m: 0.3,
      errors: 0,
      resets: 0,
      init_s: 2.2,
    });
    const rows = rowsOf('rabbit.health.tof', {
      ts: 1_790_000_000_000_000_000,
      power_cycles: 1,
      sensors: [
        sensor('FL', 3),
        {
          ...sensor('RR', 6),
          state: 'failed',
          frame_age_s: null,
          nearest_m: null,
        },
      ],
    });
    expect(rows).toHaveLength(2);
    expect(rows[1]).toMatchObject({
      sensor: 'RR',
      state: 'failed',
      frame_age_s: null,
      power_cycles: 1,
    });
  });

  it('stores lidar health with the per-sector minimums and drops the mount', () => {
    const [row] = rowsOf('rabbit.health.lidar', {
      ts: 1_790_000_000_000_000_000,
      connected: true,
      port: '/dev/ttyAMA4',
      model: 65,
      firmware: '1.01',
      device_health: 'good',
      error_code: 0,
      scan_hz: 10.1,
      points: 480,
      measurements: 500,
      rotation_s: 0.099,
      scan_age_s: 0.05,
      rotations: 100,
      bad_nodes: 0,
      skipped_bytes: 0,
      short_rotations: 1,
      restarts: 0,
      reconnects: 0,
      errors: 0,
      sector_min_m: [
        2.1,
        null,
        0.4,
        0.4,
        0.5,
        0.06,
        0.06,
        0.5,
        0.4,
        0.4,
        null,
        2.1,
      ],
      mount: [0.1597, 0, 0.23, 180],
      masked_deg: [],
    });
    expect(row).toMatchObject({ model: 65, scan_hz: 10.1 });
    expect(row?.sector_min_m).toHaveLength(12);
    expect(row).not.toHaveProperty('mount');
  });
});

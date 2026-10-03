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

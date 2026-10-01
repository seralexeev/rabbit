import { describe, expect, it } from 'vitest';

import { conditionalReference } from '../graph/stats.ts';
import { jointEvents } from './detect.ts';

const GRID = { binMs: 100, firstBin: 0, length: 1000 };

const event = (signal: string, first: number, last: number) => ({
  signal,
  first,
  last,
  peakIndex: first,
  severity_ratio: 5,
  observed: 1,
  expected: 0,
  unit: 'A',
});

describe('jointEvents', () => {
  it('joins events of different signals that overlap within the window and names the first mover', () => {
    const joint = jointEvents(
      [
        event('battery_voltage', 105, 108),
        event('motor_current', 100, 102),
        event('imu_vibration', 400, 401),
      ],
      5,
      GRID,
    );
    expect(joint).toHaveLength(1);
    expect(joint[0]).toMatchObject({
      signals: ['motor_current', 'battery_voltage'],
      leading_signal: 'motor_current',
    });
  });

  it('does not call two events of one signal joint', () => {
    expect(
      jointEvents(
        [event('motor_current', 100, 101), event('motor_current', 103, 104)],
        5,
        GRID,
      ),
    ).toEqual([]);
  });
});

describe('conditionalReference', () => {
  it('expects the level of the signal at the same covariate level', () => {
    const command = Array.from({ length: 400 }, (_, i) =>
      i % 100 < 50 ? 0 : 0.25,
    );
    const current = command.map(
      (value, i) => (value === 0 ? 0.07 : 0.3) + (i % 3) * 0.01,
    );
    const expect_ = conditionalReference(
      current,
      current.map(() => true),
      [command],
      0.01,
    );
    expect(expect_(10).center).toBeCloseTo(0.08, 2);
    expect(expect_(60).center).toBeCloseTo(0.31, 2);
  });
});

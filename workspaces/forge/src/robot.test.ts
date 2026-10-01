import { describe, expect, it } from 'vitest';

import { missionOutcome, planMission } from './robot.ts';

const SENT_AT = 1000;
const REJECTED = 'rejected: move longer than 3 m';

describe('missionOutcome', () => {
  it.each([
    ['no state yet', null, undefined, 'pending'],
    [
      'a state from before the mission was sent',
      null,
      { payload: { fault: REJECTED }, receivedAt: 900 },
      'pending',
    ],
    [
      'the previous mission id kept after it ended',
      null,
      { payload: { mission_id: 'forge-old', mode: 'idle' }, receivedAt: 1100 },
      'pending',
    ],
    [
      'a rejection left over from the previous mission',
      REJECTED,
      {
        payload: { mission_id: 'forge-old', fault: REJECTED },
        receivedAt: 1100,
      },
      'pending',
    ],
    [
      'navigation adopting the id',
      REJECTED,
      {
        payload: { mission_id: 'forge-new', mode: 'driving' },
        receivedAt: 1100,
      },
      'accepted',
    ],
    [
      'navigation refusing it',
      null,
      {
        payload: { mission_id: 'forge-old', fault: REJECTED },
        receivedAt: 1100,
      },
      'rejected',
    ],
  ])('%s gives %s', (_, faultBefore, state, status) => {
    expect(
      missionOutcome('forge-new', SENT_AT, faultBefore, state).status,
    ).toBe(status);
  });
});

describe('planMission', () => {
  const START = { x: 0, z: 0, heading_deg: 0 };

  it('measures a goto from where the earlier steps leave the robot', () => {
    expect(
      planMission(START, [
        { type: 'move', forward: 3, right: 0 },
        { type: 'goto', x: 0, z: -7 },
      ]).total,
    ).toBeCloseTo(7);
    expect(() =>
      planMission(START, [
        { type: 'move', forward: 3, right: 0 },
        { type: 'move', forward: 2, right: 0 },
        { type: 'goto', x: 0, z: 4.9 },
      ]),
    ).toThrow('Goto target is too far');
  });

  it('reports the first leg that moves, with the heading change before it', () => {
    expect(
      planMission(START, [
        { type: 'turn', degrees: 0 },
        { type: 'move', forward: 0, right: 0 },
        { type: 'move', forward: 2, right: 0 },
      ]).firstLeg,
    ).toEqual({ forward: 2, turned_deg: 0 });
    expect(
      planMission(START, [
        { type: 'turn', degrees: 90 },
        { type: 'move', forward: 2, right: 0 },
      ]).firstLeg?.turned_deg,
    ).toBe(90);
  });
});

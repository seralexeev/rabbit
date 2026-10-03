import { describe, expect, it } from 'vitest';

import {
  clusterSightings,
  confirmedSighting,
  labelsFor,
  missionOutcome,
  planMission,
  seenFromSpots,
} from './robot.ts';

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

describe('labelsFor', () => {
  it.each([
    ['the Fridge', ['refrigerator']],
    ['fridges', ['refrigerator']],
    ['chairs', ['chair']],
    ['boxes', ['box']],
    ['TV', ['television']],
    ['potted plant', ['potted plant']],
    ['unicorn', []],
  ])('%s is %j', (query, labels) => {
    expect(labelsFor(query)).toEqual(labels);
  });
});

describe('clusterSightings', () => {
  const cell = (label: string, x: number, z: number, frames: number) => ({
    label,
    x,
    z,
    width: 0.7,
    length: 0.7,
    frames,
    confidence: 80,
    last_seen: `2026-10-02 09:0${frames % 10}:00`,
  });

  it('merges neighbouring cells of one object and keeps distant ones apart', () => {
    const clusters = clusterSightings([
      cell('refrigerator', 2, -6.4, 30),
      cell('refrigerator', 2.4, -6.4, 10),
      cell('refrigerator', 5, -1, 20),
      cell('oven', 2.2, -6.4, 50),
    ]);

    expect(clusters.map(({ label, x, frames }) => [label, x, frames])).toEqual([
      ['oven', 2.2, 50],
      ['refrigerator', 2.1, 40],
      ['refrigerator', 5, 20],
    ]);
  });
});

describe('confirmedSighting', () => {
  const sighting = (frames: number, confidence: number) => ({
    label: 'refrigerator',
    x: 0,
    z: 0,
    width: 0.7,
    length: 0.7,
    frames,
    confidence,
    last_seen: '2026-10-03 08:22:00',
  });

  it('accepts a few confident detections from a quick pass and rejects a weak flicker', () => {
    expect(confirmedSighting(sighting(6, 61))).toBe(true);
    expect(confirmedSighting(sighting(6, 45))).toBe(false);
    expect(confirmedSighting(sighting(12, 45))).toBe(true);
  });
});

describe('seenFromSpots', () => {
  it('keeps distinct camera spots of detections near the chosen object', () => {
    const row = (ox: number, cx: number, cz: number) => ({
      object_x: ox,
      object_z: 0,
      camera_x: cx,
      camera_z: cz,
    });
    expect(
      seenFromSpots(
        [row(2, 0, 0), row(2.1, 0.05, 0.02), row(2, 0, 1), row(5, 4, 4)],
        { x: 2, z: 0 },
      ),
    ).toEqual([
      [0, 0],
      [0, 1],
    ]);
  });
});

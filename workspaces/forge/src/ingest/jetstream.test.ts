import { describe, expect, it } from 'vitest';

import { logRow, recordRows } from './jetstream.ts';

describe('logRow', () => {
  it('lifts mission and map context into columns and keeps the rest as fields', () => {
    const text = JSON.stringify({
      ts: 0,
      node: 'nav',
      level: 'warning',
      logger: 'nav',
      message: 'Safety stop: stall',
      template: 'Safety stop: %s',
      fields: { fault: 'stall' },
      context: { mission_id: '17', exploration_id: '9' },
      repeats: 2,
      dropped: 4,
      pid: 7,
    }).replace('"ts":0', '"ts":1790862460381227544');

    const row = logRow(text, 42, () => 'run-a');

    expect(row).toMatchObject({
      run_id: 'run-a',
      ts: '1790862460381227544',
      mission_id: '17',
      map_session: '',
      repeats: 2,
      seq: 42,
      fields: { fault: 'stall', exploration_id: '9', dropped: '4' },
    });
  });
});

describe('recordRows', () => {
  const stamp = (payload: object) =>
    JSON.stringify({ ts: 0, ...payload }).replace(
      '"ts":0',
      '"ts":1790862460381227544',
    );

  it('stores an event with its ids in columns and its measurements in maps', () => {
    const text = stamp({
      node: 'nav',
      name: 'nav.safety_stop',
      severity: 'warning',
      reason: 'stall',
      boot_id: 'b1',
      instance_id: 'i1',
      ids: { mission_id: 'trip-1.2', trip_id: 'trip-1', place: 'kitchen' },
      values: { motor_current_a: 2.1 },
      labels: { mode: 'driving' },
      suppressed: 3,
    });

    const tables = recordRows('rabbit.log.nav.event', text, 7, () => 'run-a');

    expect(tables).toEqual([
      {
        table: 'events',
        rows: [
          expect.objectContaining({
            run_id: 'run-a',
            name: 'nav.safety_stop',
            severity: 'warning',
            reason: 'stall',
            mission_id: 'trip-1.2',
            trip_id: 'trip-1',
            exploration_id: '',
            values: { motor_current_a: 2.1 },
            labels: { mode: 'driving', place: 'kitchen' },
            suppressed: 3,
            seq: 7,
          }),
        ],
      },
    ]);
  });

  it('also records the start snapshot of a node and keeps plain logs as logs', () => {
    const start = stamp({
      node: 'planner',
      name: 'node.start',
      snapshot: {
        host: 'rabbit',
        pid: 12,
        code_hash: 'abc',
        git_rev: 'b36435d-dirty',
        versions: { python: '3.10.12' },
        env: { USE_GRID: '1' },
        config: { 'trip.DETOUR_HOLD': '4.0' },
      },
    });
    const log = stamp({
      node: 'planner',
      level: 'info',
      logger: 'planner',
      message: 'Planning: start',
    });

    const tables = recordRows('rabbit.log.planner.event', start, 1, () => 'r');

    expect(tables.map(({ table }) => table)).toEqual(['events', 'node_starts']);
    expect(tables[1]?.rows[0]).toMatchObject({
      code_hash: 'abc',
      config: { 'trip.DETOUR_HOLD': '4.0' },
    });
    expect(
      recordRows('rabbit.log.planner', log, 2, () => 'r').map(
        ({ table }) => table,
      ),
    ).toEqual(['logs']);
  });
});

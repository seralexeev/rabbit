import { describe, expect, it } from 'vitest';

import { logRow } from './jetstream.ts';

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

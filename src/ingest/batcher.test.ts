import { ClickHouseError } from '@clickhouse/client';
import { describe, expect, it } from 'vitest';

import type { Row } from '../streams.ts';
import { Batcher } from './batcher.ts';

const rows = (count: number): Row[] =>
  Array.from({ length: count }, (_, i) => ({ ts: `${i}` }));

const drain = async (batcher: Batcher, clock: { now: number }) => {
  for (let step = 0; step < 50 && batcher.pending() > 0; step++) {
    await batcher.flush();
    clock.now += 60_000;
  }
};

describe('Batcher', () => {
  it('isolates a malformed row by bisecting and inserts the rest', async () => {
    const clock = { now: 0 };
    const stored: Row[] = [];
    const dead: Row[] = [];
    const batcher = new Batcher(
      async (_, batch) => {
        if (batch.some((row) => row.ts === '5')) {
          throw new ClickHouseError({
            message: 'Cannot parse input',
            code: '27',
            type: 'CANNOT_PARSE_INPUT',
          });
        }
        stored.push(...batch);
        await Promise.resolve();
      },
      (_, batch) => {
        dead.push(...batch);
      },
      { batchRows: 8, maxBufferedRows: 100, now: () => clock.now },
    );
    batcher.push('imu', rows(8));
    await drain(batcher, clock);
    expect(dead).toEqual([{ ts: '5' }]);
    expect(
      stored
        .map((row) => String(row.ts))
        .toSorted((a, b) => a.localeCompare(b)),
    ).toEqual(['0', '1', '2', '3', '4', '6', '7']);
  });

  it('retries a transient failure with the same deduplication token after a backoff', async () => {
    const clock = { now: 0 };
    const tokens: string[] = [];
    let failures = 1;
    const batcher = new Batcher(
      async (_, __, token) => {
        tokens.push(token);
        if (failures-- > 0) {
          throw new Error('socket hang up');
        }
        await Promise.resolve();
      },
      () => {
        throw new Error('nothing should be dead-lettered');
      },
      { batchRows: 10, maxBufferedRows: 100, now: () => clock.now },
    );
    batcher.push('power', rows(3));
    await batcher.flush();
    await batcher.flush();
    expect(tokens).toHaveLength(1);
    clock.now += 2000;
    await batcher.flush();
    expect(tokens).toHaveLength(2);
    expect(tokens[1]).toBe(tokens[0]);
    expect(batcher.inserted.get('power')).toBe(3);
  });
});

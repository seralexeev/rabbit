import { describe, expect, it } from 'vitest';

import { type RunSpan, runAt } from './runs.ts';

const runs: RunSpan[] = [
  { run_id: 'auto-1', kind: 'auto', start: 0, stop: 1000 },
  { run_id: 'manual-1', kind: 'manual', start: 100, stop: 500 },
  { run_id: 'auto-2', kind: 'auto', start: 2000, stop: null },
];

describe('runAt', () => {
  it.each([
    {
      at: 300,
      expected: 'manual-1',
      why: 'a manual run wins over an overlapping auto run',
    },
    {
      at: 700,
      expected: 'auto-1',
      why: 'outside the manual run the auto run holds it',
    },
    {
      at: 1500,
      expected: 'auto-1',
      why: 'a record from a gap between runs belongs to the run before it',
    },
    {
      at: 5000,
      expected: 'auto-2',
      why: 'an open run contains everything after its start',
    },
    { at: -1, expected: undefined, why: 'nothing before the first run' },
  ])('$why', ({ at, expected }) => {
    expect(runAt(runs, at)).toBe(expected);
  });
});

import { describe, expect, it } from 'vitest';

import { gridFor, toGrid } from './series.ts';

describe('toGrid', () => {
  it('treats a missing value as an unobserved gap instead of zero', () => {
    const grid = toGrid(
      [
        { bin: 10, value: 2 },
        { bin: 11, value: Number.NaN },
        { bin: 13, value: 5 },
      ],
      10,
      4,
    );
    expect(grid.observed).toEqual([true, false, false, true]);
    expect(grid.values).toEqual([2, 2, 2, 5]);
  });

  it.each([
    {
      missing: 'zero' as const,
      rows: [{ bin: 10, value: 3 }],
      observed: [true, true, true],
      values: [3, 0, 0],
    },
    {
      missing: 'zero' as const,
      rows: [],
      observed: [false, false, false],
      values: [0, 0, 0],
    },
  ])(
    'counts an empty bin of a rate as zero only when the source has rows ($rows.length rows)',
    ({ missing, rows, observed, values }) => {
      const grid = toGrid(rows, 10, 3, missing);
      expect(grid.observed).toEqual(observed);
      expect(grid.values).toEqual(values);
    },
  );
});

describe('gridFor', () => {
  it('bins in whole milliseconds, which ClickHouse binds as UInt32', () => {
    const grid = gridFor({ first: 0, last: 110_000 }, 600 / 110);
    expect(grid.binMs).toBe(183);
    expect(grid.length).toBe(602);
  });
});

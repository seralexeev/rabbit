import { describe, expect, it } from 'vitest';

import { TIMEZONE_NOTE, localTime, withLocalTimes } from './local_time.ts';

describe('local times for the model', () => {
  it.each([
    ['2026-10-02 01:38:52.900000000', '2026-10-02 11:38:52.900 AEST'],
    ['2026-10-03 15:59:00', '2026-10-04 01:59:00 AEST'],
    ['2026-10-03 16:00:00', '2026-10-04 03:00:00 AEDT'],
    ['2026-10-01T11:00', '2026-10-01 21:00 AEST'],
  ])('shows %s UTC as %s in Sydney', (utc, local) => {
    expect(localTime(utc)).toBe(local);
  });

  it('adds a local twin next to every UTC time and nothing else', () => {
    expect(
      withLocalTimes({
        rows: [{ t: '2026-10-02 01:38:52', run_id: '20261002-010955-auto' }],
        window: { from: '2026-10-02 01:36:00' },
      }),
    ).toEqual({
      timezone: TIMEZONE_NOTE,
      rows: [
        {
          t: '2026-10-02 01:38:52',
          t_local: '2026-10-02 11:38:52 AEST',
          run_id: '20261002-010955-auto',
        },
      ],
      window: {
        from: '2026-10-02 01:36:00',
        from_local: '2026-10-02 11:36:00 AEST',
      },
    });
    expect(withLocalTimes({ ok: true, day: '2026-10-02' })).toEqual({
      ok: true,
      day: '2026-10-02',
    });
  });
});

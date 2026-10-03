import { ForgeError } from './errors.ts';
import { epochMs } from './output.ts';
import { resolveRunId } from './runs.ts';
import { select } from './store/engine.ts';

export const toIso = (ms: number) =>
  new Date(ms).toISOString().replace('T', ' ').slice(0, 23);

export const parseAt = (at: string, day: string) => {
  const clock = /^\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(at.trim());
  const ms = epochMs(clock ? `${day} ${at.trim().padStart(5, '0')}` : at);
  if (ms == null) {
    throw new ForgeError('Unreadable time', {
      llm: "Pass at as HH:MM[:SS] on the robot's UTC clock or a full 'YYYY-MM-DD HH:MM:SS'.",
      internal: { at },
    });
  }
  return ms;
};

export const runFor = async (input: {
  run_id?: string | undefined;
  at?: string | undefined;
}) => {
  if (input.run_id != null || input.at == null) {
    return await resolveRunId(input.run_id ?? 'latest');
  }
  const [latest] = await select<{ day: string }>(
    'SELECT toString(toDate(max(started_at))) AS day FROM runs',
  );
  const at = parseAt(input.at, latest?.day ?? '1970-01-01');
  const [run] = await select<{ run_id: string }>(
    "SELECT run_id FROM runs WHERE started_at <= fromUnixTimestamp64Milli({at:Int64}) AND (stopped_at IS NULL OR stopped_at >= fromUnixTimestamp64Milli({at:Int64})) ORDER BY kind = 'manual' DESC, started_at DESC LIMIT 1",
    { at },
  );
  return run?.run_id ?? (await resolveRunId('latest'));
};

export const runDay = async (runId: string) =>
  (
    await select<{ day: string }>(
      'SELECT toString(toDate(started_at)) AS day FROM runs WHERE run_id = {run_id:String}',
      { run_id: runId },
    )
  )[0]?.day ?? '1970-01-01';

export type TimeWindow = {
  run_id: string;
  from: number;
  to: number;
  at: number | null;
};

export const resolveWindow = async (
  input: {
    run_id?: string | undefined;
    at?: string | undefined;
    from?: string | undefined;
    to?: string | undefined;
  },
  around: { before_s: number; after_s: number },
  maxSpanS: number,
): Promise<TimeWindow> => {
  const runId = await runFor(input);
  const day = await runDay(runId);
  const at = input.at == null ? null : parseAt(input.at, day);
  const bound = (value: string | undefined, offsetMs: number) => {
    if (value != null) {
      return parseAt(value, day);
    }
    return at == null ? null : at + offsetMs;
  };
  const from = bound(input.from, -around.before_s * 1000);
  const to = bound(input.to, around.after_s * 1000);
  if (from == null || to == null || to <= from) {
    throw new ForgeError('No time window given', {
      llm: 'Pass at (HH:MM[:SS] UTC) for a moment, or from and to for a range.',
      internal: { input },
    });
  }
  if (to - from > maxSpanS * 1000) {
    throw new ForgeError('Time window too long', {
      llm: `Keep the window under ${maxSpanS / 60} minutes; narrow from and to or pass at.`,
      internal: { from, to },
    });
  }
  return { run_id: runId, from, to, at };
};

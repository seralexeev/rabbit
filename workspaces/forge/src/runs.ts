import { type NatsConnection, connect } from '@nats-io/transport-node';
import z from 'zod';

import { config } from './config.ts';
import { ForgeError, errorMessage } from './errors.ts';
import { select } from './store/engine.ts';

export type RunKind = 'manual' | 'auto';

export type RunEvent = {
  run_id: string;
  name: string;
  kind: RunKind;
  event: 'start' | 'stop';
  at: string;
  note: string;
};

export type Run = {
  run_id: string;
  name: string;
  kind: RunKind;
  started_at: string;
  stopped_at: string | null;
  duration_s: number;
  note: string;
};

export const nowNanos = () => `${BigInt(Date.now()) * 1_000_000n}`;

const slug = (name: string) =>
  name
    .toLowerCase()
    .replaceAll(/[^a-z0-9]+/g, '-')
    .replaceAll(/^-|-$/g, '');

export const newRunId = (name: string, at = new Date()) => {
  const stamp = at
    .toISOString()
    .slice(0, 19)
    .replaceAll(/[-:]/g, '')
    .replace('T', '-');
  return `${stamp}-${slug(name)}`;
};

type RunEventSink = (events: RunEvent[]) => Promise<void>;

let sink: RunEventSink | null = null;

export const recordRunEvents = (record: RunEventSink) => {
  sink = record;
};

const insertRunEvents = async (events: RunEvent[]) => {
  if (sink == null) {
    throw new ForgeError('Runs are recorded by the Forge writer');
  }
  await sink(events);
};

const RUN_SUBJECT = 'forge.run';
const RUN_REPLY_MS = 5000;

const RunRequest = z.object({
  name: z.string().min(1).optional(),
  note: z.string().default(''),
});

const RunReply = z.object({
  run_id: z.string().optional(),
  error: z.string().optional(),
});

export const openRuns = async (kind: RunKind) =>
  await select<Pick<Run, 'run_id' | 'name'>>(
    'SELECT run_id, name FROM runs WHERE kind = {kind:String} AND stopped_at IS NULL ORDER BY started_at DESC',
    { kind },
  );

export type RunSpan = {
  run_id: string;
  kind: RunKind;
  start: number;
  stop: number | null;
};

export const recentRuns = async (days: number) =>
  (
    await select<{
      run_id: string;
      kind: RunKind;
      start: string;
      stop: string | null;
    }>(
      'SELECT run_id, kind, toUnixTimestamp64Milli(started_at) AS start, toUnixTimestamp64Milli(stopped_at) AS stop FROM runs WHERE started_at > now() - toIntervalDay({days:UInt32}) ORDER BY started_at',
      { days },
    )
  ).map((run): RunSpan => ({
    ...run,
    start: Number(run.start),
    stop: run.stop == null ? null : Number(run.stop),
  }));

export const runAt = (runs: RunSpan[], at: number) => {
  const started = runs.filter((run) => run.start <= at);
  const containing = started.filter(
    (run) => run.stop == null || run.stop >= at,
  );
  return (
    containing.find((run) => run.kind === 'manual') ??
    containing.at(-1) ??
    started.toSorted((a, b) => (a.stop ?? at) - (b.stop ?? at)).at(-1) ??
    null
  )?.run_id;
};

const requestRun = async (action: 'start' | 'stop', payload: object) => {
  let nc: NatsConnection;
  try {
    nc = await connect({
      servers: config.natsUrl,
      name: 'forge-cli',
      timeout: RUN_REPLY_MS,
    });
  } catch (error) {
    throw new ForgeError('Robot is unreachable', {
      llm: 'Runs are recorded by the Forge writer on the robot, and its NATS server did not answer.',
      cause: error,
    });
  }
  try {
    const reply = RunReply.parse(
      (
        await nc.request(`${RUN_SUBJECT}.${action}`, JSON.stringify(payload), {
          timeout: RUN_REPLY_MS,
        })
      ).json(),
    );
    if (reply.error != null || reply.run_id == null) {
      throw new ForgeError(
        reply.error ?? 'The Forge writer did not return a run',
      );
    }
    return reply.run_id;
  } finally {
    await nc.close();
  }
};

const startLocal = async (name: string, note = '') => {
  const [open] = await openRuns('manual');
  if (open != null) {
    throw new ForgeError('A run is already recording', {
      internal: { runId: open.run_id },
    });
  }
  const runId = newRunId(name);
  await insertRunEvents([
    {
      run_id: runId,
      name,
      kind: 'manual',
      event: 'start',
      at: nowNanos(),
      note,
    },
  ]);
  return runId;
};

const stopLocal = async () => {
  const [open] = await openRuns('manual');
  if (open == null) {
    throw new ForgeError('No run is recording');
  }
  await insertRunEvents([
    { ...open, kind: 'manual', event: 'stop', at: nowNanos(), note: '' },
  ]);
  return open.run_id;
};

export const startRun = async (name: string, note = '') =>
  sink == null
    ? await requestRun('start', { name, note })
    : await startLocal(name, note);

export const stopRun = async () =>
  sink == null ? await requestRun('stop', {}) : await stopLocal();

export const serveRunControl = (nc: NatsConnection) => {
  for (const action of ['start', 'stop'] as const) {
    const subscription = nc.subscribe(`${RUN_SUBJECT}.${action}`);
    void (async () => {
      for await (const msg of subscription) {
        try {
          const request = RunRequest.parse(msg.json());
          const runId =
            action === 'start'
              ? await startLocal(request.name ?? 'run', request.note)
              : await stopLocal();
          msg.respond(JSON.stringify({ run_id: runId }));
        } catch (error) {
          msg.respond(JSON.stringify({ error: errorMessage(error) }));
        }
      }
    })();
  }
};

export const listRuns = async (limit = 20) =>
  await select<Run>(
    'SELECT run_id, name, kind, started_at, stopped_at, duration_s, note FROM runs ORDER BY started_at DESC LIMIT {limit:UInt32}',
    { limit },
  );

const RELATIVE_RUNS: Record<string, number> = { latest: 0, previous: 1 };

export const resolveRunId = async (runId: string) => {
  const offset = RELATIVE_RUNS[runId];
  if (offset == null) {
    return runId;
  }
  const [run] = await select<Pick<Run, 'run_id'>>(
    "SELECT run_id FROM runs ORDER BY kind = 'manual' DESC, started_at DESC LIMIT 1 OFFSET {offset:UInt32}",
    { offset },
  );
  if (run == null) {
    throw new ForgeError('No such run recorded yet', {
      llm: `There is no '${runId}' run yet. Use list_runs to see what was recorded.`,
      internal: { runId },
    });
  }
  return run.run_id;
};

export const resolveRunParams = async <T extends Record<string, unknown>>(
  params: T,
): Promise<T> =>
  Object.fromEntries(
    await Promise.all(
      Object.entries(params).map(async ([name, value]) => [
        name,
        name.endsWith('run_id') && typeof value === 'string'
          ? await resolveRunId(value)
          : value,
      ]),
    ),
  ) as T;

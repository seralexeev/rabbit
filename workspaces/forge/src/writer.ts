import { type NatsConnection, connect } from '@nats-io/transport-node';
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { writer } from './clickhouse.ts';
import { ROOT, config } from './config.ts';
import { errorMessage } from './errors.ts';
import { Batcher } from './ingest/batcher.ts';
import { consumeKv, consumeLogs } from './ingest/jetstream.ts';
import { log } from './log.ts';
import {
  type RunEvent,
  type RunKind,
  type RunSpan,
  newRunId,
  nowNanos,
  openRuns,
  recentRuns,
  runAt,
} from './runs.ts';
import { migrate } from './schema.ts';
import { type Row, STREAMS } from './streams.ts';

const FLUSH_MS = 10_000;
const POLL_MS = 2000;
const REPORT_MS = 10_000;
const IDLE_MS = 60_000;
const LIVE_MS = 10_000;
const RUN_HISTORY_DAYS = 8;
const BATCH_ROWS = 20_000;
const MAX_BUFFERED_ROWS = 1_000_000;
const SHUTDOWN_FLUSH_MS = 10_000;

type Current = { runId: string; name: string; kind: RunKind };

class RunTracker {
  private current: Current | null = null;
  private manual: Current | null = null;
  private history: RunSpan[] = [];
  private lastMessageAt = 0;
  private readonly emit: (event: RunEvent) => void;

  public constructor(emit: (event: RunEvent) => void) {
    this.emit = emit;
  }

  public runIdFor(now: number): string {
    this.lastMessageAt = now;
    if (this.manual != null) {
      if (this.current?.runId !== this.manual.runId) {
        this.stopAuto();
        this.current = this.manual;
        log('Recording run', { runId: this.manual.runId });
      }
      return this.manual.runId;
    }
    if (this.current?.kind === 'auto') {
      return this.current.runId;
    }
    const runId = newRunId('auto');
    this.current = { runId, name: 'auto', kind: 'auto' };
    this.emit({
      run_id: runId,
      name: 'auto',
      kind: 'auto',
      event: 'start',
      at: nowNanos(),
      note: '',
    });
    log('Opened auto run', { runId });
    return runId;
  }

  public runIdAt(tsNanos: string, now: number): string {
    const at = Number(BigInt(tsNanos) / 1_000_000n);
    if (Math.abs(now - at) < LIVE_MS) {
      return this.runIdFor(now);
    }
    return runAt(this.history, at) ?? this.runIdFor(now);
  }

  public async poll() {
    this.history = await recentRuns(RUN_HISTORY_DAYS);
    const [open] = await openRuns('manual');
    this.manual =
      open == null
        ? null
        : { runId: open.run_id, name: open.name, kind: 'manual' };
    if (
      this.current?.kind === 'auto' &&
      Date.now() - this.lastMessageAt > IDLE_MS
    ) {
      this.stopAuto();
      this.current = null;
    }
  }

  public async closeStaleAutoRuns() {
    for (const run of await openRuns('auto')) {
      this.emit({
        run_id: run.run_id,
        name: run.name,
        kind: 'auto',
        event: 'stop',
        at: nowNanos(),
        note: '',
      });
    }
  }

  public stopAuto() {
    if (this.current?.kind === 'auto') {
      const { runId, name } = this.current;
      this.emit({
        run_id: runId,
        name,
        kind: 'auto',
        event: 'stop',
        at: nowNanos(),
        note: '',
      });
      log('Closed auto run', { runId });
    }
  }
}

const DEAD_LETTERS = new URL('dead_letters/', ROOT);

const deadLetter = (table: string, rows: Row[], reason: string) => {
  try {
    mkdirSync(DEAD_LETTERS, { recursive: true });
    appendFileSync(
      new URL(`${table}.jsonl`, DEAD_LETTERS),
      rows.map((row) => JSON.stringify({ reason, row })).join('\n') + '\n',
    );
    log('Dead-lettered rows', { table, rows: rows.length, reason });
  } catch (error) {
    log('Lost rows that could not be dead-lettered', {
      table,
      rows: rows.length,
      reason,
      error: errorMessage(error),
    });
  }
};

const insert = async (table: string, rows: Row[], token: string) => {
  await writer.insert({
    table,
    values: rows,
    format: 'JSONEachRow',
    clickhouse_settings: { insert_deduplication_token: token },
  });
};

const WRITER_HEARTBEAT = join(tmpdir(), 'forge-writer.heartbeat');

const subscribeStreams = (
  nc: NatsConnection,
  tracker: RunTracker,
  buffers: Batcher,
  parseErrors: Map<string, number>,
) => {
  const subjects = Map.groupBy(STREAMS, (stream) => stream.subject);
  for (const [subject, streams] of subjects) {
    const subscription = nc.subscribe(subject);
    void (async () => {
      for await (const msg of subscription) {
        const now = Date.now();
        const runId = tracker.runIdFor(now);
        for (const stream of streams) {
          try {
            const rows = stream.toRows(msg, `${BigInt(now) * 1_000_000n}`);
            buffers.push(
              stream.table,
              rows.map((row) => ({ run_id: runId, ...row })),
            );
          } catch (error) {
            const count = (parseErrors.get(stream.table) ?? 0) + 1;
            parseErrors.set(stream.table, count);
            if (count === 1) {
              log('Dropped malformed message', {
                subject,
                table: stream.table,
                error: errorMessage(error).slice(0, 300),
              });
            }
          }
        }
      }
    })();
  }
};

export const runWriter = async () => {
  await migrate();
  const buffers = new Batcher(insert, deadLetter, {
    batchRows: BATCH_ROWS,
    maxBufferedRows: MAX_BUFFERED_ROWS,
  });
  const tracker = new RunTracker((event) => {
    buffers.push('run_events', [event]);
  });
  await tracker.closeStaleAutoRuns();
  await tracker.poll();

  const parseErrors = new Map<string, number>();
  let natsState = 'connecting';
  let robot: {
    nc: NatsConnection;
    logs: ReturnType<typeof consumeLogs>;
    kv: ReturnType<typeof consumeKv>;
  } | null = null;

  const flushTimer = setInterval(() => {
    void buffers.flush();
  }, FLUSH_MS);
  const pollTimer = setInterval(() => {
    tracker.poll().catch((error: unknown) => {
      log('Run poll failed', { error: errorMessage(error) });
    });
  }, POLL_MS);

  let previous = new Map<string, number>();
  const reportTimer = setInterval(() => {
    try {
      writeFileSync(WRITER_HEARTBEAT, String(Date.now()));
    } catch (error) {
      log('Heartbeat write failed', { error: errorMessage(error) });
    }
    const totals = new Map([
      ...buffers.received,
      ['logs', robot?.logs.inserted() ?? 0],
    ]);
    const rates = Object.fromEntries(
      [...totals].map(([table, total]) => [
        table,
        Math.round(((total - (previous.get(table) ?? 0)) * 1000) / REPORT_MS),
      ]),
    );
    previous = totals;
    log('rows/s', {
      ...rates,
      nats: natsState,
      pending: buffers.pending(),
      ...(buffers.deadLettered.size > 0
        ? { dead_lettered: Object.fromEntries(buffers.deadLettered) }
        : {}),
      ...(parseErrors.size > 0
        ? { malformed: Object.fromEntries(parseErrors) }
        : {}),
    });
  }, REPORT_MS);

  const shutdown = async () => {
    log('Shutting down');
    clearInterval(pollTimer);
    clearInterval(reportTimer);
    if (robot != null) {
      await Promise.all([robot.logs.stop(), robot.kv.stop()]);
      await robot.nc.close();
    }
    tracker.stopAuto();
    clearInterval(flushTimer);
    const deadline = Date.now() + SHUTDOWN_FLUSH_MS;
    while (buffers.pending() > 0 && Date.now() < deadline) {
      await buffers.flush();
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    const unsent = buffers.pending();
    if (unsent > 0) {
      buffers.drainUnsent('writer shutdown');
      log('Unsent rows dead-lettered at shutdown', { rows: unsent });
    }
    await writer.close();
    process.exit(0);
  };
  process.once('SIGINT', () => void shutdown());
  process.once('SIGTERM', () => void shutdown());

  log('Connecting to NATS', { server: config.natsUrl });
  const nc = await connect({
    servers: config.natsUrl,
    name: 'forge-writer',
    pingInterval: config.natsPingIntervalMs,
    maxPingOut: config.natsMaxPingOut,
    maxReconnectAttempts: -1,
    reconnectTimeWait: 2000,
    waitOnFirstConnect: true,
  });
  natsState = 'connected';
  log('Connected to NATS', { server: config.natsUrl });

  void (async () => {
    for await (const status of nc.status()) {
      if (status.type === 'disconnect' || status.type === 'reconnect') {
        natsState = status.type === 'reconnect' ? 'connected' : 'disconnected';
        log(`NATS ${status.type}`, { server: status.server });
      }
    }
  })();

  subscribeStreams(nc, tracker, buffers, parseErrors);
  const recordedAt = (ts: string) => tracker.runIdAt(ts, Date.now());
  robot = {
    nc,
    logs: consumeLogs(
      nc,
      recordedAt,
      async (table, rows) => {
        await insert(
          table,
          rows,
          `${table}:${String(rows[0]?.seq)}-${String(rows.at(-1)?.seq)}`,
        );
      },
      deadLetter,
    ),
    kv: consumeKv(nc, recordedAt, (table, rows) => {
      buffers.push(table, rows);
    }),
  };
};

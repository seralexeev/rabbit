import {
  AckPolicy,
  DeliverPolicy,
  type JsMsg,
  jetstream,
  jetstreamManager,
} from '@nats-io/jetstream';
import type { NatsConnection } from '@nats-io/transport-node';
import z from 'zod';

import { errorMessage } from '../errors.ts';
import { log } from '../log.ts';
import { type Row, nanos } from '../streams.ts';
import { isTransient } from './batcher.ts';

export const LOG_STREAM = 'LOGS';
export const LOG_SUBJECTS = 'rabbit.log.>';
export const KV_SUBJECTS = '$KV.rabbit.>';

const KV_STREAM = 'KV_rabbit';
const KV_PREFIX = '$KV.rabbit.';
const LOG_CONSUMER = 'forge-writer';
const FETCH_MESSAGES = 1000;
const FETCH_EXPIRES_MS = 1000;
const ACK_WAIT_NS = 120_000_000_000;
const RETRY_MS = 5000;
const MAX_BACKOFF_MS = 30_000;
const MAX_KV_VALUE = 65_536;

export type RunAt = (tsNanos: string) => string;
export type InsertRows = (table: string, rows: Row[]) => Promise<void>;
export type DeadLetter = (table: string, rows: Row[], reason: string) => void;

const LogRecord = z.object({
  node: z.string(),
  level: z.enum(['debug', 'info', 'warning', 'error', 'critical']),
  logger: z.string(),
  message: z.string(),
  template: z.string().default(''),
  exception_type: z.string().default(''),
  exception: z.string().default(''),
  location: z.string().default(''),
  fields: z.record(z.string(), z.string()).default({}),
  context: z.record(z.string(), z.string()).default({}),
  repeats: z.number().int().min(0).default(0),
  dropped: z.number().int().min(0).optional(),
  pid: z.number().int().min(0).default(0),
});

export const logRow = (text: string, seq: number, runAt: RunAt): Row => {
  const ts = nanos(text);
  const record = LogRecord.parse(JSON.parse(text));
  const {
    mission_id: missionId,
    map_session: mapSession,
    ...context
  } = record.context;
  return {
    run_id: runAt(ts),
    ts,
    node: record.node,
    level: record.level,
    logger: record.logger,
    message: record.message,
    template: record.template.length === 0 ? record.message : record.template,
    exception_type: record.exception_type,
    exception: record.exception,
    location: record.location,
    fields: {
      ...record.fields,
      ...context,
      ...(record.dropped == null ? {} : { dropped: String(record.dropped) }),
    },
    mission_id: missionId ?? '',
    map_session: mapSession ?? '',
    repeats: record.repeats,
    pid: record.pid,
    seq,
  };
};

const sleep = async (ms: number) =>
  await new Promise((resolve) => setTimeout(resolve, ms));

const ensureLogConsumer = async (nc: NatsConnection) => {
  const jsm = await jetstreamManager(nc);
  try {
    await jsm.consumers.info(LOG_STREAM, LOG_CONSUMER);
  } catch {
    await jsm.consumers.add(LOG_STREAM, {
      durable_name: LOG_CONSUMER,
      ack_policy: AckPolicy.All,
      deliver_policy: DeliverPolicy.All,
      ack_wait: ACK_WAIT_NS,
      max_ack_pending: 20_000,
    });
  }
  return await jetstream(nc).consumers.get(LOG_STREAM, LOG_CONSUMER);
};

const insertUntilStored = async (
  insert: InsertRows,
  deadLetter: DeadLetter,
  rows: Row[],
  running: () => boolean,
) => {
  for (let attempt = 0; ; attempt++) {
    try {
      await insert('logs', rows);
      return true;
    } catch (error) {
      if (!isTransient(error)) {
        deadLetter('logs', rows, errorMessage(error).slice(0, 300));
        return true;
      }
      if (!running()) {
        return false;
      }
      await sleep(Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt));
    }
  }
};

export const consumeLogs = (
  nc: NatsConnection,
  runAt: RunAt,
  insert: InsertRows,
  deadLetter: DeadLetter,
) => {
  const state = { running: true, inserted: 0 };
  const running = () => state.running;
  const done = (async () => {
    while (running()) {
      try {
        const consumer = await ensureLogConsumer(nc);
        log('Consuming robot logs', { stream: LOG_STREAM });
        while (running()) {
          const messages: JsMsg[] = [];
          for await (const msg of await consumer.fetch({
            max_messages: FETCH_MESSAGES,
            expires: FETCH_EXPIRES_MS,
          })) {
            messages.push(msg);
          }
          const last = messages.at(-1);
          if (last == null) {
            continue;
          }
          const rows: Row[] = [];
          for (const msg of messages) {
            try {
              rows.push(logRow(msg.string(), msg.seq, runAt));
            } catch (error) {
              deadLetter(
                'logs',
                [{ subject: msg.subject, seq: msg.seq, text: msg.string() }],
                errorMessage(error).slice(0, 300),
              );
            }
          }
          if (
            rows.length > 0 &&
            !(await insertUntilStored(
              insert,
              deadLetter,
              rows,
              () => state.running,
            ))
          ) {
            return;
          }
          state.inserted += rows.length;
          last.ack();
        }
      } catch (error) {
        if (running()) {
          log('Robot log consumer failed, retrying', {
            error: errorMessage(error).slice(0, 300),
          });
          await sleep(RETRY_MS);
        }
      }
    }
  })();
  return {
    inserted: () => state.inserted,
    stop: async () => {
      state.running = false;
      await done;
    },
  };
};

export const consumeKv = (
  nc: NatsConnection,
  runAt: RunAt,
  push: (table: string, rows: Row[]) => void,
) => {
  const state: { stopped: boolean; close: (() => Promise<void>) | null } = {
    stopped: false,
    close: null,
  };
  const stopped = () => state.stopped;
  void (async () => {
    while (!stopped()) {
      try {
        const consumer = await jetstream(nc).consumers.get(KV_STREAM, {
          filter_subjects: [KV_SUBJECTS],
          deliver_policy: DeliverPolicy.LastPerSubject,
        });
        const messages = await consumer.consume();
        state.close = async () => {
          await messages.close();
        };
        for await (const msg of messages) {
          const ts = `${msg.info.timestampNanos}`;
          const value = msg.string();
          const operation = msg.headers?.get('KV-Operation') ?? '';
          push('kv_changes', [
            {
              run_id: runAt(ts),
              ts,
              key: msg.subject.slice(KV_PREFIX.length),
              revision: msg.seq,
              operation: operation === '' ? 'PUT' : operation,
              value:
                value.length > MAX_KV_VALUE
                  ? value.slice(0, MAX_KV_VALUE)
                  : value,
            },
          ]);
        }
      } catch (error) {
        log('Robot key-value consumer failed, retrying', {
          error: errorMessage(error).slice(0, 300),
        });
      }
      if (!stopped()) {
        await sleep(RETRY_MS);
      }
    }
  })();
  return {
    stop: async () => {
      state.stopped = true;
      await state.close?.();
    },
  };
};

import { ClickHouseError } from '@clickhouse/client';
import { randomUUID } from 'node:crypto';

import type { Row } from '../streams.ts';

export type Insert = (
  table: string,
  rows: Row[],
  token: string,
) => Promise<void>;

export type DeadLetter = (table: string, rows: Row[], reason: string) => void;

const TRANSIENT_CODES = new Set([
  '159',
  '202',
  '203',
  '209',
  '210',
  '241',
  '242',
  '252',
  '319',
  '394',
  '425',
  '999',
  '1000',
]);

export const isTransient = (error: unknown) =>
  !(error instanceof ClickHouseError) || TRANSIENT_CODES.has(error.code);

const MAX_BACKOFF_MS = 30_000;

type Job = { rows: Row[]; token: string; attempts: number };

type Options = {
  batchRows: number;
  maxBufferedRows: number;
  now?: () => number;
};

export class Batcher {
  private readonly buffers = new Map<string, Row[]>();
  private readonly jobs = new Map<string, Job[]>();
  private readonly inFlight = new Set<string>();
  private readonly retryAt = new Map<string, number>();
  public readonly inserted = new Map<string, number>();
  public readonly deadLettered = new Map<string, number>();
  private readonly insert: Insert;
  private readonly deadLetter: DeadLetter;
  private readonly options: Required<Options>;

  public constructor(insert: Insert, deadLetter: DeadLetter, options: Options) {
    this.insert = insert;
    this.deadLetter = deadLetter;
    this.options = { now: Date.now, ...options };
  }

  public push(table: string, rows: Row[]) {
    const buffer = this.buffers.get(table) ?? [];
    buffer.push(...rows);
    const overflow = buffer.length - this.options.maxBufferedRows;
    if (overflow > 0) {
      this.drop(table, buffer.splice(0, overflow), 'buffer overflow');
    }
    this.buffers.set(table, buffer);
  }

  public async flush() {
    const now = this.options.now();
    const started: Array<Promise<void>> = [];
    for (const table of new Set([
      ...this.buffers.keys(),
      ...this.jobs.keys(),
    ])) {
      if (this.inFlight.has(table) || (this.retryAt.get(table) ?? 0) > now) {
        continue;
      }
      const job = this.nextJob(table);
      if (job != null) {
        started.push(this.run(table, job));
      }
    }
    await Promise.all(started);
  }

  public pending() {
    return [
      ...this.buffers.values(),
      ...[...this.jobs.values()].flat().map((job) => job.rows),
    ].reduce((total, rows) => total + rows.length, 0);
  }

  public drainUnsent(reason: string) {
    for (const [table, jobs] of this.jobs) {
      for (const job of jobs) {
        this.drop(table, job.rows, reason);
      }
    }
    for (const [table, rows] of this.buffers) {
      this.drop(table, rows, reason);
    }
    this.jobs.clear();
    this.buffers.clear();
  }

  private nextJob(table: string): Job | null {
    const queued = this.jobs.get(table)?.shift();
    if (queued != null) {
      return queued;
    }
    const rows =
      this.buffers.get(table)?.splice(0, this.options.batchRows) ?? [];
    return rows.length === 0
      ? null
      : { rows, token: randomUUID(), attempts: 0 };
  }

  private requeue(table: string, ...jobs: Job[]) {
    this.jobs.set(table, [...jobs, ...(this.jobs.get(table) ?? [])]);
  }

  private drop(table: string, rows: Row[], reason: string) {
    if (rows.length > 0) {
      this.deadLetter(table, rows, reason);
      this.deadLettered.set(
        table,
        (this.deadLettered.get(table) ?? 0) + rows.length,
      );
    }
  }

  private async run(table: string, job: Job) {
    this.inFlight.add(table);
    try {
      await this.insert(table, job.rows, job.token);
      this.inserted.set(
        table,
        (this.inserted.get(table) ?? 0) + job.rows.length,
      );
      this.retryAt.delete(table);
    } catch (error) {
      if (isTransient(error)) {
        const attempts = job.attempts + 1;
        this.retryAt.set(
          table,
          this.options.now() +
            Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (attempts - 1)),
        );
        this.requeue(table, { ...job, attempts });
      } else if (job.rows.length === 1) {
        this.drop(
          table,
          job.rows,
          error instanceof Error ? error.message.slice(0, 300) : String(error),
        );
      } else {
        const half = Math.ceil(job.rows.length / 2);
        this.requeue(
          table,
          {
            rows: job.rows.slice(0, half),
            token: `${job.token}.a`,
            attempts: 0,
          },
          { rows: job.rows.slice(half), token: `${job.token}.b`, attempts: 0 },
        );
      }
    } finally {
      this.inFlight.delete(table);
    }
  }
}

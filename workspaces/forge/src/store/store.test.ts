import type { Msg } from '@nats-io/transport-node';
import { copyFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { config } from '../config.ts';
import { searchLogsTool } from '../logs.ts';
import { runSlab } from '../slabs/run_slab.ts';
import { loadSlabs } from '../slabs/slab.ts';
import { checkSql } from '../sql/query_gate.ts';
import { STREAMS } from '../streams.ts';
import { applyRetention, compact, mergeFiles } from './compact.ts';
import { closeStore, select, tableSpec, tableSpecs } from './engine.ts';
import { TMP, listPartitions, recover } from './layout.ts';
import { writeRows } from './write.ts';

vi.mock('../config.ts', async (importOriginal) => {
  const { mkdtempSync: temp } = await import('node:fs');
  const { tmpdir: dir } = await import('node:os');
  const { join: joinPath } = await import('node:path');
  const original = await importOriginal<{ config: typeof config }>();
  return {
    ...original,
    config: {
      ...original.config,
      dataDir: temp(joinPath(dir(), 'forge-store-test-')),
      syncFrom: null,
    },
  };
});

const HOUR = 3_600_000;
const T0 = Date.parse('2026-10-01T10:00:00Z');

const nanos = (ms: number) => `${BigInt(ms) * 1_000_000n}`;

const power = (ms: number, run = 'r1') => ({
  run_id: run,
  ts: nanos(ms),
  battery_voltage: 15.5,
  battery_current: 1.25,
  battery_power: 19.4,
  battery_charge_pct: null,
  rail_6v_voltage: 6,
  rail_6v_current: 0.1,
  rail_6v_power: 0.6,
  errors: 0,
});

const count = async (table: string) =>
  Number(
    (await select<{ n: string }>(`SELECT count() AS n FROM ${table}`))[0]?.n,
  );

const files = (table: string) =>
  listPartitions(config.dataDir, table).flatMap((partition) =>
    partition.files.map((file) => file.name),
  );

beforeEach(() => {
  rmSync(config.dataDir, { recursive: true, force: true });
});

afterAll(async () => {
  await closeStore();
  rmSync(config.dataDir, { recursive: true, force: true });
});

describe('Parquet store', () => {
  it('maps every schema table to a view with exactly the schema types', async () => {
    for (const spec of (await tableSpecs()).values()) {
      const described = await select<{ name: string; type: string }>(
        `DESCRIBE TABLE forge.${spec.name}`,
      );
      expect(
        described.map((column) => `${column.name} ${column.type}`),
      ).toEqual(spec.columns.map((column) => `${column.name} ${column.type}`));
    }
  });

  it('round-trips enums, maps, nullable arrays and computed columns through Parquet', async () => {
    await writeRows('logs', [
      {
        run_id: 'r1',
        ts: nanos(T0),
        node: 'nav',
        level: 'warning',
        logger: 'nav',
        message: 'Roboclaw Error 7',
        template: 'Roboclaw Error %d',
        exception_type: '',
        exception: '',
        location: 'nav:run:1',
        fields: { fault: 'stall' },
        mission_id: 'm1',
        map_session: '',
        repeats: 2,
        pid: 7,
        seq: 1,
      },
      {
        run_id: 'r1',
        ts: nanos(T0 + 1000),
        node: 'nav',
        level: 'info',
        logger: 'nav',
        message: 'Roboclaw Error 8',
        template: 'Roboclaw Error %d',
        exception_type: '',
        exception: '',
        location: 'nav:run:1',
        fields: {},
        mission_id: '',
        map_session: '',
        repeats: 0,
        pid: 7,
        seq: 2,
      },
    ]);
    await writeRows('obstacle', [
      { run_id: 'r1', ts: nanos(T0), scan_ranges: [1.5, null, 2], blind: true },
    ]);
    await writeRows('imu', [
      {
        run_id: 'r1',
        ts: nanos(T0),
        accel_x: 0,
        accel_y: 9.80665,
        accel_z: 0,
        gyro_x: 0,
        gyro_y: 0,
        gyro_z: 0,
        qx: 0,
        qy: 0,
        qz: 0,
        qw: 1,
      },
    ]);
    expect(
      await select(
        `SELECT level, fields['fault'] AS fault, fingerprint = cityHash64(node, logger, exception_type, 'Roboclaw Error %d') AS fingerprinted
         FROM logs WHERE level >= 'warning' AND hasAllTokens(lower(message), lower('roboclaw ERROR'))`,
      ),
    ).toEqual([{ level: 'warning', fault: 'stall', fingerprinted: 1 }]);
    expect(
      await select('SELECT scan_ranges, blind, nearest_distance FROM obstacle'),
    ).toEqual([
      { scan_ranges: [1.5, null, 2], blind: true, nearest_distance: null },
    ]);
    expect(await select('SELECT g, samples FROM imu')).toEqual([
      { g: 1, samples: 1 },
    ]);
  });

  it('stores rabbit-loc rows and the shadow columns of zed health as the streams produce them', async () => {
    const stream = (subject: string) => {
      const found = STREAMS.find((s) => s.subject === subject);
      if (found == null) {
        throw new Error(`no stream for ${subject}`);
      }
      return found;
    };
    const msg = (payload: object) =>
      ({ string: () => JSON.stringify(payload) }) as unknown as Msg;
    const loc = stream('rabbit.loc.map_odom').toRows(
      msg({
        ts: Number(nanos(T0)),
        status: 'localized',
        mode: 'localization',
        map_id: 'm',
        odom_session: 's1',
        translation: [1, 0, 2],
        orientation: [0, 0, 0, 1],
        matches: 3,
        corrections: 0,
        pending: 0,
        grown_nodes: 0,
      }),
      '0',
    );
    await writeRows(
      'loc',
      loc.map((row) => ({ run_id: 'r1', ...row })),
    );
    expect(
      await select('SELECT status, x, z, yaw_deg, keyframe_ts FROM loc'),
    ).toEqual([
      { status: 'localized', x: 1, z: 2, yaw_deg: 0, keyframe_ts: null },
    ]);
    const columns = await select(
      "SELECT name, type FROM system.columns WHERE database = 'forge' AND table = 'zed_health' AND name LIKE 'gen3_from_loc%' ORDER BY name",
    );
    expect(columns.map((c) => (c as { name: string }).name)).toEqual([
      'gen3_from_loc_x',
      'gen3_from_loc_yaw_deg',
      'gen3_from_loc_z',
    ]);
  });

  it('never shows a file that was not committed, and recovery removes it', async () => {
    await writeRows('power', [power(T0), power(T0 + 1000)]);
    const [partition] = listPartitions(config.dataDir, 'power');
    if (partition == null) {
      throw new Error('no partition written');
    }
    writeFileSync(join(partition.dir, `99-99.parquet${TMP}`), 'PAR1 torn');
    expect(await count('power')).toBe(2);
    expect(recover(config.dataDir)).toHaveLength(1);
    expect(readdirSync(partition.dir).some((name) => name.endsWith(TMP))).toBe(
      false,
    );
  });

  it('rewrites the same file when a write is retried with its id', async () => {
    await writeRows('power', [power(T0)], 42);
    await writeRows('power', [power(T0)], 42);
    expect(files('power')).toEqual(['42-42.parquet']);
    expect(await count('power')).toBe(1);
  });

  it('writes one file per hour a batch spans', async () => {
    await writeRows('power', [power(T0 + HOUR - 500), power(T0 + HOUR + 500)]);
    expect(listPartitions(config.dataDir, 'power')).toHaveLength(2);
    expect(await count('power')).toBe(2);
  });

  it('drops the inputs a merge already covers when a crash left them behind', async () => {
    await writeRows('power', [power(T0)], 1);
    await writeRows('power', [power(T0 + 1000)], 2);
    const [partition] = listPartitions(config.dataDir, 'power');
    if (partition == null) {
      throw new Error('no partition written');
    }
    const [first] = partition.files;
    if (first == null) {
      throw new Error('no file written');
    }
    const backup = join(tmpdir(), 'forge-store-test-input.parquet');
    copyFileSync(first.path, backup);
    await mergeFiles(await tableSpec('power'), partition.files);
    expect(files('power')).toEqual(['1-2.parquet']);
    copyFileSync(backup, first.path);
    expect(await count('power')).toBe(3);
    recover(config.dataDir);
    expect(files('power')).toEqual(['1-2.parquet']);
    expect(await count('power')).toBe(2);
    rmSync(backup);
  });

  it('merges a closed hour into one file and an open hour once small files pile up', async () => {
    for (let i = 0; i < 3; i++) {
      await writeRows('power', [power(T0 + i * 1000)]);
    }
    await compact(T0 + HOUR / 2);
    expect(files('power')).toHaveLength(3);
    await compact(T0 + 2 * HOUR);
    expect(files('power')).toHaveLength(1);
    expect(await count('power')).toBe(3);
    for (let i = 0; i < 30; i++) {
      await writeRows('power', [power(T0 + 2 * HOUR + i * 1000)]);
    }
    await compact(T0 + 2 * HOUR + 60_000);
    expect(
      listPartitions(config.dataDir, 'power').map((p) => p.files.length),
    ).toEqual([1, 1]);
    expect(await count('power')).toBe(33);
  });

  it('deduplicates replacing tables by their sorting key when merging', async () => {
    const record = {
      run_id: 'r1',
      ts: nanos(T0),
      key: 'rabbit.zed.camera_settings',
      revision: 3,
      operation: 'PUT',
      value: '{}',
    };
    await writeRows('kv_changes', [record]);
    await writeRows('kv_changes', [record]);
    expect(await count('kv_changes')).toBe(2);
    await compact(T0 + 2 * HOUR);
    expect(await count('kv_changes')).toBe(1);
  });

  it('keeps only warnings in logs older than 30 days and drops logs older than 180', async () => {
    const day = 86_400_000;
    const log = (ms: number, level: string, seq: number) => ({
      run_id: 'r1',
      ts: nanos(ms),
      node: 'nav',
      level,
      logger: 'nav',
      message: level,
      template: level,
      exception_type: '',
      exception: '',
      location: '',
      fields: {},
      mission_id: '',
      map_session: '',
      repeats: 0,
      pid: 1,
      seq,
    });
    await writeRows('logs', [
      log(T0, 'info', 1),
      log(T0 + 1, 'error', 2),
      log(T0 - 200 * day, 'error', 3),
    ]);
    await applyRetention(T0 + 31 * day);
    expect(
      await select('SELECT toString(level) AS level FROM logs ORDER BY seq'),
    ).toEqual([{ level: 'error' }]);
  });

  it('finds log records by the start of a word, case-insensitively', async () => {
    await writeRows('logs', [
      {
        run_id: 'r1',
        ts: nanos(T0),
        node: 'rabbit-zed',
        level: 'info',
        logger: 'zed',
        message: 'Relocalized (KNOWN_MAP)',
        template: 'Relocalized (%s)',
        exception_type: '',
        exception: '',
        location: '',
        fields: {},
        mission_id: '',
        map_session: '',
        repeats: 0,
        pid: 1,
        seq: 1,
      },
    ]);
    const found = await searchLogsTool.run(
      searchLogsTool.input.parse({ run_id: 'r1', text: 'relocali known' }),
    );
    expect(found).toMatchObject({
      rows: [{ latest_message: 'Relocalized (KNOWN_MAP)' }],
    });
  });

  it('counts over-current events across a reboot and notices the clock floors dropping', async () => {
    const sample = (second: number, oc3: number, pinned: boolean) => ({
      run_id: 'r1',
      ts: nanos(T0 + second * 1000),
      cpu_freq_mhz: [1728, 1728],
      cpu_actual_mhz: [second === 1 ? 864 : 1728, 1728],
      cpu_min_freq_mhz: pinned ? [1728, 1728] : [730, 730],
      gpu_min_freq_mhz: pinned ? 1020 : 306,
      emc_freq_mhz: 3199,
      oc1_events: 0,
      oc2_events: 0,
      oc3_events: oc3,
      power_mode: 'MAXN_SUPER',
    });
    await writeRows('jetson', [
      sample(0, 100, true),
      sample(1, 102, true),
      sample(2, 105, false),
      sample(3, 1, false),
    ]);
    const { rows } = await runSlab('power_throttling', {
      run_id: 'r1',
      bucket_s: 10,
    });
    expect(rows).toMatchObject([
      {
        oc1_events: 0,
        oc3_per_s: 0.5,
        min_actual_cpu_mhz: 864,
        cut_sample_share: 0.25,
        min_cpu_floor_mhz: 730,
        clocks_pinned_share: 0.5,
        power_mode: 'MAXN_SUPER',
      },
    ]);
  });

  it('runs every slab through the SQL gate and EXPLAIN on the views', async () => {
    for (const slab of loadSlabs()) {
      const params = Object.fromEntries(
        Object.entries(slab.subs).map(([name, sub]) => [
          name,
          sub.default ?? (sub.type === 'String' ? 'r1' : 1),
        ]),
      );
      await expect(
        checkSql(slab.sql, {
          ...params,
          run_id: 'r1',
          other_run_id: 'r0',
          bucket_s: 10,
        }),
      ).resolves.toBeUndefined();
    }
  });
});

import { readFileSync } from 'node:fs';

import { isSeries, loadGraph } from '../graph/graph.ts';
import { extent, fetchSeries, gridFor } from '../graph/series.ts';
import { investigateTool } from '../graph/tools.ts';
import { searchLogsTool } from '../logs.ts';
import { listRuns } from '../runs.ts';
import { runSlab } from '../slabs/run_slab.ts';
import { loadSlabs } from '../slabs/slab.ts';
import { timelineTool } from '../timeline.ts';
import { select } from './engine.ts';

const kib = (status: string, key: string) =>
  Number(new RegExp(`${key}:\\s+(\\d+)`).exec(status)?.[1] ?? 0);

export const memory = () => {
  const mb = (bytes: number) => Math.round(bytes / 1048576);
  const read = (path: string) => {
    try {
      return readFileSync(path, 'utf8');
    } catch {
      return null;
    }
  };
  const status = read('/proc/self/status');
  const cgroup = read('/sys/fs/cgroup/memory.current');
  const peak = read('/sys/fs/cgroup/memory.peak');
  return {
    rss_mb: mb(process.memoryUsage().rss),
    heap_mb: mb(process.memoryUsage().heapUsed),
    ...(status == null
      ? {}
      : {
          anon_mb: Math.round(kib(status, 'RssAnon') / 1024),
          file_mb: Math.round(kib(status, 'RssFile') / 1024),
          hwm_mb: Math.round(kib(status, 'VmHWM') / 1024),
        }),
    ...(cgroup == null ? {} : { cgroup_mb: mb(Number(cgroup)) }),
    ...(peak == null ? {} : { cgroup_peak_mb: mb(Number(peak)) }),
  };
};

const timed = async (fn: () => Promise<unknown>) => {
  const started = performance.now();
  const cpu = process.cpuUsage();
  await fn();
  const used = process.cpuUsage(cpu);
  return {
    ms: Math.round(performance.now() - started),
    cpu_ms: Math.round((used.user + used.system) / 1000),
    ...memory(),
  };
};

const iso = (ms: number) =>
  new Date(ms).toISOString().replace('T', ' ').slice(0, 19);

export const bench = async (runId?: string) => {
  const report: Record<string, unknown> = { start: memory() };
  report.engine = await timed(async () => await select('SELECT 1'));
  const runs = await listRuns(100);
  const run =
    runs.find((candidate) => candidate.run_id === runId) ??
    runs
      .filter((candidate) => candidate.stopped_at != null)
      .toSorted((a, b) => b.duration_s - a.duration_s)[0];
  if (run == null) {
    return report;
  }
  report.run = { run_id: run.run_id, duration_s: run.duration_s };
  const start = Date.parse(`${run.started_at.replace(' ', 'T')}Z`);
  const middle = iso(start + (run.duration_s * 1000) / 2);
  report.status_queries = await timed(async () => {
    for (const table of ['pose', 'power', 'nav_state', 'obstacle']) {
      await select(
        `SELECT * FROM ${table} WHERE ts > now64(3) - INTERVAL 10 MINUTE ORDER BY ts DESC LIMIT 1`,
      );
    }
  });
  const slabs: Record<string, number> = {};
  report.slabs = await timed(async () => {
    for (const slab of loadSlabs()) {
      const started = performance.now();
      await runSlab(slab.id, { run_id: run.run_id });
      slabs[slab.id] = Math.round(performance.now() - started);
    }
  });
  report.slowest_slabs = Object.entries(slabs)
    .toSorted((a, b) => b[1] - a[1])
    .slice(0, 5);
  report.timeline = await timed(
    async () =>
      await timelineTool.run(
        timelineTool.input.parse({
          at: middle,
          run_id: run.run_id,
          before_s: 600,
          after_s: 300,
        }),
      ),
  );
  report.investigate = await timed(
    async () =>
      await investigateTool.run(
        investigateTool.input.parse({
          symptom: 'motor_current',
          run_id: run.run_id,
          from: iso(start),
          to: iso(Math.min(start + 900_000, start + run.duration_s * 1000)),
        }),
      ),
  );
  report.search_logs = await timed(
    async () =>
      await searchLogsTool.run(
        searchLogsTool.input.parse({ run_id: run.run_id, text: 'error' }),
      ),
  );
  report.graph_series_whole_run = await timed(async () => {
    const nodes = [...loadGraph().nodes.values()].filter(isSeries);
    const scope = {
      run_id: run.run_id,
      from: '1970-01-01 00:00:00',
      to: '2100-01-01 00:00:00',
    };
    await fetchSeries(nodes, scope, gridFor(await extent(nodes, scope), 0.1));
  });
  report.parallel_slabs = await timed(async () => {
    await Promise.all(
      loadSlabs()
        .slice(0, 8)
        .map(async (slab) => await runSlab(slab.id, { run_id: run.run_id })),
    );
  });
  report.end = memory();
  return report;
};

import z from 'zod';

import { ForgeError, errorMessage } from '../errors.ts';
import { forgeTool } from '../forge_tool.ts';
import {
  type MetricGraph,
  type SeriesNode,
  getNode,
  isSeries,
  loadGraph,
  upstreamLinks,
} from '../graph/graph.ts';
import {
  FAST_MAX_MS,
  type Grid,
  type Sampled,
  type Scope,
  extent,
  fetchSeries,
  gridFor,
  isoOf,
  timeOf,
} from '../graph/series.ts';
import {
  median,
  quantile,
  conditionalReference,
  round,
  sparkline,
} from '../graph/stats.ts';
import { log } from '../log.ts';
import { type Chart, type Severity, outputId } from '../output.ts';
import { resolveRunId } from '../runs.ts';
import {
  type Forecast,
  type ForecastInput,
  forecastQuantiles,
} from './tsfm.ts';

const FAST = { hz: 10, context: 512, horizon: 16 };
const SLOW = { hz: 1, context: 256, horizon: 30 };
const MIN_CONTEXT = 64;
const MIN_OBSERVED_SHARE = 0.5;
const WINDOWS_PER_REQUEST = 200;
const MODELS = [
  { id: 'amazon/chronos-2', joint: true },
  { id: 'NX-AI/TiRex-2', joint: false },
];
const SUSTAINED_POINTS = 10;
const SUSTAINED_DEVIATION = 0.5;
const SUSTAINED_CLIP = 3;
const REFERENCE_Z = 6;
const STEP_SHARE = 0.5;
const STEP_LOOKBACK = 5;
const TRANSIENT_S = 2;
const MERGE_GAP = 2;
const MAX_EVENTS = 12;
const MAX_TARGETS = 4;
const MAX_COVARIATES = 4;
const CLEAN_TRIM = 0.05;
const CLEAN_QUANTILE = 0.998;
const JOINT_WINDOW_S = { 10: 2, 1: 5 } as Record<number, number>;
const COVARIATE_RELATIONS = ['explains', 'drives'] as const;
const EVIDENCE_RANK: Record<string, number> = {
  physics: 0,
  design: 1,
  observed: 2,
};
const CHART_POINTS = 2000;

type Shape = { grid: Grid; context: number; horizon: number };

type Channel = {
  node: SeriesNode;
  sampled: Sampled;
  covariates: string[];
};

type Scored = {
  index: number;
  value: number;
  median: number;
  lo: number;
  hi: number;
  score: number;
  deviation: number;
};

type Flag = { index: number; kind: 'point' | 'sustained' | 'regime' };

type Window = { t0: number; c0: number };

export const autoCovariates = (
  graph: MetricGraph,
  targets: string[],
): Record<string, string[]> =>
  Object.fromEntries(
    targets.map((target) => [
      target,
      upstreamLinks(graph, target, COVARIATE_RELATIONS)
        .filter((link) => {
          const cause = graph.nodes.get(link.cause);
          return (
            cause != null && isSeries(cause) && !targets.includes(link.cause)
          );
        })
        .toSorted(
          (a, b) =>
            (EVIDENCE_RANK[a.edge.evidence] ?? 3) -
            (EVIDENCE_RANK[b.edge.evidence] ?? 3),
        )
        .map((link) => link.cause),
    ]),
  );

const pickCovariates = (
  graph: MetricGraph,
  targets: string[],
  requested: 'auto' | string[],
) => {
  if (requested !== 'auto') {
    for (const id of requested) {
      if (!isSeries(getNode(graph, id))) {
        throw new ForgeError('Covariate is not a measured metric', {
          llm: `${id} is an event, not a measured series; pick covariates from the series metrics.`,
          internal: { id },
        });
      }
    }
    return Object.fromEntries(targets.map((target) => [target, requested]));
  }
  const perTarget = autoCovariates(graph, targets);
  const chosen: string[] = [];
  for (let rank = 0; chosen.length < MAX_COVARIATES; rank++) {
    const next = targets
      .map((target) => perTarget[target]?.[rank])
      .filter((id): id is string => id != null && !chosen.includes(id));
    if (
      next.length === 0 &&
      targets.every((target) => (perTarget[target]?.length ?? 0) <= rank)
    ) {
      break;
    }
    chosen.push(...next.slice(0, MAX_COVARIATES - chosen.length));
  }
  return Object.fromEntries(
    targets.map((target) => [
      target,
      (perTarget[target] ?? []).filter((id) => chosen.includes(id)),
    ]),
  );
};

const shapeFor = async (
  nodes: SeriesNode[],
  targets: SeriesNode[],
  scope: Scope,
): Promise<Shape> => {
  const span = await extent(targets, scope);
  const fast =
    span.last - span.first <= FAST_MAX_MS &&
    targets.every((node) => node.hz >= FAST.hz);
  const shape = fast ? FAST : SLOW;
  const grid = gridFor(span, shape.hz);
  const context = Math.min(shape.context, grid.length - shape.horizon);
  if (context < MIN_CONTEXT) {
    throw new ForgeError('Not enough data for anomaly detection', {
      llm: `These signals need at least ${(MIN_CONTEXT + shape.horizon) / shape.hz} s of data in the chosen run and time range; widen from and to, or pick another run.`,
      internal: { ...scope, points: grid.length, nodes: nodes.length },
    });
  }
  return { grid, context, horizon: shape.horizon };
};

const windowStarts = (shape: Shape, channels: Channel[]): Window[] => {
  const firstObserved = Math.min(
    ...channels
      .map((channel) => channel.sampled.observed.indexOf(true))
      .filter((index) => index >= 0),
  );
  const windows: Window[] = [];
  for (
    let t0 = firstObserved + MIN_CONTEXT;
    t0 + shape.horizon <= shape.grid.length;
    t0 += shape.horizon
  ) {
    const c0 = Math.max(firstObserved, t0 - shape.context);
    const observed = channels.some(
      (channel) =>
        channel.sampled.observed.slice(c0, t0).filter(Boolean).length >=
        (t0 - c0) * MIN_OBSERVED_SHARE,
    );
    if (observed) {
      windows.push({ t0, c0 });
    }
  }
  return windows;
};

const forecastCache = new Map<string, Forecast & { model: string }>();

const forecast = async (
  model: (typeof MODELS)[number],
  shape: Shape,
  starts: Window[],
  channels: Channel[],
  covariates: Map<string, Sampled>,
  cacheKey: string,
): Promise<Forecast & { model: string }> => {
  const key = `${cacheKey}|${model.id}`;
  const cached = forecastCache.get(key);
  if (cached != null) {
    return cached;
  }
  const slice = (from: number, to: number) =>
    Object.fromEntries(
      [...covariates].map(([id, sampled]) => [
        id,
        sampled.values.slice(from, to),
      ]),
    );
  const groups = model.joint
    ? [channels]
    : channels.map((channel) => [channel]);
  const inputs: ForecastInput[] = starts.flatMap(({ t0, c0 }) =>
    groups.map((group) => ({
      target: Array.from({ length: t0 - c0 }, (_, h) =>
        group.map((channel) =>
          channel.sampled.observed[c0 + h] === true
            ? (channel.sampled.values[c0 + h] ?? null)
            : null,
        ),
      ),
      ...(covariates.size === 0
        ? {}
        : {
            past_covariates: slice(c0, t0),
            future_covariates: slice(t0, t0 + shape.horizon),
          }),
    })),
  );
  const chunks: ForecastInput[][] = [];
  for (let i = 0; i < inputs.length; i += WINDOWS_PER_REQUEST) {
    chunks.push(inputs.slice(i, i + WINDOWS_PER_REQUEST));
  }
  const responses = await Promise.all(
    chunks.map(
      async (chunk) => await forecastQuantiles(model.id, chunk, shape.horizon),
    ),
  );
  const outputs = responses.flatMap((response) => response.windows);
  const windows = starts.map((_, w) => {
    const parts = outputs.slice(w * groups.length, (w + 1) * groups.length);
    return {
      lo: parts.flatMap((part) => part.lo),
      median: parts.flatMap((part) => part.median),
      hi: parts.flatMap((part) => part.hi),
    };
  });
  const result = {
    model: model.id,
    band: responses[0]?.band ?? [0.05, 0.95],
    windows,
  } satisfies Forecast & { model: string };
  forecastCache.set(key, result);
  return result;
};

const scoreChannel = (
  channel: Channel,
  c: number,
  shape: Shape,
  starts: Window[],
  result: Forecast,
): Scored[] =>
  result.windows.flatMap((window, w) => {
    const t0 = starts[w]?.t0 ?? 0;
    return Array.from({ length: shape.horizon }, (_, h) => {
      const index = t0 + h;
      const value = channel.sampled.values[index] ?? Number.NaN;
      const lo = window.lo[c]?.[h] ?? Number.NaN;
      const hi = window.hi[c]?.[h] ?? Number.NaN;
      const middle = window.median[c]?.[h] ?? Number.NaN;
      const width = Math.max(hi - lo, channel.node.floor, 1e-9);
      return {
        index,
        value,
        median: middle,
        lo,
        hi,
        score: Math.max(0, (value - hi) / width, (lo - value) / width),
        deviation: (value - middle) / width,
      };
    });
  });

const scoreReference = (
  channel: Channel,
  shape: Shape,
  starts: Window[],
  covariates: Map<string, Sampled>,
): Scored[] => {
  const expect = conditionalReference(
    channel.sampled.values,
    channel.sampled.observed,
    channel.covariates
      .slice(0, 2)
      .map((id) => covariates.get(id)?.values)
      .filter((values) => values != null),
    channel.node.floor,
  );
  return starts.flatMap(({ t0 }) =>
    Array.from({ length: shape.horizon }, (_, h) => {
      const index = t0 + h;
      const value = channel.sampled.values[index] ?? Number.NaN;
      const cell = expect(index);
      const z = (value - cell.center) / cell.scale;
      return {
        index,
        value,
        median: cell.center,
        lo: cell.center - REFERENCE_Z * cell.scale,
        hi: cell.center + REFERENCE_Z * cell.scale,
        score: Math.abs(z) / REFERENCE_Z,
        deviation: z,
      };
    }),
  );
};

const REGIME_TRIM = 0.1;

const rollingMedians = (reference: Scored[]) =>
  reference.map((_, i) => {
    if (i < SUSTAINED_POINTS - 1) {
      return 0;
    }
    const recent = reference.slice(i - SUSTAINED_POINTS + 1, i + 1);
    const contiguous =
      (recent.at(-1)?.index ?? 0) - (recent[0]?.index ?? 0) ===
      SUSTAINED_POINTS - 1;
    return contiguous
      ? median(recent.map((candidate) => Math.abs(candidate.deviation)))
      : 0;
  });

export const regimeLimit = (medians: number[], horizon: number) => {
  const windows = Math.floor(medians.length / horizon);
  const peaks = Array.from({ length: windows }, (_, w) =>
    Math.max(0, ...medians.slice(w * horizon, (w + 1) * horizon)),
  );
  const cutoff = quantile(peaks, 1 - REGIME_TRIM);
  const clean = peaks.flatMap((peak, w) =>
    peak <= cutoff ? medians.slice(w * horizon, (w + 1) * horizon) : [],
  );
  return Math.max(REFERENCE_Z, quantile(clean, CLEAN_QUANTILE));
};

const regimeFlags = (
  reference: Scored[],
  medians: number[],
  limit: number,
  observed: boolean[],
): Flag[] =>
  reference.flatMap((point, i): Flag[] =>
    observed[point.index] === true && (medians[i] ?? 0) > limit
      ? [{ index: point.index, kind: 'regime' }]
      : [],
  );

const stepIn = (
  channel: Channel,
  covariates: Map<string, Sampled>,
  first: number,
) =>
  channel.covariates.find((id) => {
    const series = covariates.get(id);
    if (series == null) {
      return false;
    }
    const spread = Math.max(...series.values) - Math.min(...series.values);
    const around = series.values.slice(
      Math.max(0, first - STEP_LOOKBACK),
      first + STEP_LOOKBACK + 1,
    );
    return (
      spread > 0 &&
      Math.max(...around) - Math.min(...around) > STEP_SHARE * spread
    );
  }) ?? null;

const sustainedMeans = (points: Scored[], observed: boolean[]) =>
  points.map((_, i) => {
    if (i < SUSTAINED_POINTS - 1) {
      return 0;
    }
    const recent = points.slice(i - SUSTAINED_POINTS + 1, i + 1);
    const contiguous =
      (recent.at(-1)?.index ?? 0) - (recent[0]?.index ?? 0) ===
        SUSTAINED_POINTS - 1 &&
      recent.every((candidate) => observed[candidate.index] === true);
    return contiguous
      ? Math.abs(
          recent.reduce(
            (total, candidate) =>
              total +
              Math.max(
                -SUSTAINED_CLIP,
                Math.min(SUSTAINED_CLIP, candidate.deviation),
              ),
            0,
          ) / SUSTAINED_POINTS,
        )
      : 0;
  });

export const calibrate = (
  points: Scored[],
  sustained: number[],
  horizon: number,
  threshold: number,
) => {
  const windows = Math.floor(points.length / horizon);
  const peaks = Array.from({ length: windows }, (_, w) =>
    Math.max(
      0,
      ...points
        .slice(w * horizon, (w + 1) * horizon)
        .map((point) => point.score),
    ),
  );
  const cutoff = quantile(peaks, 1 - CLEAN_TRIM);
  const clean = peaks
    .map((peak, w) => ({ peak, w }))
    .filter(({ peak }) => peak <= cutoff)
    .map(({ w }) => w);
  const inClean = <T>(values: T[]) =>
    clean.flatMap((w) => values.slice(w * horizon, (w + 1) * horizon));
  return {
    clean_windows: clean.length,
    windows,
    point: Math.max(
      threshold,
      quantile(
        inClean(points).map((point) => point.score),
        CLEAN_QUANTILE,
      ),
    ),
    sustained: Math.max(
      SUSTAINED_DEVIATION,
      quantile(inClean(sustained), CLEAN_QUANTILE),
    ),
  };
};

const flags = (
  points: Scored[],
  sustained: number[],
  observed: boolean[],
  limits: { point: number; sustained: number },
): Flag[] =>
  points.flatMap((point, i): Flag[] => {
    if (observed[point.index] !== true) {
      return [];
    }
    if (point.score > limits.point) {
      return [{ index: point.index, kind: 'point' }];
    }
    return (sustained[i] ?? 0) > limits.sustained
      ? [{ index: point.index, kind: 'sustained' }]
      : [];
  });

const groupFlags = (flagged: Flag[]) => {
  const groups: Flag[][] = [];
  const byIndex = new Map<number, Flag>();
  for (const flag of flagged) {
    if (!byIndex.has(flag.index)) {
      byIndex.set(flag.index, flag);
    }
  }
  for (const flag of [...byIndex.values()].toSorted(
    (a, b) => a.index - b.index,
  )) {
    const group = groups.at(-1);
    const last = group?.at(-1);
    if (
      group != null &&
      last != null &&
      flag.index - last.index <= MERGE_GAP + 1
    ) {
      group.push(flag);
    } else {
      groups.push([flag]);
    }
  }
  return groups;
};

const severityOf = (ratio: number): Severity => {
  if (ratio >= 4) {
    return 'alert';
  }
  return ratio >= 2 ? 'warn' : 'info';
};

const STEP_DISCOUNT = 8;

type DetectInput = Scope & {
  signals: string[];
  covariates: 'auto' | string[];
  threshold: number;
};

export const detectAnomalies = async (input: DetectInput) => {
  const graph = loadGraph();
  const targets = [...new Set(input.signals)].map((id) => {
    const node = getNode(graph, id);
    if (!isSeries(node)) {
      throw new ForgeError('Signal is an event, not a measured series', {
        llm: `${id} is an event list; use investigate or its slab for it, and detect anomalies on measured metrics.`,
        internal: { id },
      });
    }
    return node;
  });
  const runId = await resolveRunId(input.run_id);
  const scope = { run_id: runId, from: input.from, to: input.to };
  const covariatesOf = pickCovariates(
    graph,
    targets.map((node) => node.id),
    input.covariates,
  );
  const covariateNodes = [...new Set(Object.values(covariatesOf).flat())].map(
    (id) => getNode(graph, id) as SeriesNode,
  );
  const shape = await shapeFor([...targets, ...covariateNodes], targets, scope);
  const sampled = await fetchSeries(
    [...targets, ...covariateNodes],
    scope,
    shape.grid,
  );
  const channels: Channel[] = targets.map((node) => ({
    node,
    sampled: sampled.get(node.id) ?? { values: [], observed: [] },
    covariates: covariatesOf[node.id] ?? [],
  }));
  const covariates = new Map(
    covariateNodes.flatMap((node) => {
      const series = sampled.get(node.id);
      return series == null || !series.observed.some(Boolean)
        ? []
        : [[node.id, series] as const];
    }),
  );
  const starts = windowStarts(shape, channels);
  if (starts.length === 0) {
    throw new ForgeError('Not enough overlapping data for anomaly detection', {
      llm: 'The chosen signals are not recorded together long enough in this range; detect them one at a time or widen the range.',
      internal: { ...scope, signals: input.signals },
    });
  }
  const cacheKey = [
    channels.map((channel) => channel.node.id).join(','),
    [...covariates.keys()].join(','),
    runId,
    input.from,
    input.to,
    shape.grid.firstBin,
    shape.grid.length,
    shape.grid.binMs,
  ].join('|');
  const failures: Array<{ model: string; error: string }> = [];
  let result: (Forecast & { model: string }) | null = null;
  for (const model of MODELS) {
    try {
      result = await forecast(
        model,
        shape,
        starts,
        channels,
        covariates,
        cacheKey,
      );
      break;
    } catch (error) {
      failures.push({ model: model.id, error: errorMessage(error) });
      log('Forecast model failed', {
        model: model.id,
        error: errorMessage(error),
      });
    }
  }
  const binS = shape.grid.binMs / 1000;
  const perSignal = channels.map((channel, c) => {
    const reference = scoreReference(channel, shape, starts, covariates);
    const points =
      result == null
        ? reference
        : scoreChannel(channel, c, shape, starts, result);
    const sustained = sustainedMeans(points, channel.sampled.observed);
    const limits = calibrate(points, sustained, shape.horizon, input.threshold);
    const medians = rollingMedians(reference);
    const regime = regimeLimit(medians, shape.horizon);
    const referenceAt = new Map(reference.map((point) => [point.index, point]));
    const byIndex = new Map(points.map((point) => [point.index, point]));
    const sustainedAt = new Map(
      points.map((point, i) => [point.index, sustained[i] ?? 0]),
    );
    const events = groupFlags([
      ...flags(points, sustained, channel.sampled.observed, limits),
      ...regimeFlags(reference, medians, regime, channel.sampled.observed),
    ]).map((group) => {
      const scored = group
        .map((flag) => byIndex.get(flag.index))
        .filter((point) => point != null);
      const peak = scored.reduce((best, point) =>
        Math.max(point.score, Math.abs(point.deviation)) >
        Math.max(best.score, Math.abs(best.deviation))
          ? point
          : best,
      );
      const first = group[0]?.index ?? peak.index;
      const last = group.at(-1)?.index ?? peak.index;
      const kinds = [...new Set(group.map((flag) => flag.kind))];
      const referenceZ = Math.max(
        ...group.map((flag) =>
          Math.abs(referenceAt.get(flag.index)?.deviation ?? 0),
        ),
      );
      const ratio = Math.max(
        ...scored.map((point) => point.score / limits.point),
        ...group.map(
          (flag) => (sustainedAt.get(flag.index) ?? 0) / limits.sustained,
        ),
        kinds.includes('regime') ? referenceZ / regime : 0,
      );
      const duration = (last - first + 1) * binS;
      const step =
        duration <= TRANSIENT_S && !kinds.includes('regime')
          ? stepIn(channel, covariates, peak.index)
          : null;
      const severity = severityOf(step == null ? ratio : ratio / STEP_DISCOUNT);
      return {
        signal: channel.node.id,
        start: isoOf(shape.grid, first),
        end: isoOf(shape.grid, last + 1),
        duration_s: round(duration),
        kind: kinds.join('+'),
        peak_at: isoOf(shape.grid, peak.index),
        peak_score: round(peak.score),
        severity_ratio: round(ratio),
        severity,
        observed: round(peak.value),
        expected: round(peak.median),
        band: [round(peak.lo), round(peak.hi)],
        unit: channel.node.unit,
        reference_z: round(referenceZ),
        reference_agrees: referenceZ > regime,
        at_covariate_step: step,
        covariates: Object.fromEntries(
          [...covariates].map(([id, series]) => [
            id,
            round(series.values[peak.index] ?? Number.NaN),
          ]),
        ),
        first,
        last,
        peakIndex: peak.index,
      };
    });
    return { channel, points, limits: { ...limits, regime }, events };
  });
  const allEvents = perSignal.flatMap((signal) => signal.events);
  const jointWindow = Math.round(
    ((JOINT_WINDOW_S[1000 / shape.grid.binMs] ?? 2) * 1000) / shape.grid.binMs,
  );
  const joint = jointEvents(allEvents, jointWindow, shape.grid);
  const view = (event: (typeof allEvents)[number]) => {
    const { first: _first, last: _last, peakIndex: _peak, ...rest } = event;
    return rest;
  };
  return {
    kind: 'chart' as const,
    id: outputId('chart'),
    chart: anomalyChart(perSignal, joint, shape, runId),
    signals: channels.map((channel) => channel.node.id),
    run_id: runId,
    from: input.from,
    to: input.to,
    grid_hz: 1000 / shape.grid.binMs,
    context: shape.context,
    horizon: shape.horizon,
    points_scored: starts.length * shape.horizon,
    model:
      result == null
        ? { id: 'reference_only', failures }
        : {
            id: result.model,
            band: result.band,
            multivariate:
              MODELS.find((model) => model.id === result.model)?.joint ===
                true && channels.length > 1,
          },
    covariates: covariatesOf,
    method: `${result?.model ?? 'The reference model alone'} forecasts ${channels.length > 1 ? 'the signals jointly' : 'the signal'} from up to ${shape.context} points of history and the covariates measured in the same window. Each signal's thresholds are calibrated on its clean windows (all but the 5% with the largest exceedance): a point is flagged above the 99.8th percentile of clean exceedance (at least the requested threshold in band widths), a stretch when its 10-point mean deviation exceeds the clean 99.8th percentile. A run-wide reference (the median and robust spread of the signal at the same levels of its two main covariates, per quarter of the range) flags regime shifts the forecast absorbs into its context: 10 points whose median deviation exceeds the 99.8th percentile of its clean windows (at least ${REFERENCE_Z} robust sigma). A short event that starts with a step in an explaining covariate (a command starting) is marked at_covariate_step and its severity is judged on an eight times wider margin. Events of different signals within ${(jointWindow * shape.grid.binMs) / 1000} s form joint events.`,
    per_signal: perSignal.map(({ channel, limits, events }) => ({
      signal: channel.node.id,
      unit: channel.node.unit,
      gap_share: round(
        1 -
          channel.sampled.observed.filter(Boolean).length /
            Math.max(1, channel.sampled.observed.length),
      ),
      calibration: {
        point_threshold: round(limits.point),
        sustained_threshold: round(limits.sustained),
        regime_threshold: round(limits.regime),
        clean_windows: limits.clean_windows,
        windows: limits.windows,
      },
      event_count: events.length,
      events: events
        .toSorted((a, b) => b.severity_ratio - a.severity_ratio)
        .slice(0, MAX_EVENTS)
        .map(view),
      spark: sparkline(channel.sampled.values),
    })),
    joint_events: joint,
    gaps_note:
      'Missing samples are forward-filled and never scored, so data gaps, dropouts and reboots do not show up here; use the brownout_and_gaps slab or investigate reboots for them.',
  };
};

type EventRecord = {
  signal: string;
  first: number;
  last: number;
  peakIndex: number;
  severity_ratio: number;
  observed: number;
  expected: number;
  unit: string;
};

export const jointEvents = (
  events: EventRecord[],
  window: number,
  grid: Grid,
) => {
  const sorted = events.toSorted((a, b) => a.first - b.first);
  const clusters: EventRecord[][] = [];
  let reach = Number.NEGATIVE_INFINITY;
  for (const event of sorted) {
    const cluster = clusters.at(-1);
    if (cluster != null && event.first <= reach + window) {
      cluster.push(event);
      reach = Math.max(reach, event.last);
    } else {
      clusters.push([event]);
      reach = event.last;
    }
  }
  return clusters
    .filter((cluster) => new Set(cluster.map((event) => event.signal)).size > 1)
    .map((cluster) => {
      const lead = cluster[0];
      const ratio = Math.max(...cluster.map((event) => event.severity_ratio));
      return {
        start: isoOf(grid, Math.min(...cluster.map((event) => event.first))),
        end: isoOf(grid, Math.max(...cluster.map((event) => event.last)) + 1),
        signals: [...new Set(cluster.map((event) => event.signal))],
        leading_signal: lead?.signal ?? null,
        severity: severityOf(ratio),
        members: cluster.map((event) => ({
          signal: event.signal,
          peak_at: isoOf(grid, event.peakIndex),
          observed: event.observed,
          expected: event.expected,
          unit: event.unit,
        })),
      };
    });
};

const anomalyChart = (
  perSignal: Array<{
    channel: Channel;
    points: Scored[];
    events: Array<EventRecord & { severity: Severity; kind: string }>;
  }>,
  joint: ReturnType<typeof jointEvents>,
  shape: Shape,
  runId: string,
): Chart['chart'] => {
  const byIndex = perSignal.map(
    ({ points }) => new Map(points.map((point) => [point.index, point])),
  );
  const indices = [
    ...new Set(
      perSignal.flatMap(({ points }) => points.map((point) => point.index)),
    ),
  ].toSorted((a, b) => a - b);
  const peaks = new Set(
    perSignal.flatMap(({ events }) => events.map((event) => event.peakIndex)),
  );
  const step = Math.max(1, Math.ceil(indices.length / CHART_POINTS));
  const kept = indices.filter((index, i) => i % step === 0 || peaks.has(index));
  const rows = kept.map((index) => ({
    t: timeOf(shape.grid, index),
    ...Object.fromEntries(
      perSignal.flatMap(({ channel }, c) => {
        const point = byIndex[c]?.get(index);
        const id = channel.node.id;
        return [
          [
            id,
            channel.sampled.observed[index] === true && point != null
              ? round(point.value)
              : null,
          ],
          [`${id}_expected`, point == null ? null : round(point.median)],
          [`${id}_lo`, point == null ? null : round(point.lo)],
          [`${id}_hi`, point == null ? null : round(point.hi)],
        ];
      }),
    ),
  }));
  return {
    type: 'line',
    title: `Anomalies in ${perSignal.map(({ channel }) => channel.node.label.toLowerCase()).join(', ')}, run ${runId}`,
    layout: perSignal.length > 1 ? 'stacked' : 'overlay',
    x: { field: 't', label: 'time', time: true },
    series: perSignal.flatMap(({ channel }) => [
      {
        field: channel.node.id,
        label: channel.node.label,
        unit: channel.node.unit,
        panel: channel.node.id,
      },
      {
        field: `${channel.node.id}_expected`,
        label: 'expected',
        unit: channel.node.unit,
        panel: channel.node.id,
        dashed: true,
      },
    ]),
    rows,
    bands: perSignal.map(({ channel }) => ({
      field_lo: `${channel.node.id}_lo`,
      field_hi: `${channel.node.id}_hi`,
      label: 'forecast band',
      series: channel.node.id,
    })),
    markers: [
      ...perSignal.flatMap(({ channel, events }) =>
        events
          .toSorted((a, b) => b.severity_ratio - a.severity_ratio)
          .slice(0, MAX_EVENTS)
          .map((event) => ({
            x: timeOf(shape.grid, event.first),
            x_end: timeOf(shape.grid, event.last + 1),
            label: `${channel.node.label} ${event.kind}: ${event.observed} ${event.unit}, expected ${event.expected} ${event.unit}`,
            severity: event.severity,
            series: channel.node.id,
          })),
      ),
      ...joint.map((event) => ({
        x: Date.parse(event.start),
        x_end: Date.parse(event.end),
        label: `joint: ${event.signals.join(' + ')}, led by ${event.leading_signal ?? ''}`,
        severity: event.severity,
      })),
    ],
  };
};

const signalList = () =>
  [...loadGraph().nodes.values()]
    .filter(isSeries)
    .map((node) => `${node.id} (${node.unit})`)
    .join(', ');

export const detectAnomaliesTool = forgeTool({
  title: 'Detect anomalies',
  description: `Flags anomalies in one to four related robot signals at once with a time-series foundation model (Chronos-2 via tsfm.ai). The signals are forecast jointly as one multivariate series, given covariates that the metric graph says explain or drive them (picked automatically, or pass your own), and measured in the same window, so an event means the value went beyond what its load explains. Thresholds are calibrated per signal on its clean windows. Each signal gets its own events (observed, expected, band, covariates at the peak, whether the run-wide reference model agrees, whether it started with a step in a covariate such as a command starting) and events of different signals that overlap become joint events naming the signal that moved first.
How to use it well:
- Pass related signals together (battery_voltage with battery_current and motor_current, wifi_rtt with uplink_kbps, zed_fps with tracking_confidence) to see whether they moved together and which led.
- Transients (stalls, current spikes, jolts, short sags) need 10 Hz: pass from and to covering at most 15 minutes around the moment of interest. Longer ranges and 1 Hz signals (Jetson, camera health, Wi-Fi) run at 1 Hz.
- severity alert means at least four times the calibrated threshold, warn at least two; info events are noise level. Trust events the reference agrees with most; a short event at_covariate_step is usually start-up inrush. Kind regime means the signal stayed off its usual relation with its covariates for a while (a stall, a stuck sensor, a pushed wall).
- Gaps (dropouts, reboots) are never scored; use investigate with reboots or data_gaps, or the brownout_and_gaps slab.
Signals: ${signalList()}.`,
  input: z.object({
    signals: z
      .array(z.string())
      .min(1)
      .max(MAX_TARGETS)
      .describe(
        'Metric ids from metric_graph, e.g. ["battery_voltage", "motor_current"]',
      ),
    covariates: z
      .union([z.literal('auto'), z.array(z.string()).max(MAX_COVARIATES)])
      .default('auto')
      .describe(
        "'auto' picks the explaining metrics from the graph; [] forecasts from history alone",
      ),
    run_id: z
      .string()
      .default('latest')
      .describe("Run id from list_runs, 'latest' or 'previous'"),
    from: z
      .string()
      .default('1970-01-01 00:00:00')
      .describe(
        'Start of the time range, UTC robot clock; default is the whole run',
      ),
    to: z
      .string()
      .default('2100-01-01 00:00:00')
      .describe('End of the time range, UTC robot clock'),
    threshold: z
      .number()
      .positive()
      .default(1)
      .describe(
        'Lowest point threshold in band widths outside the 5-95% band; calibration may raise it',
      ),
  }),
  run: async (input) => await detectAnomalies(input),
  forModel: ({ chart: _chart, ...summary }) => ({
    ...summary,
    shown_to_user: true,
  }),
});

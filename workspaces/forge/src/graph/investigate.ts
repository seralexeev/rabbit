import { ForgeError } from '../errors.ts';
import { parseAt, runDay, runFor, toIso } from '../moment.ts';
import {
  type Chart,
  type GraphEdgeType,
  type GraphView,
  type Severity,
  outputId,
} from '../output.ts';
import { windowEvents } from '../timeline.ts';
import {
  EDGE_TYPES,
  type EventNode,
  type Link,
  type MetricGraph,
  type MetricNode,
  type SeriesNode,
  causeChains,
  getNode,
  isSeries,
  loadGraph,
} from './graph.ts';
import {
  FAST_MAX_MS,
  type Grid,
  type Sampled,
  type Scope,
  extent,
  fetchEvents,
  fetchSeries,
  gridFor,
  isoOf,
  timeOf,
} from './series.ts';
import { leadLag, robustZ, round, sparkline, strength } from './stats.ts';

const BASELINE_S = 30;
const MAX_LAG_S = 3;
const EVENT_LOOKBACK_S = 15;
const EVENT_CONTEXT_S = 300;
const EVENT_BUCKET_MS = 1000;
const FOCUS_PAD_S = 10;
const CONTEXT_BEFORE_S = 20;
const CONTEXT_AFTER_S = 5;
const CORRELATION_PAD_S = 30;
const MAX_NODES = 14;
const MAX_HYPOTHESES = 5;
const STRONG_Z = 6;
const NOTABLE_Z = 3;
const PRIOR: Record<string, number> = {
  physics: 1,
  design: 0.95,
  observed: 0.85,
};

export type InvestigateInput = {
  symptom: string;
  run_id?: string | undefined;
  from?: string | undefined;
  to?: string | undefined;
  at?: string | undefined;
  depth: number;
  edge_types?: GraphEdgeType[] | undefined;
};

type Profile = {
  node: SeriesNode;
  sampled: Sampled;
  z: number[];
  baseline: number[];
};

type Focus = { start: number; end: number; peak: number; direction: 1 | -1 };

type LinkScore = {
  link: Link;
  score: number;
  r: number | null;
  lag_s: number | null;
  cause_z: number;
  cause_peak: number | null;
};

const pickEvent = async (
  node: EventNode,
  runId: string,
  input: InvestigateInput,
) => {
  const events = await fetchEvents(node, {
    run_id: runId,
    from: input.from ?? '1970-01-01 00:00:00',
    to: input.to ?? '2100-01-01 00:00:00',
  });
  const [first] = events;
  if (first == null) {
    throw new ForgeError('No events of this kind in the run', {
      llm: `There are no ${node.label.toLowerCase()} in run ${runId} and the chosen range. Say so, or investigate a metric instead.`,
      internal: { node: node.id, runId },
    });
  }
  const at = input.at == null ? null : parseAt(input.at, await runDay(runId));
  const distance = (event: { start: number; end: number | null }) =>
    at == null
      ? 0
      : Math.max(0, event.start - at, at - (event.end ?? event.start));
  const chosen = events.reduce((best, event) =>
    distance(event) < distance(best) ? event : best,
  );
  return {
    time: chosen.start,
    end:
      node.events.end == null ? chosen.start + EVENT_BUCKET_MS : chosen.start,
    count: events.length,
  };
};

const candidates = (
  graph: MetricGraph,
  symptom: string,
  depth: number,
  types: readonly GraphEdgeType[],
) => {
  const chains = causeChains(graph, symptom, depth, types)
    .filter((chain) =>
      chain.every((link, i) => i === 0 || link.edge.type !== 'decomposes_into'),
    )
    .toSorted((a, b) => a.length - b.length);
  const kept = new Set<string>([symptom]);
  for (const chain of chains) {
    for (const link of chain) {
      if (kept.size < MAX_NODES || kept.has(link.cause)) {
        kept.add(link.cause);
      }
    }
  }
  return {
    nodes: [...kept].map((id) => getNode(graph, id)),
    chains: chains.filter((chain) =>
      chain.every((link) => kept.has(link.cause)),
    ),
  };
};

const profile = (node: SeriesNode, sampled: Sampled, grid: Grid): Profile => {
  const { z, baseline } = robustZ(
    sampled.values,
    sampled.observed,
    Math.round((BASELINE_S * 1000) / grid.binMs),
    node.floor,
  );
  return { node, sampled, z, baseline };
};

const peakIn = (z: number[], start: number, end: number, direction: number) => {
  let best = { index: -1, z: 0 };
  for (let i = Math.max(0, start); i <= Math.min(z.length - 1, end); i++) {
    const value = (z[i] ?? 0) * direction;
    if (value > best.z) {
      best = { index: i, z: value };
    }
  }
  return best;
};

const seriesFocus = (
  symptom: Profile,
  grid: Grid,
  at: number | null,
): Focus => {
  const z = symptom.z;
  const pad = Math.round((FOCUS_PAD_S * 1000) / grid.binMs);
  let peak = 0;
  if (at == null) {
    for (let i = 0; i < z.length; i++) {
      if (Math.abs(z[i] ?? 0) > Math.abs(z[peak] ?? 0)) {
        peak = i;
      }
    }
  } else {
    const target = Math.round(at / grid.binMs) - grid.firstBin;
    for (
      let i = Math.max(0, target - pad);
      i <= Math.min(z.length - 1, target + pad);
      i++
    ) {
      if (Math.abs(z[i] ?? 0) > Math.abs(z[peak] ?? 0) || peak < target - pad) {
        peak = i;
      }
    }
  }
  let start = peak;
  while (start > 0 && Math.abs(z[start - 1] ?? 0) > NOTABLE_Z) {
    start--;
  }
  let end = peak;
  while (end < z.length - 1 && Math.abs(z[end + 1] ?? 0) > NOTABLE_Z) {
    end++;
  }
  return {
    start: Math.max(0, start - pad),
    end: Math.min(z.length - 1, end + pad),
    peak,
    direction: (z[peak] ?? 0) < 0 ? -1 : 1,
  };
};

const scoreLink = (
  link: Link,
  profiles: Map<string, Profile>,
  directions: Map<string, 1 | -1>,
  focus: Focus,
  grid: Grid,
): LinkScore => {
  const cause = profiles.get(link.cause);
  const effect = profiles.get(link.effect);
  const sign = link.edge.sign === 'negative' ? -1 : 1;
  const prior =
    (PRIOR[link.edge.evidence] ?? 0.8) *
    (link.edge.type === 'correlates_with' ? 0.8 : 1);
  if (cause == null) {
    return {
      link,
      score: 0,
      r: null,
      lag_s: null,
      cause_z: 0,
      cause_peak: null,
    };
  }
  const effectDirection = directions.get(link.effect) ?? 1;
  const direction = (effectDirection * sign) as 1 | -1;
  const maxLag = Math.round((MAX_LAG_S * 1000) / grid.binMs);
  const found = peakIn(cause.z, focus.start - maxLag, focus.end, direction);
  const peak = found.index < 0 ? { index: focus.end, z: 0 } : found;
  const anomaly = strength(peak.z);
  if (!directions.has(link.cause)) {
    directions.set(link.cause, direction);
  }
  if (effect == null) {
    return {
      link,
      score: round(prior * anomaly),
      r: null,
      lag_s: round(((peak.index - focus.end) * grid.binMs) / 1000),
      cause_z: round(peak.z * direction),
      cause_peak: peak.index,
    };
  }
  const pad = Math.round((CORRELATION_PAD_S * 1000) / grid.binMs);
  const from = Math.max(0, focus.start - pad);
  const to = Math.min(cause.z.length, focus.end + pad);
  const clip = (values: number[]) =>
    values.slice(from, to).map((value) => Math.max(-20, Math.min(20, value)));
  const { r, lag } = leadLag(clip(cause.z), clip(effect.z), maxLag, sign);
  const leads = lag >= 0 ? 1 : 0.3;
  return {
    link,
    score: round(
      prior *
        (0.4 * Math.max(0, r) +
          0.4 * anomaly +
          0.2 * leads * Math.max(anomaly, Math.max(0, r))),
    ),
    r: round(r * sign),
    lag_s: round((lag * grid.binMs) / 1000),
    cause_z: round(peak.z * direction),
    cause_peak: peak.index,
  };
};

const statusOf = (z: number): Severity | 'ok' => {
  if (Math.abs(z) >= STRONG_Z) {
    return 'alert';
  }
  return Math.abs(z) >= NOTABLE_Z ? 'warn' : 'ok';
};

const describeNode = (
  profile: Profile | undefined,
  index: number | null,
  grid: Grid,
) => {
  if (profile == null || index == null) {
    return null;
  }
  const unit = profile.node.unit;
  return {
    at: isoOf(grid, index).slice(11, 23),
    value: round(profile.sampled.values[index] ?? Number.NaN),
    baseline: round(profile.baseline[index] ?? Number.NaN),
    unit,
    z: round(profile.z[index] ?? 0),
  };
};

const summarize = (
  score: LinkScore,
  profiles: Map<string, Profile>,
  grid: Grid,
) => {
  const peak = describeNode(
    profiles.get(score.link.cause),
    score.cause_peak,
    grid,
  );
  let what = `${score.link.cause} shows no data in the window`;
  if (peak != null) {
    what =
      Math.abs(peak.z) < NOTABLE_Z
        ? `${score.link.cause} stayed normal (${peak.value} ${peak.unit}, baseline ${peak.baseline})`
        : `${score.link.cause} reached ${peak.value} ${peak.unit} at ${peak.at} against a baseline of ${peak.baseline} (z ${peak.z})`;
  }
  const coupling =
    score.r == null
      ? ''
      : `, r ${score.r} with ${score.link.effect} at a lag of ${score.lag_s} s`;
  return `${what}${coupling}`;
};

const chainScore = (scores: LinkScore[]) => {
  const values = scores.map((score) => score.score);
  const geometric =
    values.reduce((product, value) => product * Math.max(value, 1e-3), 1) **
    (1 / values.length);
  return round(0.5 * geometric + 0.5 * Math.min(...values));
};

export const investigate = async (input: InvestigateInput) => {
  const graph = loadGraph();
  const symptom = getNode(graph, input.symptom);
  const types = input.edge_types ?? EDGE_TYPES;
  const runId = await runFor(input);
  const { nodes, chains } = candidates(graph, symptom.id, input.depth, types);
  const seriesNodes = nodes.filter(isSeries);
  if (seriesNodes.length === 0) {
    throw new ForgeError('Nothing to investigate around this metric', {
      llm: 'The graph has no measured neighbours for this metric with the chosen edge types; widen edge_types or depth.',
      internal: { symptom: symptom.id },
    });
  }
  let scope: Scope;
  let event: { time: number; end: number; count: number } | null = null;
  if (isSeries(symptom)) {
    scope = {
      run_id: runId,
      from: input.from ?? '1970-01-01 00:00:00',
      to: input.to ?? '2100-01-01 00:00:00',
    };
  } else {
    event = await pickEvent(symptom, runId, input);
    scope = {
      run_id: runId,
      from: toIso(event.time - EVENT_CONTEXT_S * 1000),
      to: toIso(event.end + 1000),
    };
  }
  const span = await extent(seriesNodes, scope);
  const grid = gridFor(span, span.last - span.first <= FAST_MAX_MS ? 10 : 1);
  const sampled = await fetchSeries(seriesNodes, scope, grid);
  const profiles = new Map(
    seriesNodes.flatMap((node) => {
      const series = sampled.get(node.id);
      return series == null || !series.observed.some(Boolean)
        ? []
        : [[node.id, profile(node, series, grid)] as const];
    }),
  );
  let focus: Focus;
  if (event == null) {
    const symptomProfile = profiles.get(symptom.id);
    if (symptomProfile == null) {
      throw new ForgeError('No samples for this metric in the run', {
        llm: `Run ${runId} has no ${symptom.id} data in the chosen range.`,
        internal: { symptom: symptom.id, ...scope },
      });
    }
    const at = input.at == null ? null : parseAt(input.at, await runDay(runId));
    focus = seriesFocus(symptomProfile, grid, at);
  } else {
    const end = Math.min(
      grid.length - 1,
      Math.round(event.end / grid.binMs) - grid.firstBin,
    );
    focus = {
      start: Math.max(
        0,
        end - Math.round((EVENT_LOOKBACK_S * 1000) / grid.binMs),
      ),
      end,
      peak: end,
      direction: 1,
    };
  }
  const directions = new Map<string, 1 | -1>([[symptom.id, focus.direction]]);
  const linkScores = new Map<string, LinkScore>();
  const keyOf = (link: Link) =>
    `${link.cause}>${link.effect}>${link.edge.type}`;
  for (const chain of chains) {
    for (const link of chain) {
      if (!linkScores.has(keyOf(link))) {
        linkScores.set(
          keyOf(link),
          scoreLink(link, profiles, directions, focus, grid),
        );
      }
    }
  }
  const isBreakdown = (chain: Link[]) =>
    chain.length === 1 && chain[0]?.edge.type === 'decomposes_into';
  const breakdown = chains.filter(isBreakdown).flatMap((chain) => {
    const score =
      chain[0] == null ? undefined : linkScores.get(keyOf(chain[0]));
    return score == null
      ? []
      : [
          {
            part: score.link.cause,
            score: score.score,
            r: score.r,
            summary: summarize(score, profiles, grid),
          },
        ];
  });
  const hypotheses = chains
    .filter((chain) => !isBreakdown(chain))
    .map((chain) => {
      const scores = chain.map((link) => linkScores.get(keyOf(link)));
      return { chain, scores: scores.filter((score) => score != null) };
    })
    .filter(({ chain, scores }) => scores.length === chain.length)
    .map(({ chain, scores }) => ({
      chain: [symptom.id, ...chain.map((link) => link.cause)],
      score: chainScore(scores),
      evidence: scores.map((score) => ({
        cause: score.link.cause,
        effect: score.link.effect,
        relation: score.link.edge.type,
        score: score.score,
        r: score.r,
        lag_s: score.lag_s,
        cause_peak: describeNode(
          profiles.get(score.link.cause),
          score.cause_peak,
          grid,
        ),
        summary: summarize(score, profiles, grid),
      })),
    }))
    .toSorted((a, b) =>
      b.score === a.score ? b.chain.length - a.chain.length : b.score - a.score,
    )
    .filter(
      (hypothesis, i, all) =>
        !all
          .slice(0, i)
          .some(
            (better) =>
              better.score >= hypothesis.score &&
              hypothesis.chain.every((id, j) => better.chain[j] === id),
          ),
    )
    .slice(0, MAX_HYPOTHESES);
  const examined = new Set([symptom.id, ...(hypotheses[0]?.chain ?? [])]);
  const ruledOut = [...linkScores.values()]
    .filter((score) => examined.has(score.link.effect))
    .filter((score) => profiles.has(score.link.cause) && score.score < 0.15)
    .map((score) => ({
      metric: score.link.cause,
      relation: score.link.edge.type,
      why: score.link.edge.why,
      summary: summarize(score, profiles, grid),
    }));
  const noData = nodes
    .filter((node) => isSeries(node) && !profiles.has(node.id))
    .map((node) => node.id);
  const best = hypotheses[0];
  const contextWindow = {
    run_id: runId,
    from: timeOf(grid, focus.start) - CONTEXT_BEFORE_S * 1000,
    to: timeOf(grid, focus.end) + CONTEXT_AFTER_S * 1000,
    at: event?.time ?? timeOf(grid, focus.peak),
  };
  const contextEvents = await windowEvents(contextWindow);
  const view = graphView({
    graph,
    symptom,
    nodes,
    linkScores: [...linkScores.values()],
    profiles,
    focus,
    grid,
    chain: best?.chain ?? [symptom.id],
    title: `Investigation of ${symptom.label.toLowerCase()}, run ${runId}`,
  });
  return {
    ...view,
    symptom: symptom.id,
    run_id: runId,
    range: { from: isoOf(grid, 0), to: isoOf(grid, grid.length - 1) },
    focus: {
      from: isoOf(grid, focus.start),
      to: isoOf(grid, focus.end),
      peak_at: isoOf(grid, focus.peak),
      symptom_peak:
        event == null
          ? describeNode(profiles.get(symptom.id), focus.peak, grid)
          : null,
      event_at: event == null ? null : new Date(event.time).toISOString(),
      events_in_run: event?.count ?? null,
    },
    grid_hz: 1000 / grid.binMs,
    method:
      'Each metric is compared with its own trailing 30 s median (robust z). Links are scored on how strongly the cause deviates in the focus window in the expected direction, how well it co-moves with its effect (cross-correlation within 3 s of lag) and whether it leads. A chain scores the blend of its geometric mean and its weakest link. context lists the commands, state transitions and logs from 20 s before the focus to 5 s after it.',
    hypotheses,
    breakdown,
    ruled_out: ruledOut,
    no_data: noData,
    context: {
      from: toIso(contextWindow.from),
      to: toIso(contextWindow.to),
      note: 'Commands with their sender, state transitions (navigation mode, safety faults, missions, exploration, tracking, Wi-Fi), HUD heartbeat silences, configuration changes and log records around the focus; offset_s is relative to the event or the symptom peak. Use them to name what the robot was told and what its software reported, alongside the metric evidence.',
      events: contextEvents,
    },
  };
};

const roleOf = (id: string, symptom: string, chain: string[]) => {
  if (id === symptom) {
    return 'symptom' as const;
  }
  return chain.includes(id) ? ('cause' as const) : ('context' as const);
};

const graphView = ({
  graph,
  symptom,
  nodes,
  linkScores,
  profiles,
  focus,
  grid,
  chain,
  title,
}: {
  graph: MetricGraph;
  symptom: MetricNode;
  nodes: MetricNode[];
  linkScores: LinkScore[];
  profiles: Map<string, Profile>;
  focus: Focus;
  grid: Grid;
  chain: string[];
  title: string;
}): GraphView => {
  const pad = Math.round((CORRELATION_PAD_S * 1000) / grid.binMs);
  const from = Math.max(0, focus.start - pad);
  const to = Math.min(grid.length, focus.end + pad + 1);
  const chainEdges = new Set(
    chain.slice(1).map((cause, i) => `${cause}>${chain[i] ?? ''}`),
  );
  const nodeScore = new Map<string, LinkScore>();
  for (const score of linkScores) {
    const known = nodeScore.get(score.link.cause);
    if (known == null || score.score > known.score) {
      nodeScore.set(score.link.cause, score);
    }
  }
  const viewNodes = nodes.map((node) => {
    const nodeProfile = profiles.get(node.id);
    const score = nodeScore.get(node.id);
    const index =
      node.id === symptom.id ? focus.peak : (score?.cause_peak ?? null);
    const peak = describeNode(nodeProfile, index, grid);
    return {
      id: node.id,
      label: node.label,
      group: node.group,
      ...(isSeries(node) ? { unit: node.unit } : {}),
      role: roleOf(node.id, symptom.id, chain),
      ...(score == null ? {} : { score: score.score }),
      status:
        node.id === symptom.id && !isSeries(node)
          ? ('alert' as const)
          : statusOf(peak?.z ?? 0),
      ...(peak == null ? {} : { value: `${peak.value} ${peak.unit}` }),
      ...(nodeProfile == null
        ? {}
        : { spark: sparkline(nodeProfile.sampled.values.slice(from, to)) }),
    };
  });
  const viewEdges = linkScores.map((score) => ({
    from: score.link.edge.from,
    to: score.link.edge.to,
    type: score.link.edge.type,
    label: score.link.edge.type.replaceAll('_', ' '),
    why: score.link.edge.why,
    score: score.score,
    ...(score.lag_s == null ? {} : { lag_s: score.lag_s }),
  }));
  const chartNodes = chain
    .map((id) => profiles.get(id))
    .filter((value) => value != null);
  return {
    kind: 'graph',
    id: outputId('graph'),
    title,
    nodes: viewNodes,
    edges: viewEdges,
    highlights: {
      nodes: chain,
      edges: graph.edges
        .filter(
          (edge) =>
            chainEdges.has(`${edge.from}>${edge.to}`) ||
            chainEdges.has(`${edge.to}>${edge.from}`),
        )
        .map((edge): [string, string] => [edge.from, edge.to]),
    },
    ...(chartNodes.length === 0
      ? {}
      : { chart: chainChart(chartNodes, grid, from, to, focus, linkScores) }),
  };
};

const CHART_POINTS = 1500;

const chainChart = (
  chain: Profile[],
  grid: Grid,
  from: number,
  to: number,
  focus: Focus,
  linkScores: LinkScore[],
): Chart['chart'] => {
  const step = Math.max(1, Math.ceil((to - from) / CHART_POINTS));
  const rows = [];
  for (let i = from; i < to; i += step) {
    rows.push({
      t: timeOf(grid, i),
      ...Object.fromEntries(
        chain.map((item) => [
          item.node.id,
          item.sampled.observed[i] === true
            ? round(item.sampled.values[i] ?? Number.NaN)
            : null,
        ]),
      ),
    });
  }
  const peaks = chain.flatMap((item) => {
    const score = linkScores
      .filter((candidate) => candidate.link.cause === item.node.id)
      .toSorted((a, b) => b.score - a.score)[0];
    const index = score?.cause_peak;
    return index == null || Math.abs(score?.cause_z ?? 0) < NOTABLE_Z
      ? []
      : [
          {
            x: timeOf(grid, index),
            label: `${item.node.label}: ${round(item.sampled.values[index] ?? Number.NaN)} ${item.node.unit} (z ${score?.cause_z})`,
            severity:
              statusOf(score?.cause_z ?? 0) === 'alert'
                ? ('alert' as const)
                : ('warn' as const),
            series: item.node.id,
          },
        ];
  });
  return {
    type: 'line',
    title: 'Causal chain, focus window shaded',
    layout: 'stacked',
    x: { field: 't', label: 'time', time: true },
    series: chain.map((item) => ({
      field: item.node.id,
      label: item.node.label,
      unit: item.node.unit,
      panel: item.node.id,
    })),
    rows,
    markers: [
      {
        x: timeOf(grid, focus.start),
        x_end: timeOf(grid, focus.end),
        label: 'focus window',
        severity: 'info',
      },
      ...peaks,
    ],
  };
};

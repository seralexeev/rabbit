import z from 'zod';

import { ForgeError } from '../errors.ts';
import { forgeTool } from '../forge_tool.ts';
import { type GraphView, outputId } from '../output.ts';
import {
  EDGE_TYPES,
  type MetricEdge,
  type MetricGraph,
  getNode,
  isSeries,
  loadGraph,
  neighbours,
  shortestPath,
} from './graph.ts';
import { investigate } from './investigate.ts';

const EdgeTypes = z
  .array(z.enum(EDGE_TYPES))
  .min(1)
  .optional()
  .describe('Only follow these relations; default all');

const nodeView = (
  graph: MetricGraph,
  id: string,
  role: 'focus' | 'context',
) => {
  const node = getNode(graph, id);
  return {
    id,
    label: node.label,
    group: node.group,
    ...(isSeries(node) ? { unit: node.unit } : {}),
    role,
  };
};

const edgeView = (edge: MetricEdge) => ({
  from: edge.from,
  to: edge.to,
  type: edge.type,
  label: edge.type.replaceAll('_', ' '),
  why: edge.why,
});

const around = (
  graph: MetricGraph,
  focus: string[],
  hops: number,
  types: ReadonlyArray<(typeof EDGE_TYPES)[number]>,
) => {
  const reached = new Set(focus);
  let frontier = [...focus];
  for (let hop = 0; hop < hops; hop++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const edge of neighbours(graph, id, types)) {
        for (const end of [edge.from, edge.to]) {
          if (!reached.has(end)) {
            reached.add(end);
            next.push(end);
          }
        }
      }
    }
    frontier = next;
  }
  return graph.edges.filter(
    (edge) =>
      types.includes(edge.type) &&
      reached.has(edge.from) &&
      reached.has(edge.to),
  );
};

export const metricGraph = (input: {
  node?: string | undefined;
  to?: string | undefined;
  hops: number;
  edge_types?: Array<(typeof EDGE_TYPES)[number]> | undefined;
}): GraphView & { metrics: unknown } => {
  const graph = loadGraph();
  const types = input.edge_types ?? EDGE_TYPES;
  let edges: MetricEdge[];
  let focus: string[];
  let title: string;
  if (input.node == null) {
    if (input.to != null) {
      throw new ForgeError('A path needs both ends', {
        llm: 'Pass node as the start and to as the end of the path.',
      });
    }
    focus = [];
    edges = graph.edges.filter((edge) => types.includes(edge.type));
    title = 'Metric graph';
  } else if (input.to == null) {
    getNode(graph, input.node);
    focus = [input.node];
    edges = around(graph, focus, input.hops, types);
    title = `Metrics around ${getNode(graph, input.node).label.toLowerCase()}`;
  } else {
    getNode(graph, input.to);
    const path = shortestPath(graph, input.node, input.to, types);
    if (path == null) {
      throw new ForgeError('No path between these metrics', {
        llm: `The graph links ${input.node} and ${input.to} through no chain of the chosen relations.`,
        internal: { from: input.node, to: input.to },
      });
    }
    focus = [input.node, input.to];
    edges = path;
    title = `Path from ${input.node} to ${input.to}`;
  }
  const ids = new Set([
    ...focus,
    ...edges.flatMap((edge) => [edge.from, edge.to]),
    ...(input.node == null ? graph.nodes.keys() : []),
  ]);
  const nodes = [...ids].map((id) =>
    nodeView(graph, id, focus.includes(id) ? 'focus' : 'context'),
  );
  return {
    kind: 'graph',
    id: outputId('graph'),
    title,
    nodes,
    edges: edges.map(edgeView),
    highlights: {
      nodes: focus,
      edges:
        input.to == null
          ? []
          : edges.map((edge): [string, string] => [edge.from, edge.to]),
    },
    metrics: [...ids].map((id) => {
      const node = getNode(graph, id);
      return {
        id,
        description: node.description,
        ...(isSeries(node)
          ? { unit: node.unit, table: node.source.table, rate_hz: node.hz }
          : { from_slab: node.events.slab }),
        slabs: node.slabs,
      };
    }),
  };
};

export const metricGraphTool = forgeTool({
  title: 'Metric graph',
  description: `The typed graph of the robot's metrics and how they relate: nodes are measured signals and events (with unit, source table and the slabs that fetch them), edges are directed relations with a reason. Relations: decomposes_into (a total into its parts), drives and causes (physical cause to effect), explains (a load or command that sets the expected level), correlates_with (moves together, no direction), guards (a safety signal that blocks an action) and symptom_of (an observed event to the signal behind it). Pass node to get its neighbourhood, node and to for the shortest path between two metrics, nothing for the whole graph. The user sees the diagram, so describe only what matters. Use it to plan which signals to check for a why question, or to answer how two signals relate.`,
  input: z.object({
    node: z.string().optional().describe('Metric id, e.g. motor_current'),
    to: z.string().optional().describe('Second metric id for a path'),
    hops: z.number().int().min(1).max(3).default(1),
    edge_types: EdgeTypes,
  }),
  run: async (input) => await Promise.resolve(metricGraph(input)),
  forModel: ({ id, title, edges, metrics }) => ({
    kind: 'graph',
    id,
    title,
    shown_to_user: true,
    edges: edges.map(
      (edge) => `${edge.from} ${edge.type} ${edge.to}: ${edge.why}`,
    ),
    metrics,
  }),
});

export const investigateTool = forgeTool({
  title: 'Investigate',
  description: `Root-cause analysis over the metric graph. Give a symptom metric or event (for example reboots, stalls, data_gaps, nav_faults, container_crashes, battery_voltage, motor_current, wifi_rtt, zed_fps, log_errors) and a moment or range; it walks the graph upstream breadth-first, fetches every candidate cause over the same window, scores each link on anomaly strength in the focus window, co-movement and lead or lag, and returns ranked causal chains with evidence, the causes it ruled out, and an interactive diagram plus a stacked chart of the top chain for the user. Its context lists the commands (with their sender), state transitions (navigation mode, safety faults, missions, exploration, tracking, Wi-Fi), HUD heartbeat silences and log records from 20 s before the focus to 5 s after it.
- For events (reboots, stalls, data_gaps) pass at with the approximate time (HH:MM or HH:MM:SS, UTC robot clock); it picks the nearest event and looks at the 15 s before it within 5 minutes of context. The run is found from at when run_id is omitted.
- For a metric, pass from and to (at most 15 minutes keeps 10 Hz resolution) and optionally at to pick the deviation nearest that moment; otherwise it takes the strongest deviation in the range.
- A link score above 0.6 is strong evidence, 0.3 to 0.6 supporting, below 0.15 rules the link out. Report what was ruled out as well as the top chain, and confirm with slabs before stating a cause.`,
  input: z.object({
    symptom: z.string().describe('Metric or event id from metric_graph'),
    run_id: z
      .string()
      .optional()
      .describe(
        "Run id, 'latest' or 'previous'; omitted, the run containing at, else latest",
      ),
    at: z.string().optional().describe('Moment of interest, HH:MM[:SS] UTC'),
    from: z.string().optional().describe('Start of the range, UTC robot clock'),
    to: z.string().optional().describe('End of the range, UTC robot clock'),
    depth: z.number().int().min(1).max(3).default(2),
    edge_types: EdgeTypes,
  }),
  run: async (input) => await investigate(input),
  forModel: ({
    chart: _chart,
    nodes,
    edges: _edges,
    highlights: _highlights,
    ...summary
  }) => ({
    ...summary,
    shown_to_user: true,
    sparks: Object.fromEntries(
      nodes.flatMap((node) =>
        node.spark == null ||
        summary.hypotheses[0]?.chain.includes(node.id) !== true
          ? []
          : [[node.id, node.spark.filter((_, i) => i % 2 === 0)]],
      ),
    ),
  }),
});

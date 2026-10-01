import { readFileSync } from 'node:fs';
import { parse as parseYaml } from 'yaml';
import z from 'zod';

import { ROOT } from '../config.ts';
import { ForgeError } from '../errors.ts';
import type { GraphEdgeType } from '../output.ts';
import { loadSlabs } from '../slabs/slab.ts';

export const EDGE_TYPES = [
  'decomposes_into',
  'drives',
  'causes',
  'explains',
  'correlates_with',
  'guards',
  'symptom_of',
] as const satisfies readonly GraphEdgeType[];

const IDENTIFIER = /^[a-z][a-z0-9_]*$/;

const SeriesSource = z.strictObject({
  table: z.string().regex(IDENTIFIER),
  expr: z.string().min(1),
  agg: z.enum(['mean', 'rate']).default('mean'),
});

const EventSource = z.strictObject({
  slab: z.string(),
  time: z.string(),
  end: z.string().optional(),
  where: z.record(z.string(), z.union([z.string(), z.number()])).default({}),
});

const NodeFile = z.strictObject({
  label: z.string(),
  group: z.string(),
  description: z.string(),
  unit: z.string().optional(),
  source: SeriesSource.optional(),
  events: EventSource.optional(),
  hz: z.number().positive().optional(),
  floor: z.number().positive().optional(),
  slabs: z.array(z.string()).min(1),
});

const EdgeFile = z.strictObject({
  from: z.string(),
  to: z.string(),
  type: z.enum(EDGE_TYPES),
  why: z.string(),
  evidence: z.enum(['physics', 'design', 'observed']),
  sign: z.enum(['positive', 'negative']).default('positive'),
});

const GraphFile = z.strictObject({
  nodes: z.record(z.string().regex(IDENTIFIER), NodeFile),
  edges: z.array(EdgeFile),
});

export type SeriesNode = z.infer<typeof NodeFile> & {
  id: string;
  source: z.infer<typeof SeriesSource>;
  unit: string;
  hz: number;
  floor: number;
};

export type EventNode = z.infer<typeof NodeFile> & {
  id: string;
  events: z.infer<typeof EventSource>;
};

export type MetricNode = SeriesNode | EventNode;

export type MetricEdge = z.infer<typeof EdgeFile>;

export type MetricGraph = {
  nodes: Map<string, MetricNode>;
  edges: MetricEdge[];
};

export const isSeries = (node: MetricNode): node is SeriesNode =>
  'source' in node && node.source != null;

const graphErrors = (
  graph: z.infer<typeof GraphFile>,
  slabColumns: Map<string, Set<string>>,
) => {
  const errors: string[] = [];
  for (const [id, node] of Object.entries(graph.nodes)) {
    if ((node.source == null) === (node.events == null)) {
      errors.push(`node ${id} needs exactly one of source or events`);
    }
    if (
      node.source != null &&
      (node.unit == null || node.hz == null || node.floor == null)
    ) {
      errors.push(`series node ${id} needs unit, hz and floor`);
    }
    for (const slab of node.slabs) {
      if (!slabColumns.has(slab)) {
        errors.push(`node ${id} links unknown slab ${slab}`);
      }
    }
    if (node.events != null) {
      const columns = slabColumns.get(node.events.slab);
      for (const column of [
        node.events.time,
        ...(node.events.end == null ? [] : [node.events.end]),
        ...Object.keys(node.events.where),
      ]) {
        if (columns?.has(column) !== true) {
          errors.push(
            `event node ${id} reads ${node.events.slab}.${column}, which the slab does not project`,
          );
        }
      }
    }
  }
  const seen = new Set<string>();
  for (const edge of graph.edges) {
    for (const end of [edge.from, edge.to]) {
      if (!(end in graph.nodes)) {
        errors.push(
          `edge ${edge.from} -> ${edge.to} names unknown node ${end}`,
        );
      }
    }
    if (edge.from === edge.to) {
      errors.push(`edge ${edge.from} -> ${edge.to} is a self loop`);
    }
    const key = `${edge.from}|${edge.to}|${edge.type}`;
    if (seen.has(key)) {
      errors.push(`edge ${edge.from} -> ${edge.to} (${edge.type}) is repeated`);
    }
    seen.add(key);
  }
  return errors;
};

export const parseGraph = (
  text: string,
  slabColumns: Map<string, Set<string>>,
): MetricGraph => {
  const parsed = GraphFile.safeParse(parseYaml(text));
  if (!parsed.success) {
    throw new ForgeError('Invalid metric graph file', {
      internal: { error: z.prettifyError(parsed.error) },
    });
  }
  const errors = graphErrors(parsed.data, slabColumns);
  if (errors.length > 0) {
    throw new ForgeError('Invalid metric graph', { internal: { errors } });
  }
  return {
    nodes: new Map(
      Object.entries(parsed.data.nodes).map(([id, node]) => [
        id,
        { ...node, id } as MetricNode,
      ]),
    ),
    edges: parsed.data.edges,
  };
};

let cache: MetricGraph | null = null;

export const loadGraph = (): MetricGraph => {
  cache ??= parseGraph(
    readFileSync(new URL('graph/metrics.yml', ROOT), 'utf8'),
    new Map(
      loadSlabs().map((slab) => [slab.id, new Set(Object.keys(slab.columns))]),
    ),
  );
  return cache;
};

export const getNode = (graph: MetricGraph, id: string): MetricNode => {
  const node = graph.nodes.get(id);
  if (node == null) {
    throw new ForgeError('Unknown metric', {
      llm: `There is no metric '${id}' in the graph. Metrics: ${[...graph.nodes.keys()].join(', ')}.`,
      internal: { id },
    });
  }
  return node;
};

export type Link = { cause: string; effect: string; edge: MetricEdge };

export const causeOf = (edge: MetricEdge): Link =>
  edge.type === 'symptom_of' || edge.type === 'decomposes_into'
    ? { cause: edge.to, effect: edge.from, edge }
    : { cause: edge.from, effect: edge.to, edge };

const touches = (edge: MetricEdge, id: string) =>
  edge.from === id || edge.to === id;

export const neighbours = (
  graph: MetricGraph,
  id: string,
  types: readonly GraphEdgeType[] = EDGE_TYPES,
) =>
  graph.edges.filter((edge) => types.includes(edge.type) && touches(edge, id));

export const upstreamLinks = (
  graph: MetricGraph,
  effect: string,
  types: readonly GraphEdgeType[] = EDGE_TYPES,
): Link[] =>
  graph.edges
    .filter((edge) => types.includes(edge.type))
    .flatMap((edge): Link[] => {
      if (edge.type === 'correlates_with') {
        if (edge.to === effect) {
          return [{ cause: edge.from, effect, edge }];
        }
        return edge.from === effect ? [{ cause: edge.to, effect, edge }] : [];
      }
      const link = causeOf(edge);
      return link.effect === effect ? [link] : [];
    });

export const causeChains = (
  graph: MetricGraph,
  symptom: string,
  depth: number,
  types: readonly GraphEdgeType[] = EDGE_TYPES,
): Link[][] => {
  const chains: Link[][] = [];
  const walk = (chain: Link[], visited: Set<string>) => {
    const head = chain.at(-1)?.cause ?? symptom;
    const next = upstreamLinks(graph, head, types).filter(
      (link) => !visited.has(link.cause),
    );
    if (chain.length > 0) {
      chains.push(chain);
    }
    if (chain.length >= depth) {
      return;
    }
    for (const link of next) {
      walk([...chain, link], new Set([...visited, link.cause]));
    }
  };
  walk([], new Set([symptom]));
  return chains;
};

export const shortestPath = (
  graph: MetricGraph,
  from: string,
  to: string,
  types: readonly GraphEdgeType[] = EDGE_TYPES,
): MetricEdge[] | null => {
  const previous = new Map<string, { node: string; edge: MetricEdge } | null>([
    [from, null],
  ]);
  const queue = [from];
  for (let current = queue.shift(); current != null; current = queue.shift()) {
    if (current === to) {
      const path: MetricEdge[] = [];
      for (
        let step = previous.get(to);
        step != null;
        step = previous.get(step.node)
      ) {
        path.push(step.edge);
      }
      return path.toReversed();
    }
    for (const edge of neighbours(graph, current, types)) {
      const other = edge.from === current ? edge.to : edge.from;
      if (!previous.has(other)) {
        previous.set(other, { node: current, edge });
        queue.push(other);
      }
    }
  }
  return null;
};

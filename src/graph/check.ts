import { resolveRunId } from '../runs.ts';
import { isSeries, loadGraph } from './graph.ts';
import { extent, fetchSeries, gridFor } from './series.ts';

export const checkGraph = async () => {
  const graph = loadGraph();
  const nodes = [...graph.nodes.values()].filter(isSeries);
  const scope = {
    run_id: await resolveRunId('latest'),
    from: '1970-01-01 00:00:00',
    to: '2100-01-01 00:00:00',
  };
  const span = await extent(nodes, scope);
  const series = await fetchSeries(nodes, scope, gridFor(span, 0.1));
  return {
    run_id: scope.run_id,
    nodes: graph.nodes.size,
    edges: graph.edges.length,
    metrics: nodes.map((node) => ({
      id: node.id,
      observed_10s_bins:
        series.get(node.id)?.observed.filter(Boolean).length ?? 0,
    })),
  };
};

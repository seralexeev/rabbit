import z from 'zod';

import { forgeTool } from './forge_tool.ts';
import { isSeries, loadGraph } from './graph/graph.ts';
import { KV_SUBJECTS, LOG_STREAM, LOG_SUBJECTS } from './ingest/jetstream.ts';
import { table } from './output.ts';
import { describeSchema } from './schema.ts';
import { STREAMS } from './streams.ts';

const subjectsByTable = () => {
  const subjects = new Map<string, string[]>([
    ['logs', [`${LOG_SUBJECTS} (JetStream ${LOG_STREAM})`]],
    ['kv_changes', [`${KV_SUBJECTS} (key-value bucket rabbit)`]],
  ]);
  for (const stream of STREAMS) {
    subjects.set(stream.table, [
      ...new Set([...(subjects.get(stream.table) ?? []), stream.subject]),
    ]);
  }
  return subjects;
};

export const listMetricsTool = forgeTool({
  title: 'List metrics',
  description: `Catalog of everything Forge records about the robot. metrics: every metric and event of the metric graph with its id (the name investigate, detect_anomalies and metric_graph take), group, unit, the table and expression it reads, the NATS subject it comes from, its rate and the slabs that show it. tables: every table with the NATS subjects that feed it and what it holds. Filter with query (matches id, label, group, table or subject). Use it to find the right metric id or table before calling other tools.`,
  input: z.object({
    query: z
      .string()
      .optional()
      .describe(
        'Case-insensitive filter, e.g. wifi, commands, logs, rabbit.cmd',
      ),
  }),
  run: async ({ query }) => {
    const subjects = subjectsByTable();
    const matches = (...parts: string[]) =>
      query == null ||
      parts.join(' ').toLowerCase().includes(query.toLowerCase());
    const metrics = [...loadGraph().nodes.values()].map((node) => {
      const tableName = isSeries(node) ? node.source.table : '';
      return {
        id: node.id,
        label: node.label,
        group: node.group,
        kind: isSeries(node) ? 'series' : 'event',
        unit: isSeries(node) ? node.unit : '',
        table: tableName,
        source: isSeries(node)
          ? `${node.source.agg === 'rate' ? 'rate of ' : ''}${node.source.expr}`
          : `slab ${node.events.slab}`,
        subject: (subjects.get(tableName) ?? []).join(', '),
        rate_hz: isSeries(node) ? node.hz : null,
        slabs: node.slabs.join(', '),
      };
    });
    const tables = (await describeSchema()).map((schemaTable) => ({
      table: schemaTable.name,
      subjects: (subjects.get(schemaTable.name) ?? []).join(', '),
      description: schemaTable.description,
      columns: schemaTable.columns.length,
    }));
    return {
      ...table(
        metrics.filter((metric) =>
          matches(
            metric.id,
            metric.label,
            metric.group,
            metric.table,
            metric.subject,
          ),
        ),
        { title: 'Robot metrics' },
      ),
      tables: tables.filter((entry) =>
        matches(entry.table, entry.subjects, entry.description),
      ),
    };
  },
});

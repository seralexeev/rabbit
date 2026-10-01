import { generateText, isStepCount, tool } from 'ai';
import { stringify } from 'yaml';
import z from 'zod';

import { ForgeError, describeForModel } from '../errors.ts';
import { forgeTool } from '../forge_tool.ts';
import { table } from '../output.ts';
import { resolveRunParams } from '../runs.ts';
import { describeSchema } from '../schema.ts';
import { searchSlabs } from '../slabs/search_slabs.ts';
import { getSlab } from '../slabs/slab.ts';
import { checkSql, runSql } from '../sql/query_gate.ts';
import { AGENT_PROVIDER_OPTIONS, agentModel, prompt } from './model.ts';

const SYSTEM = prompt('sql_agent.md');

const MAX_STEPS = 6;

const EXAMPLE_SLABS = 3;

const Finalize = z.object({
  title: z.string(),
  sql: z.string(),
  params: z.record(z.string(), z.union([z.string(), z.number()])).default({}),
});

type Committed = z.infer<typeof Finalize>;

const context = async (request: string) => {
  const schema = await describeSchema();
  const examples = searchSlabs(request, EXAMPLE_SLABS).map(({ slab }) => {
    const { title, description, sql, columns } = getSlab(slab);
    return { slab, title, description, sql, columns };
  });
  return `# Schema\n\n${stringify(schema)}\n# Nearest slabs\n\n${stringify(examples)}`;
};

export const writeQuery = async (request: string) => {
  const model = agentModel();
  let committed: Committed | null = null;
  const rejections: unknown[] = [];
  const finalize = tool({
    description:
      'Validate the SQL with the static gate and ClickHouse EXPLAIN and commit it.',
    inputSchema: Finalize,
    execute: async (query) => {
      try {
        const params = await resolveRunParams(query.params);
        await checkSql(query.sql, params);
        committed = { ...query, params };
        return { ok: true };
      } catch (error) {
        const rejection = describeForModel(error);
        rejections.push(rejection);
        return { ok: false, ...rejection };
      }
    },
  });
  await generateText({
    model,
    instructions: SYSTEM,
    messages: [
      { role: 'user', content: await context(request) },
      { role: 'user', content: `# Request\n\n${request}` },
    ],
    tools: { finalize },
    toolChoice: 'required',
    providerOptions: AGENT_PROVIDER_OPTIONS,
    stopWhen: [isStepCount(MAX_STEPS), () => committed != null],
  });
  const query = committed as Committed | null;
  if (query == null) {
    throw new ForgeError('SQL agent ended without a valid query', {
      llm: 'Writing a query for this request failed validation repeatedly. Answer with what you have and say this part could not be computed.',
      internal: { request, rejections },
    });
  }
  const result = await runSql(query.sql, query.params);
  return {
    ...table(result.rows, {
      title: query.title,
      rowCount: result.row_count,
      truncated: result.truncated,
    }),
    sql: query.sql,
    params: query.params,
  };
};

export const writeQueryTool = forgeTool({
  title: 'Write query',
  description:
    'Heavy path: a SQL sub-agent writes a new ClickHouse query for a request no slab covers, validates it (static gate and EXPLAIN), runs it and returns the SQL, its params and the rows. Describe the result you need precisely: metrics and how to aggregate them, grain, filters and run.',
  input: z.object({ request: z.string() }),
  run: async ({ request }) => await writeQuery(request),
});

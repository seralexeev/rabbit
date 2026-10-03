import { generateText, isStepCount } from 'ai';
import z from 'zod';

import { detectAnomaliesTool } from '../anomaly/detect.ts';
import { forgeTool } from '../forge_tool.ts';
import { investigateTool, metricGraphTool } from '../graph/tools.ts';
import { logsAroundTool, searchLogsTool } from '../logs.ts';
import { timelineTool } from '../timeline.ts';
import { listRunsTool, runSlabTool, searchSlabsTool } from '../tools.ts';
import { groundingContext } from './context.ts';
import {
  AGENT_PROVIDER_OPTIONS,
  LANGUAGE_REMINDER,
  agentModel,
  asAiTools,
  prompt,
} from './model.ts';
import { writeQueryTool } from './sql_agent.ts';

export const SYSTEM = `${prompt('ask.md')}\n\n${prompt('robot.md')}`;

const MAX_STEPS = 10;

export const ANALYSIS_TOOLS = {
  list_runs: listRunsTool,
  search_slabs: searchSlabsTool,
  run_slab: runSlabTool,
  write_query: writeQueryTool,
  detect_anomalies: detectAnomaliesTool,
  metric_graph: metricGraphTool,
  investigate: investigateTool,
  timeline: timelineTool,
  search_logs: searchLogsTool,
  logs_around: logsAroundTool,
};

type ToolName = keyof typeof ANALYSIS_TOOLS;

type AskTrace = Array<{ tool: string; input: unknown; error?: string }>;

type AskResult = {
  answer: string;
  path: 'fast' | 'heavy' | 'none';
  trace: AskTrace;
};

const answerPath = (trace: AskTrace): AskResult['path'] => {
  const succeeded = (name: ToolName) =>
    trace.some((call) => call.tool === name && call.error == null);
  if (succeeded('write_query')) {
    return 'heavy';
  }
  return succeeded('run_slab') ? 'fast' : 'none';
};

export const ask = async (question: string): Promise<AskResult> => {
  const model = agentModel();
  const result = await generateText({
    model,
    instructions: SYSTEM,
    messages: [
      { role: 'user', content: await groundingContext(question) },
      { role: 'user', content: `# Question\n\n${question}` },
      LANGUAGE_REMINDER,
    ],
    allowSystemInMessages: true,
    tools: asAiTools(ANALYSIS_TOOLS),
    stopWhen: isStepCount(MAX_STEPS),
    providerOptions: AGENT_PROVIDER_OPTIONS,
  });
  const trace: AskTrace = result.steps.flatMap((step) =>
    step.content.flatMap((part) => {
      if (part.type === 'tool-result') {
        return [{ tool: part.toolName, input: part.input }];
      }
      return part.type === 'tool-error'
        ? [
            {
              tool: part.toolName,
              input: part.input,
              error: String(part.error),
            },
          ]
        : [];
    }),
  );
  return { answer: result.text, path: answerPath(trace), trace };
};

export const askTool = forgeTool({
  title: 'Ask',
  description:
    'Answers a natural-language question about the robot runs with an agent: it runs a reviewed slab when one fits (fast path) and otherwise writes, validates and runs new SQL (heavy path). Every number in the answer comes from the returned data; the trace lists the slabs and queries used.',
  input: z.object({ question: z.string() }),
  run: async ({ question }) => await ask(question),
});

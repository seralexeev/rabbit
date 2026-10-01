import { createOpenAI } from '@ai-sdk/openai';
import { type JSONValue, type Tool, tool } from 'ai';
import { readFileSync } from 'node:fs';

import { consumeApproval } from '../approvals.ts';
import { config } from '../config.ts';
import { ForgeError, errorMessage } from '../errors.ts';
import { type ForgeTool, modelView } from '../forge_tool.ts';

export const agentModel = () => {
  if (config.openAiApiKey == null) {
    throw new ForgeError('OpenAI API key is not configured', {
      llm: 'The agent is unavailable because OPEN_AI_KEY is missing from the Forge .env file. Use the other tools directly.',
      internal: { file: '.env', variable: 'OPEN_AI_KEY' },
    });
  }
  return createOpenAI({ apiKey: config.openAiApiKey })(config.model);
};

export const LANGUAGE_REMINDER = {
  role: 'system' as const,
  content:
    'Write your reply in English, even though the user may have written in another language.',
};

export const AGENT_PROVIDER_OPTIONS = {
  openai: { reasoningEffort: 'low' },
} as const;

export const prompt = (file: string) =>
  readFileSync(new URL(file, import.meta.url), 'utf8');

const failureText = (error: unknown) =>
  error instanceof ForgeError && error.llm != null
    ? `${error.message} — ${error.llm}`
    : errorMessage(error);

export const asAiTool = (forgeTool: ForgeTool): Tool =>
  tool({
    description: forgeTool.description,
    inputSchema: forgeTool.input,
    execute: async (input: unknown, { toolCallId }) => {
      try {
        if (forgeTool.requiresApproval === true) {
          consumeApproval(toolCallId);
        }
        return await forgeTool.run(forgeTool.input.parse(input));
      } catch (error) {
        throw new ForgeError(failureText(error), { cause: error });
      }
    },
    toModelOutput: ({ output }) => ({
      type: 'json',
      value: modelView(forgeTool, output) as JSONValue,
    }),
  });

export const asAiTools = (tools: Record<string, ForgeTool>) =>
  Object.fromEntries(
    Object.entries(tools).map(([name, forgeTool]) => [
      name,
      asAiTool(forgeTool),
    ]),
  );

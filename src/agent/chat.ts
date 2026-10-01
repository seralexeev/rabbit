import {
  type UIMessage,
  convertToModelMessages,
  isStepCount,
  isTextUIPart,
  streamText,
} from 'ai';
import { randomBytes } from 'node:crypto';

import { recordApprovalRequest } from '../approvals.ts';
import { chartTool } from '../chart.ts';
import { type ForgeTool, approvalConfig } from '../forge_tool.ts';
import { ROBOT_TOOLS } from '../robot.ts';
import { DATA_TOOLS } from '../tools.ts';
import { SYSTEM } from './ask.ts';
import { groundingContext } from './context.ts';
import {
  AGENT_PROVIDER_OPTIONS,
  LANGUAGE_REMINDER,
  agentModel,
  asAiTools,
  prompt,
} from './model.ts';
import { writeQueryTool } from './sql_agent.ts';

const INSTRUCTIONS = `${SYSTEM}\n\n${prompt('chat.md')}`;

const MAX_STEPS = 12;

const APPROVAL_SECRET = randomBytes(32);

export const CHAT_TOOLS: Record<string, ForgeTool> = {
  ...DATA_TOOLS,
  write_query: writeQueryTool,
  chart: chartTool,
  ...ROBOT_TOOLS,
};

const lastUserText = (messages: UIMessage[]) =>
  messages
    .findLast((message) => message.role === 'user')
    ?.parts.filter(isTextUIPart)
    .map((part) => part.text)
    .join(' ') ?? '';

export const chatSettings = async (
  messages: UIMessage[],
  registry: Record<string, ForgeTool> = CHAT_TOOLS,
) => {
  const tools = asAiTools(registry);
  return {
    model: agentModel(),
    instructions: INSTRUCTIONS,
    messages: [
      {
        role: 'user' as const,
        content: await groundingContext(lastUserText(messages)),
      },
      ...(await convertToModelMessages(messages, { tools })),
      LANGUAGE_REMINDER,
    ],
    allowSystemInMessages: true,
    tools,
    toolApproval: approvalConfig(registry),
    experimental_toolApprovalSecret: APPROVAL_SECRET,
    stopWhen: isStepCount(MAX_STEPS),
    providerOptions: AGENT_PROVIDER_OPTIONS,
  };
};

export const chat = async (messages: UIMessage[]) => {
  const settings = await chatSettings(messages);
  const result = streamText({
    ...settings,
    onChunk: ({ chunk }) => {
      if (chunk.type === 'tool-approval-request') {
        recordApprovalRequest(chunk.toolCall.toolCallId);
      }
    },
  });
  return { result, tools: settings.tools };
};

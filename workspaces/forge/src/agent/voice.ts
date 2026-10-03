import z from 'zod';

import { consumeApproval, recordApprovalRequest } from '../approvals.ts';
import { config } from '../config.ts';
import { ForgeError } from '../errors.ts';
import { modelView } from '../forge_tool.ts';
import { SYSTEM } from './ask.ts';
import { CHAT_TOOLS } from './chat.ts';
import { groundingContext } from './context.ts';
import { failureText, prompt } from './model.ts';

const CALLS_URL = 'https://api.openai.com/v1/realtime/calls';
const MAX_HISTORY_TURNS = 20;
const MAX_TOOL_OUTPUT_CHARS = 24_000;

const ENGLISH_RULE =
  'You always write in English. When the user writes in another language, understand it but answer in English.';

const SPOKEN_LANGUAGE_RULE =
  "Reply in the language of the operator's last message, and keep tool parameters, ids and SQL in English.";

export const VOICE_INSTRUCTIONS = `${SYSTEM.replace(ENGLISH_RULE, SPOKEN_LANGUAGE_RULE)}\n\n${prompt('voice.md')}`;

export const VoiceCall = z.object({
  sdp: z.string().min(1).max(20_000),
  history: z
    .array(
      z.object({
        role: z.enum(['user', 'assistant']),
        text: z.string().max(4000),
      }),
    )
    .max(200)
    .default([]),
});

export const VoiceToolCall = z.object({
  call_id: z.string().min(1).max(200),
  name: z.string().min(1).max(100),
  arguments: z.string().max(100_000),
  approved: z.boolean().optional(),
});

type Turn = z.infer<typeof VoiceCall>['history'][number];

export const voiceTools = () =>
  Object.entries(CHAT_TOOLS).map(([name, tool]) => {
    const { $schema: _, ...parameters } = z.toJSONSchema(tool.input, {
      io: 'input',
    });
    return {
      type: 'function',
      name,
      description: tool.description,
      parameters,
    };
  });

const earlierConversation = (history: Turn[]) =>
  history.length === 0
    ? ''
    : `\n\n# Earlier conversation in the panel\n\n${history
        .slice(-MAX_HISTORY_TURNS)
        .map(
          (turn) =>
            `${turn.role === 'user' ? 'Operator' : 'You'}: ${turn.text}`,
        )
        .join('\n\n')}`;

export const voiceSession = async (history: Turn[]) => {
  const question = history.findLast((turn) => turn.role === 'user')?.text;
  return {
    type: 'realtime',
    model: config.voiceModel,
    instructions: `${VOICE_INSTRUCTIONS}\n\n${await groundingContext(question ?? '')}${earlierConversation(history)}`,
    audio: {
      input: {
        noise_reduction: { type: 'near_field' },
        transcription: { model: config.transcriptionModel },
        turn_detection: { type: 'semantic_vad', eagerness: 'auto' },
      },
      output: { voice: config.voice },
    },
    tools: voiceTools(),
    tool_choice: 'auto',
    reasoning: { effort: 'low' },
  };
};

export const openVoiceCall = async ({
  sdp,
  history,
}: z.infer<typeof VoiceCall>) => {
  if (config.openAiApiKey == null) {
    throw new ForgeError('OpenAI API key is not configured', {
      internal: { file: '.env', variable: 'OPEN_AI_KEY' },
    });
  }
  const form = new FormData();
  form.set('sdp', sdp);
  form.set('session', JSON.stringify(await voiceSession(history)));
  const response = await fetch(CALLS_URL, {
    method: 'POST',
    headers: { authorization: `Bearer ${config.openAiApiKey}` },
    body: form,
  });
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 400);
    throw new ForgeError(
      `OpenAI realtime call failed (${response.status}): ${detail}`,
    );
  }
  return await response.text();
};

const clip = (text: string) =>
  text.length <= MAX_TOOL_OUTPUT_CHARS
    ? text
    : `${text.slice(0, MAX_TOOL_OUTPUT_CHARS)}… (output truncated)`;

export type VoiceToolResult =
  | { status: 'approval' }
  | { status: 'ok'; output: unknown; model: string }
  | { status: 'error'; error: string };

export const runVoiceTool = async ({
  call_id,
  name,
  arguments: args,
  approved,
}: z.infer<typeof VoiceToolCall>): Promise<VoiceToolResult> => {
  const tool = Object.hasOwn(CHAT_TOOLS, name) ? CHAT_TOOLS[name] : undefined;
  if (tool == null) {
    return { status: 'error', error: `Unknown tool ${name}` };
  }
  try {
    const input = tool.input.parse(args.trim() === '' ? {} : JSON.parse(args));
    if (tool.requiresApproval === true) {
      if (approved !== true) {
        recordApprovalRequest(call_id);
        return { status: 'approval' };
      }
      consumeApproval(call_id);
    }
    const output = await tool.run(input);
    return {
      status: 'ok',
      output,
      model: clip(JSON.stringify(modelView(tool, output))),
    };
  } catch (error) {
    return { status: 'error', error: failureText(error) };
  }
};

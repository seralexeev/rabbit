import { type UIMessage, isToolUIPart } from 'ai';

import { readLocal, writeLocal } from '../hooks.ts';
import { L } from '../log.ts';

const MESSAGES_KEY = 'rabbit.chat.messages';
const MAX_MESSAGES = 40;
const MAX_OUTPUT_CHARS = 40_000;

type Part = UIMessage['parts'][number];

const mapParts = (messages: UIMessage[], fn: (part: Part) => Part) =>
    messages.map((message) => ({ ...message, parts: message.parts.map(fn) }));

const expireApproval = (part: Part): Part =>
    isToolUIPart(part) && part.state === 'approval-requested'
        ? ({
              ...part,
              state: 'output-denied',
              approval: {
                  ...part.approval,
                  approved: false,
                  reason: 'Approval expired: the page was reloaded before a decision.',
              },
          } as unknown as Part)
        : part;

const SAVED_CHART_ROWS = 300;
const GRAPH_OUTPUT_CHARS = 150_000;

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value != null && !Array.isArray(value);

const thinRows = (rows: unknown[]) => {
    if (rows.length <= SAVED_CHART_ROWS) return rows;
    const step = rows.length / SAVED_CHART_ROWS;
    return Array.from({ length: SAVED_CHART_ROWS }, (_, i) => rows[Math.floor(i * step)]);
};

const thinCharts = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(thinCharts);
    if (!isRecord(value)) return value;
    const next: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) next[key] = thinCharts(child);
    if (value['kind'] === 'chart' && isRecord(value['chart']) && Array.isArray(value['chart']['rows'])) {
        next['chart'] = { ...value['chart'], rows: thinRows(value['chart']['rows']) };
        next['downsampled'] = true;
    }
    return next;
};

const compactOutput = (output: unknown, limit: number) => {
    const size = (value: unknown) => JSON.stringify(value ?? null).length;
    const cap = isRecord(output) && output['kind'] === 'graph' ? Math.max(limit, GRAPH_OUTPUT_CHARS) : limit;
    if (size(output) <= cap) return output;
    const thinned = thinCharts(output);
    return size(thinned) <= cap ? thinned : { note: 'Output not kept in local history.' };
};

const omitOutput =
    (limit: number) =>
    (part: Part): Part =>
        isToolUIPart(part) && part.state === 'output-available'
            ? ({ ...part, output: compactOutput(part.output, limit) } as unknown as Part)
            : part;

export const loadMessages = () =>
    mapParts(
        readLocal<UIMessage[]>(MESSAGES_KEY, (raw) => (Array.isArray(raw) ? (raw as UIMessage[]) : []), []),
        expireApproval,
    );

export const saveMessages = (messages: UIMessage[]) => {
    const recent = messages.slice(-MAX_MESSAGES);
    if (writeLocal(MESSAGES_KEY, mapParts(recent, omitOutput(MAX_OUTPUT_CHARS)))) return;
    if (writeLocal(MESSAGES_KEY, mapParts(recent, omitOutput(0)))) return;
    L.warn('Chat history could not be saved (storage quota)');
};

export const clearMessages = () => writeLocal(MESSAGES_KEY, null);

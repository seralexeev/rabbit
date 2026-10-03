import { type UIMessage, convertToModelMessages } from 'ai';
import { describe, expect, it } from 'vitest';

import {
  CHAT_TOOLS,
  settlePendingTools,
  withLanguageReminder,
} from './agent/chat.ts';
import { asAiTool, asAiTools } from './agent/model.ts';
import {
  APPROVAL_TTL_MS,
  consumeApproval,
  recordApprovalRequest,
} from './approvals.ts';
import { approvalConfig } from './forge_tool.ts';
import { runMissionTool } from './robot.ts';

const MISSION = { steps: [{ type: 'move', forward: 1, right: 0 }] };

describe('mission approval', () => {
  it('asks the operator to approve exactly the tools that require it', () => {
    expect(approvalConfig(CHAT_TOOLS)).toEqual({
      go_to: 'user-approval',
      run_mission: 'user-approval',
      reset_map: 'user-approval',
    });
  });

  it('keeps an approval response last so the approved tool runs', async () => {
    const approved: UIMessage[] = [
      {
        id: 'u',
        role: 'user',
        parts: [{ type: 'text', text: 'Drive forward' }],
      },
      {
        id: 'a',
        role: 'assistant',
        parts: [
          {
            type: 'tool-run_mission',
            toolCallId: 'call-1',
            state: 'approval-responded',
            input: MISSION,
            approval: { id: 'approval-1', approved: true },
          },
        ],
      },
    ];
    const history = await convertToModelMessages(approved, {
      tools: asAiTools(CHAT_TOOLS),
    });
    expect(withLanguageReminder(history).at(-1)?.role).toBe('tool');
  });

  it.each([
    { state: 'approval-requested', approval: { id: 'approval-1' } },
    {
      state: 'approval-responded',
      approval: { id: 'approval-1', approved: true },
    },
    { state: 'input-available' },
  ])(
    'answers a $state call the operator left behind, so the next message can be sent',
    async (pending) => {
      const history: UIMessage[] = [
        {
          id: 'u1',
          role: 'user',
          parts: [{ type: 'text', text: 'Drive forward' }],
        },
        {
          id: 'a',
          role: 'assistant',
          parts: [
            {
              type: 'tool-run_mission',
              toolCallId: 'call-1',
              input: MISSION,
              ...pending,
            } as UIMessage['parts'][number],
          ],
        },
        { id: 'u2', role: 'user', parts: [{ type: 'text', text: 'Status?' }] },
      ];
      const messages = await convertToModelMessages(
        settlePendingTools(history),
        { tools: asAiTools(CHAT_TOOLS) },
      );
      const parts = messages.flatMap(
        (
          message,
        ): Array<{ type: string; toolCallId?: string; output?: unknown }> =>
          Array.isArray(message.content) ? message.content : [],
      );
      const ids = (type: string) =>
        parts
          .filter((part) => part.type === type)
          .map((part) => part.toolCallId);
      expect(ids('tool-call')).toEqual(['call-1']);
      expect(ids('tool-result')).toEqual(['call-1']);
      expect(
        JSON.stringify(
          parts.find((part) => part.type === 'tool-result')?.output,
        ),
      ).toContain('Not run');
    },
  );

  it('leaves the approval in the last message alone so it can run', () => {
    const last: UIMessage = {
      id: 'a',
      role: 'assistant',
      parts: [
        {
          type: 'tool-run_mission',
          toolCallId: 'call-1',
          state: 'approval-responded',
          input: MISSION,
          approval: { id: 'approval-1', approved: true },
        },
      ],
    };
    expect(settlePendingTools([last])).toEqual([last]);
  });

  it('refuses to run a mission whose tool call was never approved', async () => {
    const execute = asAiTool(runMissionTool).execute as (
      input: unknown,
      options: { toolCallId: string },
    ) => Promise<unknown>;
    await expect(
      execute(MISSION, { toolCallId: 'never-approved' }),
    ).rejects.toThrow('Action was not approved');
  });

  it('accepts an approval once and only within its lifetime', () => {
    recordApprovalRequest('call-once', 0);
    expect(() => consumeApproval('call-once', 1000)).not.toThrow();
    expect(() => consumeApproval('call-once', 2000)).toThrow(
      'Action was not approved',
    );
    recordApprovalRequest('call-slow', 0);
    expect(() => consumeApproval('call-slow', 90_000)).not.toThrow();
    recordApprovalRequest('call-late', 0);
    expect(() => consumeApproval('call-late', APPROVAL_TTL_MS + 1)).toThrow(
      'Approval expired',
    );
  });
});

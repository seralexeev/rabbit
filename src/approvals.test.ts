import { describe, expect, it } from 'vitest';

import { CHAT_TOOLS } from './agent/chat.ts';
import { asAiTool } from './agent/model.ts';
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
      run_mission: 'user-approval',
    });
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
      'Approval was already used',
    );
    recordApprovalRequest('call-late', 0);
    expect(() => consumeApproval('call-late', APPROVAL_TTL_MS + 1)).toThrow(
      'Approval expired',
    );
  });
});

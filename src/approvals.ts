import { ForgeError } from './errors.ts';

export const APPROVAL_TTL_MS = 60_000;

const issued = new Map<string, number>();
const used = new Set<string>();

export const recordApprovalRequest = (toolCallId: string, now = Date.now()) => {
  issued.set(toolCallId, now);
};

export const consumeApproval = (toolCallId: string, now = Date.now()) => {
  if (used.has(toolCallId)) {
    throw new ForgeError('Approval was already used', {
      llm: 'This approved action already ran; ask the operator again for a new action.',
      internal: { toolCallId },
    });
  }
  const issuedAt = issued.get(toolCallId);
  if (issuedAt == null) {
    throw new ForgeError('Action was not approved', {
      llm: 'This action needs the operator to approve it in the chat panel first.',
      internal: { toolCallId },
    });
  }
  issued.delete(toolCallId);
  if (now - issuedAt > APPROVAL_TTL_MS) {
    throw new ForgeError('Approval expired', {
      llm: 'The operator approved more than 60 s after the request; propose the action again.',
      internal: { toolCallId },
    });
  }
  used.add(toolCallId);
};

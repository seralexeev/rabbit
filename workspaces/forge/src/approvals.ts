import { ForgeError } from './errors.ts';

export const APPROVAL_TTL_MS = 60_000;

const issued = new Map<string, number>();

export const recordApprovalRequest = (toolCallId: string, now = Date.now()) => {
  for (const [id, issuedAt] of issued) {
    if (now - issuedAt > APPROVAL_TTL_MS) {
      issued.delete(id);
    }
  }
  issued.set(toolCallId, now);
};

export const consumeApproval = (toolCallId: string, now = Date.now()) => {
  const issuedAt = issued.get(toolCallId);
  if (issuedAt == null) {
    throw new ForgeError('Action was not approved', {
      llm: 'This action needs the operator to approve it in the chat panel first, and each approval runs once.',
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
};

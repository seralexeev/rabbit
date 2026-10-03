import { expect, test } from 'vitest';

import { VOICE_INSTRUCTIONS } from './voice.ts';

test('voice replies in the operator language, not English only', () => {
  expect(VOICE_INSTRUCTIONS).not.toContain('always write in English');
  expect(VOICE_INSTRUCTIONS).toContain(
    "language of the operator's last message",
  );
});

import { existsSync, readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';

export const ROOT = new URL('../', import.meta.url);

const envFile = new URL('.env', ROOT);

const fileEnv: Record<string, string | undefined> = existsSync(envFile)
  ? parseEnv(readFileSync(envFile, 'utf8'))
  : {};

const fromFile = (name: string) => {
  const value = fileEnv[name]?.trim();
  return value == null || value.length === 0 ? null : value;
};

export const config = {
  natsUrl: 'nats://192.168.1.53:4222',
  clickhouseUrl: 'http://127.0.0.1:18123',
  openAiApiKey: fromFile('OPEN_AI_KEY'),
  tsfmApiKey: fromFile('TSFM_KEY'),
  chatToken: fromFile('CHAT_TOKEN'),
  model: 'gpt-6-luna',
  chatPort: 18080,
} as const;

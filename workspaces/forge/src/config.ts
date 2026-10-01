import { existsSync, readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';

export const ROOT = new URL('../', import.meta.url);

const envFile = new URL('.env', ROOT);

const settings: Record<string, string | undefined> = existsSync(envFile)
  ? parseEnv(readFileSync(envFile, 'utf8'))
  : process.env;

const setting = (name: string) => {
  const value = settings[name]?.trim();
  return value == null || value.length === 0 ? null : value;
};

export const config = {
  natsUrl: setting('FORGE_NATS_URL') ?? 'nats://192.168.1.53:4222',
  natsPingIntervalMs: 5000,
  natsMaxPingOut: 2,
  clickhouseUrl: setting('FORGE_CLICKHOUSE_URL') ?? 'http://127.0.0.1:18123',
  chatListenHost: setting('FORGE_CHAT_LISTEN_HOST') ?? '127.0.0.1',
  openAiApiKey: setting('OPEN_AI_KEY'),
  tsfmApiKey: setting('TSFM_KEY'),
  model: 'gpt-6-luna',
  chatPort: 18080,
} as const;

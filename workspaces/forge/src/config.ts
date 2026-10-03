import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
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
  dataDir:
    setting('FORGE_DATA_DIR') ??
    fileURLToPath(new URL('../../data/forge', ROOT)),
  syncFrom: setting('FORGE_SYNC_FROM'),
  maxDataBytes: Number(setting('FORGE_MAX_DATA_GB') ?? 50) * 1024 ** 3,
  logConsumer: setting('FORGE_LOG_CONSUMER') ?? 'forge',
  chatListenHost: setting('FORGE_CHAT_LISTEN_HOST') ?? '127.0.0.1',
  openAiApiKey: setting('OPEN_AI_KEY'),
  tsfmApiKey: setting('TSFM_KEY'),
  model: 'gpt-6-luna',
  voiceModel: 'gpt-realtime-2.1',
  voice: 'marin',
  transcriptionModel: 'gpt-transcribe',
  operatorTimeZone: 'Australia/Sydney',
  chatPort: 18080,
} as const;

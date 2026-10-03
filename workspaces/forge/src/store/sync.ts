import { spawn } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

import { config } from '../config.ts';
import { log } from '../log.ts';
import { recover } from './layout.ts';

const FRESH_MS = 30_000;
const RSYNC_VANISHED = 24;
const SSH_KEY = join(homedir(), '.ssh', 'rabbit_id_rsa');

const rsync = async (from: string, to: string) =>
  await new Promise<number>((resolve, reject) => {
    const ssh = [
      'ssh',
      '-o BatchMode=yes',
      '-o ConnectTimeout=3',
      ...(existsSync(SSH_KEY) ? [`-i ${SSH_KEY}`] : []),
    ].join(' ');
    const child = spawn(
      'rsync',
      [
        '-a',
        '--delete',
        '--exclude=*.tmp',
        '-e',
        ssh,
        from.endsWith('/') ? from : `${from}/`,
        `${to}/`,
      ],
      { stdio: ['ignore', 'ignore', 'pipe'] },
    );
    let stderr = '';
    child.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0 || code === RSYNC_VANISHED) {
        resolve(code);
      } else {
        reject(new Error(`rsync exited ${String(code)}: ${stderr.trim()}`));
      }
    });
  });

export const syncMirror = async (from = config.syncFrom) => {
  if (from == null) {
    throw new Error('FORGE_SYNC_FROM is not set');
  }
  mkdirSync(config.dataDir, { recursive: true });
  const started = Date.now();
  if ((await rsync(from, config.dataDir)) === RSYNC_VANISHED) {
    await rsync(from, config.dataDir);
  }
  const removed = recover(config.dataDir);
  return { ms: Date.now() - started, removed: removed.length };
};

let lastSync = 0;
let running: Promise<void> | null = null;
let warnedAt = 0;

export const ensureMirror = async () => {
  if (Date.now() - lastSync < FRESH_MS) {
    return;
  }
  running ??= syncMirror()
    .then(
      () => {
        lastSync = Date.now();
      },
      (error: unknown) => {
        lastSync = Date.now();
        if (Date.now() - warnedAt > 60_000) {
          warnedAt = Date.now();
          log('Mirror sync failed, querying the local copy', {
            error: String(error).slice(0, 300),
          });
        }
      },
    )
    .finally(() => {
      running = null;
    });
  await running;
};

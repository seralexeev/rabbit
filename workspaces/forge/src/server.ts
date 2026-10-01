import {
  type UIMessage,
  createUIMessageStreamResponse,
  toUIMessageStream,
} from 'ai';
import { timingSafeEqual } from 'node:crypto';
import {
  type IncomingMessage,
  type ServerResponse,
  createServer,
} from 'node:http';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

import { chat } from './agent/chat.ts';
import { reader, select } from './clickhouse.ts';
import { config } from './config.ts';
import { ForgeError, errorMessage } from './errors.ts';
import { log } from './log.ts';
import { startLiveStatus } from './robot.ts';

const ALLOWED_ORIGIN = /^https:\/\/(localhost|dev\.rabbit)(:\d+)?$/;

const ALLOWED_HOSTS = new Set([
  `127.0.0.1:${config.chatPort}`,
  `localhost:${config.chatPort}`,
]);

export const TOKEN_HEADER = 'x-forge-token';

const allowedOrigin = (request: IncomingMessage) => {
  const origin = request.headers.origin;
  return origin != null && ALLOWED_ORIGIN.test(origin);
};

const tokenMatches = (request: IncomingMessage) => {
  const sent = request.headers[TOKEN_HEADER];
  if (config.chatToken == null || typeof sent !== 'string') {
    return false;
  }
  const expected = Buffer.from(config.chatToken);
  const actual = Buffer.from(sent);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
};

const corsHeaders = (request: IncomingMessage): Record<string, string> => {
  const origin = request.headers.origin;
  return origin != null && allowedOrigin(request)
    ? {
        'access-control-allow-origin': origin,
        'access-control-allow-methods': 'GET, POST, OPTIONS',
        'access-control-allow-headers': `content-type, ${TOKEN_HEADER}`,
        'access-control-max-age': '600',
        vary: 'Origin',
      }
    : { vary: 'Origin' };
};

const sendJson = (
  request: IncomingMessage,
  response: ServerResponse,
  status: number,
  body: unknown,
) => {
  response.writeHead(status, {
    ...corsHeaders(request),
    'content-type': 'application/json',
  });
  response.end(JSON.stringify(body));
};

const readBody = async (request: IncomingMessage) => {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString('utf8');
};

const computeHealth = async () => {
  const [clickhouse, latest, run] = await Promise.all([
    reader.ping().then((result) => result.success),
    select<{ age_s: number | null }>(
      reader,
      "SELECT dateDiff('millisecond', max(ts), now64(3)) / 1000 AS age_s FROM power WHERE ts > now64(3) - INTERVAL 1 DAY",
    ).catch(() => []),
    select<{ run_id: string; name: string }>(
      reader,
      "SELECT run_id, name FROM runs WHERE kind = 'manual' AND stopped_at IS NULL ORDER BY started_at DESC LIMIT 1",
    ).catch(() => []),
  ]);
  return {
    ok: clickhouse && config.openAiApiKey != null,
    model: config.model,
    clickhouse,
    latest_data_age_s: latest[0]?.age_s ?? null,
    run: run[0] ?? null,
  };
};

const HEALTH_TTL_MS = 5000;

let healthCache: {
  at: number;
  value: Promise<Awaited<ReturnType<typeof computeHealth>>>;
} | null = null;

const health = async () => {
  if (healthCache == null || Date.now() - healthCache.at > HEALTH_TTL_MS) {
    healthCache = { at: Date.now(), value: computeHealth() };
  }
  return await healthCache.value;
};

const streamChat = async (
  request: IncomingMessage,
  response: ServerResponse,
) => {
  let messages: UIMessage[];
  try {
    const body = JSON.parse(await readBody(request)) as { messages?: unknown };
    if (!Array.isArray(body.messages)) {
      throw new ForgeError('Body needs messages');
    }
    messages = body.messages as UIMessage[];
    if (
      messages.some(
        (message) => message.role !== 'user' && message.role !== 'assistant',
      )
    ) {
      throw new ForgeError('Only user and assistant messages are accepted');
    }
  } catch (error) {
    sendJson(request, response, 400, { error: errorMessage(error) });
    return;
  }
  const abort = new AbortController();
  response.once('close', () => {
    abort.abort();
  });
  const { result, tools } = await chat(messages, abort.signal);
  const web = createUIMessageStreamResponse({
    stream: toUIMessageStream({
      stream: result.stream,
      tools,
      onError: (error) => {
        log('Chat stream failed', { error: errorMessage(error) });
        return errorMessage(error);
      },
    }),
  });
  response.writeHead(web.status, {
    ...Object.fromEntries(web.headers),
    ...corsHeaders(request),
  });
  if (web.body == null) {
    response.end();
    return;
  }
  await pipeline(Readable.fromWeb(web.body), response).catch(
    (error: unknown) => {
      if (!abort.signal.aborted) {
        log('Chat stream failed', { error: errorMessage(error) });
      }
    },
  );
};

const rejection = (request: IncomingMessage, path: string) => {
  if (!ALLOWED_HOSTS.has(request.headers.host ?? '')) {
    return { status: 403, error: 'Host not allowed' };
  }
  const needsOrigin =
    (request.method === 'POST' && path === '/api/chat') ||
    (request.method === 'GET' && path === '/api/session');
  if (needsOrigin && !allowedOrigin(request)) {
    return { status: 403, error: 'Origin not allowed' };
  }
  if (request.method === 'POST' && path === '/api/chat') {
    if (
      !(request.headers['content-type'] ?? '').startsWith('application/json')
    ) {
      return { status: 415, error: 'Content type must be application/json' };
    }
    if (!tokenMatches(request)) {
      return { status: 401, error: 'Missing or wrong chat token' };
    }
  }
  return null;
};

const handle = async (request: IncomingMessage, response: ServerResponse) => {
  const path = new URL(request.url ?? '/', 'http://localhost').pathname;
  const rejected = rejection(request, path);
  if (rejected != null) {
    sendJson(request, response, rejected.status, { error: rejected.error });
    return;
  }
  if (request.method === 'OPTIONS') {
    response.writeHead(204, corsHeaders(request));
    response.end();
    return;
  }
  if (request.method === 'GET' && path === '/api/session') {
    sendJson(request, response, 200, {
      token: config.chatToken,
      header: TOKEN_HEADER,
    });
    return;
  }
  if (request.method === 'GET' && path === '/api/health') {
    sendJson(request, response, 200, await health());
    return;
  }
  if (request.method === 'POST' && path === '/api/chat') {
    await streamChat(request, response);
    return;
  }
  sendJson(request, response, 404, { error: 'Not found' });
};

export const serve = () => {
  const server = createServer((request, response) => {
    handle(request, response).catch((error: unknown) => {
      log('Request failed', { url: request.url, error: errorMessage(error) });
      if (response.headersSent) {
        response.end();
      } else {
        sendJson(request, response, 500, { error: errorMessage(error) });
      }
    });
  });
  startLiveStatus();
  server.listen(config.chatPort, config.chatListenHost, () => {
    log('Forge chat listening', {
      host: config.chatListenHost,
      port: config.chatPort,
    });
  });
};

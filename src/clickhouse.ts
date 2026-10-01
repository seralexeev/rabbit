import {
  type ClickHouseClient,
  ClickHouseError,
  ClickHouseLogLevel,
  createClient,
} from '@clickhouse/client';

import { config } from './config.ts';

export type Params = Record<string, unknown>;

export const writer: ClickHouseClient = createClient({
  url: config.clickhouseUrl,
  username: 'forge_writer',
  password: 'forge_writer',
  database: 'forge',
  log: { level: ClickHouseLogLevel.OFF },
});

export const reader: ClickHouseClient = createClient({
  url: config.clickhouseUrl,
  username: 'forge_reader',
  password: 'forge_reader',
  database: 'forge',
  compression: { response: false },
  log: { level: ClickHouseLogLevel.OFF },
});

const MAX_IN_FLIGHT = 6;
const BUSY_CODE = '202';
const BUSY_RETRIES = 4;

let inFlight = 0;
const waiting: Array<() => void> = [];

const acquire = async () => {
  if (inFlight < MAX_IN_FLIGHT) {
    inFlight += 1;
    return;
  }
  await new Promise<void>((resolve) => {
    waiting.push(resolve);
  });
};

const release = () => {
  const next = waiting.shift();
  if (next == null) {
    inFlight -= 1;
  } else {
    next();
  }
};

const isBusy = (error: unknown) =>
  error instanceof ClickHouseError && error.code === BUSY_CODE;

export const select = async <T>(
  client: ClickHouseClient,
  query: string,
  params: Params = {},
): Promise<T[]> => {
  await acquire();
  try {
    for (let attempt = 0; ; attempt++) {
      try {
        const result = await client.query({
          query,
          query_params: params,
          format: 'JSONEachRow',
        });
        return await result.json<T>();
      } catch (error) {
        if (!isBusy(error) || attempt >= BUSY_RETRIES) {
          throw error;
        }
        await new Promise((resolve) => setTimeout(resolve, 200 * 2 ** attempt));
      }
    }
  } finally {
    release();
  }
};

export const closeClickhouse = async () => {
  await Promise.all([writer.close(), reader.close()]);
};

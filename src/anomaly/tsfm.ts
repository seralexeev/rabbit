import { config } from '../config.ts';
import { ForgeError } from '../errors.ts';

const FORECAST_URL = 'https://api.tsfm.ai/v1/forecast';
const ATTEMPTS = 3;
const RETRYABLE = new Set([429, 500, 502, 503, 504]);

export type ForecastInput = {
  target: Array<Array<number | null>>;
  past_covariates?: Record<string, number[]>;
  future_covariates?: Record<string, number[]>;
};

type ForecastResponse = {
  model: string;
  outputs: Array<{
    quantile_predictions?: Array<{ level: number; values: number[][] }>;
  }>;
};

type Quantiles = { lo: number[][]; median: number[][]; hi: number[][] };

const wait = async (ms: number) => {
  await new Promise((resolve) => setTimeout(resolve, ms));
};

const apiKey = () => {
  if (config.tsfmApiKey == null) {
    throw new ForgeError('TSFM API key is not configured', {
      llm: 'Forecast-based anomaly detection is unavailable because TSFM_KEY is missing from the Forge .env file.',
      internal: { file: '.env', variable: 'TSFM_KEY' },
    });
  }
  return config.tsfmApiKey;
};

const DEADLINE_MS = 60_000;

const backoff = (attempt: number, retryAfterS: number | null) =>
  retryAfterS != null && retryAfterS > 0
    ? retryAfterS * 1000
    : 1000 * 2 ** attempt;

const post = async (body: unknown): Promise<ForecastResponse> => {
  const key = apiKey();
  const deadline = Date.now() + DEADLINE_MS;
  for (let attempt = 1; ; attempt++) {
    const remaining = deadline - Date.now();
    const response = await fetch(FORECAST_URL, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${key}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(Math.max(1, remaining)),
    }).catch(() => null);
    if (response?.ok === true) {
      return (await response.json()) as ForecastResponse;
    }
    const payload =
      response == null
        ? {}
        : ((await response.json().catch(() => ({}))) as {
            error?: string;
            code?: string;
          });
    const retryable = response == null || RETRYABLE.has(response.status);
    const retryAfter = Number(response?.headers.get('retry-after'));
    const waitMs = backoff(
      attempt,
      Number.isFinite(retryAfter) ? retryAfter : null,
    );
    if (!retryable || attempt >= ATTEMPTS || Date.now() + waitMs >= deadline) {
      throw new ForgeError('Forecast request failed', {
        internal: {
          status: response?.status ?? 'network',
          attempt,
          ...payload,
        },
      });
    }
    await wait(waitMs);
  }
};

const channels = (quantile: { values: number[][] }) => {
  const count = quantile.values[0]?.length ?? 0;
  return Array.from({ length: count }, (_, channel) =>
    quantile.values.map((step) => step[channel] ?? Number.NaN),
  );
};

export const BAND = [0.05, 0.95] as const;

export type Forecast = { band: [number, number]; windows: Quantiles[] };

export const forecastQuantiles = async (
  model: string,
  inputs: ForecastInput[],
  horizon: number,
): Promise<Forecast> => {
  const response = await post({
    model,
    inputs,
    parameters: {
      prediction_length: horizon,
      quantile_levels: [BAND[0], 0.5, BAND[1]],
    },
  });
  let band: [number, number] = [BAND[0], BAND[1]];
  const windows = response.outputs.map((output) => {
    const levels = (output.quantile_predictions ?? []).toSorted(
      (a, b) => a.level - b.level,
    );
    const lo = levels.at(0);
    const hi = levels.at(-1);
    const median = levels.find(
      (quantile) => Math.abs(quantile.level - 0.5) < 1e-6,
    );
    if (
      lo == null ||
      hi == null ||
      median == null ||
      lo.level >= 0.5 ||
      hi.level <= 0.5
    ) {
      throw new ForgeError('Forecast response is missing quantiles', {
        internal: { model },
      });
    }
    band = [lo.level, hi.level];
    return { lo: channels(lo), median: channels(median), hi: channels(hi) };
  });
  return { band, windows };
};

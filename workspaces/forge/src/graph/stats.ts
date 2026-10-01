export const median = (values: number[]) => {
  if (values.length === 0) {
    return Number.NaN;
  }
  const sorted = values.toSorted((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? (sorted[middle] ?? Number.NaN)
    : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
};

export const quantile = (values: number[], q: number) => {
  if (values.length === 0) {
    return 0;
  }
  const sorted = values.toSorted((a, b) => a - b);
  const position = (sorted.length - 1) * q;
  const low = Math.floor(position);
  const high = Math.ceil(position);
  return (
    (sorted[low] ?? 0) +
    ((sorted[high] ?? 0) - (sorted[low] ?? 0)) * (position - low)
  );
};

export const trailingMedian = (values: number[], window: number) => {
  const stride = Math.max(1, Math.floor(window / 20));
  const baseline: number[] = [];
  let current = values[0] ?? 0;
  for (let i = 0; i < values.length; i++) {
    if (i % stride === 0 && i > 0) {
      current = median(values.slice(Math.max(0, i - window), i));
    }
    baseline.push(i === 0 ? (values[0] ?? 0) : current);
  }
  return baseline;
};

export const robustZ = (
  values: number[],
  observed: boolean[],
  window: number,
  floor: number,
) => {
  const baseline = trailingMedian(values, window);
  const residuals = values.map((value, i) => value - (baseline[i] ?? value));
  const kept = residuals.filter((_, i) => observed[i] === true);
  const center = median(kept);
  const scale = Math.max(
    1.4826 * median(kept.map((residual) => Math.abs(residual - center))),
    floor,
    1e-9,
  );
  return {
    baseline,
    scale,
    z: residuals.map((residual, i) =>
      observed[i] === true ? residual / scale : 0,
    ),
  };
};

const pearson = (x: number[], y: number[]) => {
  const n = Math.min(x.length, y.length);
  if (n < 3) {
    return 0;
  }
  let sx = 0;
  let sy = 0;
  for (let i = 0; i < n; i++) {
    sx += x[i] ?? 0;
    sy += y[i] ?? 0;
  }
  const mx = sx / n;
  const my = sy / n;
  let cov = 0;
  let vx = 0;
  let vy = 0;
  for (let i = 0; i < n; i++) {
    const dx = (x[i] ?? 0) - mx;
    const dy = (y[i] ?? 0) - my;
    cov += dx * dy;
    vx += dx * dx;
    vy += dy * dy;
  }
  return vx === 0 || vy === 0 ? 0 : cov / Math.sqrt(vx * vy);
};

export const leadLag = (
  cause: number[],
  effect: number[],
  maxLag: number,
  sign: 1 | -1,
) => {
  let best = { r: 0, lag: 0 };
  for (let lag = -maxLag; lag <= maxLag; lag++) {
    const x = lag >= 0 ? cause.slice(0, cause.length - lag) : cause.slice(-lag);
    const y =
      lag >= 0 ? effect.slice(lag) : effect.slice(0, effect.length + lag);
    const r = pearson(x, y) * sign;
    if (
      r > best.r + 0.02 ||
      (Math.abs(r - best.r) <= 0.02 && Math.abs(lag) < Math.abs(best.lag))
    ) {
      best = { r, lag };
    }
  }
  return best;
};

export const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

export const strength = (z: number) => clamp01((Math.abs(z) - 2) / 6);

export const sparkline = (values: number[], points = 32) => {
  if (values.length <= points) {
    return values.map(round);
  }
  const step = values.length / points;
  return Array.from({ length: points }, (_, i) => {
    const chunk = values.slice(
      Math.floor(i * step),
      Math.floor((i + 1) * step),
    );
    const extreme = chunk.reduce(
      (best, value) =>
        Math.abs(value - (chunk[0] ?? 0)) > Math.abs(best - (chunk[0] ?? 0))
          ? value
          : best,
      chunk[0] ?? 0,
    );
    return round(extreme);
  });
};

export const round = (value: number) =>
  Number.isFinite(value) ? Number(value.toPrecision(4)) : 0;

const quantileEdges = (values: number[], bins: number) => [
  ...new Set(
    Array.from({ length: bins - 1 }, (_, k) =>
      quantile(values, (k + 1) / bins),
    ),
  ),
];

export const conditionalReference = (
  y: number[],
  observed: boolean[],
  covariates: number[][],
  floor: number,
  { bins = [8, 3], segments = 4, minCount = 30 } = {},
) => {
  const length = y.length;
  const usable = y.filter((_, i) => observed[i] === true);
  const edges = covariates.map((values, c) =>
    quantileEdges(
      values.filter((_, i) => observed[i] === true),
      bins[c] ?? 3,
    ),
  );
  const levels = (i: number) =>
    covariates.map(
      (values, c) =>
        (edges[c] ?? []).filter((edge) => (values[i] ?? 0) > edge).length,
    );
  const segmentOf = (i: number) =>
    Math.min(segments - 1, Math.floor((i * segments) / length));
  const keys = (i: number) => {
    const level = levels(i);
    const segment = segmentOf(i);
    return [
      ...level.flatMap((_, k) => {
        const prefix = level.slice(0, level.length - k).join(',');
        return [`${prefix}|${segment}`, prefix];
      }),
      `|${segment}`,
      '',
    ];
  };
  const cells = new Map<string, number[]>();
  for (let i = 0; i < length; i++) {
    if (observed[i] !== true) {
      continue;
    }
    for (const key of keys(i)) {
      const cell = cells.get(key) ?? [];
      cell.push(y[i] ?? 0);
      cells.set(key, cell);
    }
  }
  const stats = new Map(
    [...cells].map(([key, values]) => {
      const center = median(values);
      return [
        key,
        {
          count: values.length,
          center,
          scale: Math.max(
            1.4826 * median(values.map((value) => Math.abs(value - center))),
            floor,
            1e-9,
          ),
        },
      ];
    }),
  );
  const fallback = {
    count: usable.length,
    center: median(usable),
    scale: floor,
  };
  return (i: number) =>
    keys(i)
      .map((key) => stats.get(key))
      .find((cell) => cell != null && cell.count >= minCount) ?? fallback;
};

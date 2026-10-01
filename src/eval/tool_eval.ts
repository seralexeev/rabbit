import { readFileSync } from 'node:fs';
import { parse as parseYaml } from 'yaml';
import z from 'zod';

import { detectAnomalies, detectAnomaliesTool } from '../anomaly/detect.ts';
import { ROOT } from '../config.ts';
import { errorMessage } from '../errors.ts';
import { investigate } from '../graph/investigate.ts';
import { investigateTool } from '../graph/tools.ts';
import { epochMs } from '../output.ts';

const Window = z.tuple([z.string(), z.string()]);

const Case = z.discriminatedUnion('tool', [
  z.strictObject({
    id: z.string(),
    tool: z.literal('investigate'),
    input: z.record(z.string(), z.unknown()),
    top_chain_any: z.array(z.string()).default([]),
    chain_any: z.array(z.string()).default([]),
    ruled_out_any: z.array(z.string()).default([]),
    max_top_score: z.number().optional(),
    focus_within: Window.optional(),
  }),
  z.strictObject({
    id: z.string(),
    tool: z.literal('detect_anomalies'),
    input: z.record(z.string(), z.unknown()),
    truth: z.array(
      z.strictObject({ signal: z.string(), from: z.string(), to: z.string() }),
    ),
    joint_within: Window.optional(),
  }),
]);

type EvalCase = z.infer<typeof Case>;

const TOLERANCE_MS = 1000;

const ms = (value: string) => epochMs(value) ?? Number.NaN;

const overlaps = (
  a: { from: number; to: number },
  b: { from: number; to: number },
) => a.from <= b.to + TOLERANCE_MS && b.from <= a.to + TOLERANCE_MS;

const within = (time: string, window: [string, string]) =>
  ms(time) >= ms(window[0]) && ms(time) <= ms(window[1]);

const checkInvestigate = async (
  evalCase: Extract<EvalCase, { tool: 'investigate' }>,
) => {
  const result = await investigate(investigateTool.input.parse(evalCase.input));
  const [top] = result.hypotheses;
  const chains = result.hypotheses.flatMap((hypothesis) => hypothesis.chain);
  const ruledOut = result.ruled_out.map((item) => item.metric);
  const checks: Array<[string, boolean]> = [
    ...(evalCase.top_chain_any.length === 0
      ? []
      : [
          [
            `top chain has one of ${evalCase.top_chain_any.join(', ')}`,
            evalCase.top_chain_any.some(
              (id) => top?.chain.includes(id) === true,
            ),
          ] as [string, boolean],
        ]),
    ...(evalCase.chain_any.length === 0
      ? []
      : [
          [
            `some chain has one of ${evalCase.chain_any.join(', ')}`,
            evalCase.chain_any.some((id) => chains.includes(id)),
          ] as [string, boolean],
        ]),
    ...(evalCase.ruled_out_any.length === 0
      ? []
      : [
          [
            `rules out one of ${evalCase.ruled_out_any.join(', ')}`,
            evalCase.ruled_out_any.some((id) => ruledOut.includes(id)),
          ] as [string, boolean],
        ]),
    ...(evalCase.max_top_score == null
      ? []
      : [
          [
            `top score at most ${evalCase.max_top_score}`,
            (top?.score ?? 0) <= evalCase.max_top_score,
          ] as [string, boolean],
        ]),
    ...(evalCase.focus_within == null
      ? []
      : [
          [
            `focus peak within ${evalCase.focus_within.join(' - ')}`,
            within(result.focus.peak_at, evalCase.focus_within),
          ] as [string, boolean],
        ]),
  ];
  return {
    checks,
    detail: {
      top: top == null ? null : `${top.chain.join(' <- ')} (${top.score})`,
      ruled_out: ruledOut,
    },
  };
};

const checkDetect = async (
  evalCase: Extract<EvalCase, { tool: 'detect_anomalies' }>,
) => {
  const result = await detectAnomalies(
    detectAnomaliesTool.input.parse(evalCase.input),
  );
  const reported = result.per_signal.flatMap((signal) =>
    signal.events
      .filter((event) => event.severity !== 'info')
      .map((event) => ({
        signal: signal.signal,
        from: ms(event.start),
        to: ms(event.end),
      })),
  );
  const truth = evalCase.truth.map((item) => ({
    signal: item.signal,
    from: ms(item.from),
    to: ms(item.to),
  }));
  const found = truth.filter((item) =>
    reported.some(
      (event) => event.signal === item.signal && overlaps(event, item),
    ),
  );
  const correct = reported.filter((event) =>
    truth.some((item) => item.signal === event.signal && overlaps(event, item)),
  );
  const joint = evalCase.joint_within;
  const checks: Array<[string, boolean]> = [
    [`recall ${found.length}/${truth.length}`, found.length === truth.length],
    ...(joint == null
      ? []
      : [
          [
            `joint event within ${joint.join(' - ')}`,
            result.joint_events.some(
              (event) => within(event.start, joint) || within(event.end, joint),
            ),
          ] as [string, boolean],
        ]),
  ];
  return {
    checks,
    detail: {
      model: result.model.id,
      reported: reported.length,
      true_positive: correct.length,
      truth: truth.length,
      found: found.length,
      false_alarms: reported
        .filter((event) => !correct.includes(event))
        .map(
          (event) =>
            `${event.signal}@${new Date(event.from).toISOString().slice(11, 21)}`,
        ),
    },
  };
};

export const runToolEval = async (only?: string) => {
  const cases = z
    .array(Case)
    .parse(parseYaml(readFileSync(new URL('evals/tools.yml', ROOT), 'utf8')))
    .filter((evalCase) => only == null || evalCase.id === only);
  const results = [];
  for (const evalCase of cases) {
    const started = Date.now();
    try {
      const outcome =
        evalCase.tool === 'investigate'
          ? await checkInvestigate(evalCase)
          : await checkDetect(evalCase);
      results.push({
        id: evalCase.id,
        pass: outcome.checks.every(([, ok]) => ok),
        seconds: Math.round((Date.now() - started) / 100) / 10,
        failed: outcome.checks.filter(([, ok]) => !ok).map(([name]) => name),
        ...outcome.detail,
      });
    } catch (error) {
      results.push({
        id: evalCase.id,
        pass: false,
        error: errorMessage(error),
      });
    }
  }
  const detect = results.filter(
    (
      result,
    ): result is typeof result & {
      reported: number;
      true_positive: number;
      truth: number;
      found: number;
    } => 'reported' in result,
  );
  const sum = (pick: (result: (typeof detect)[number]) => number) =>
    detect.reduce((total, result) => total + pick(result), 0);
  return {
    cases: results.length,
    passed: results.filter((result) => result.pass).length,
    anomaly_precision:
      Math.round(
        (sum((r) => r.true_positive) /
          Math.max(
            1,
            sum((r) => r.reported),
          )) *
          100,
      ) / 100,
    anomaly_recall:
      Math.round(
        (sum((r) => r.found) /
          Math.max(
            1,
            sum((r) => r.truth),
          )) *
          100,
      ) / 100,
    results,
  };
};

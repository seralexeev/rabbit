import { type UIMessage, generateText } from 'ai';
import { readFileSync } from 'node:fs';
import { parse as parseYaml } from 'yaml';
import z from 'zod';

import { CHAT_TOOLS, chatSettings } from '../agent/chat.ts';
import { ROOT } from '../config.ts';
import { errorMessage } from '../errors.ts';
import type { ForgeTool } from '../forge_tool.ts';
import { ROBOT_TOOLS } from '../robot.ts';

const Case = z.strictObject({
  id: z.string(),
  question: z.string(),
  all: z.array(z.string()).default([]),
  any: z.array(z.string()).default([]),
  none: z.array(z.string()).default([]),
  approval: z.string().optional(),
  approval_steps: z
    .array(z.record(z.string(), z.union([z.string(), z.number()])))
    .optional(),
  facts: z.array(z.string()).default([]),
  obstacle_ahead_m: z.number().nullable().default(null),
});

type EvalCase = z.infer<typeof Case>;

const CONCURRENCY = 3;

const DRY_RUN = new Set(
  Object.keys(ROBOT_TOOLS).filter((name) => name !== 'robot_status'),
);

const robotStatusFixture = (obstacleAhead: number | null) => ({
  kind: 'status',
  pose: {
    x: 0,
    y: 0.13,
    z: 0,
    yaw_deg: 0,
    heading_deg: 0,
    speed_mps: 0,
    confidence: 90,
    age_s: 0.3,
  },
  nav: {
    mode: 'idle',
    goal_x: null,
    goal_z: null,
    step_type: '',
    step_index: 0,
    steps_total: 0,
    age_s: 0.3,
  },
  battery: { voltage: 15.2, current_a: 1.5, charge_pct: 45, age_s: 0.3 },
  obstacle: {
    nearest_distance: obstacleAhead ?? 2.5,
    nearest_bearing_deg: 0,
    ahead_distance: obstacleAhead,
    ahead_bearing_deg: obstacleAhead == null ? null : 0,
    age_s: 0.3,
  },
  camera: {
    current_fps: 30,
    pose_state: 'OK',
    tracking_state: 'VISUAL_INERTIAL',
    age_s: 0.3,
  },
});

const evalTools = (evalCase: EvalCase): Record<string, ForgeTool> =>
  Object.fromEntries(
    Object.entries(CHAT_TOOLS).map(([name, tool]) => {
      if (name === 'robot_status') {
        return [
          name,
          {
            ...tool,
            run: async () =>
              await Promise.resolve(
                robotStatusFixture(evalCase.obstacle_ahead_m),
              ),
          },
        ];
      }
      return [
        name,
        DRY_RUN.has(name)
          ? {
              ...tool,
              run: async (input: unknown) =>
                await Promise.resolve({ ok: true, dry_run: true, input }),
            }
          : tool,
      ];
    }),
  );

const callTokens = (name: string, input: unknown) => {
  const fields = (input ?? {}) as {
    slab?: string;
    signals?: string[];
    symptom?: string;
    node?: string;
    source?: { slab?: string };
  };
  const details = [
    fields.slab,
    fields.source?.slab,
    fields.symptom,
    fields.node,
    ...(fields.signals ?? []),
  ].filter((detail) => detail != null);
  return [name, ...details.map((detail) => `${name}:${detail}`)];
};

const TOLERANCE: Record<string, number> = { degrees: 5 };

const stepsMatch = (
  input: unknown,
  expected: Array<Record<string, string | number>>,
) => {
  const steps =
    (input as { steps?: Array<Record<string, unknown>> }).steps ?? [];
  return (
    steps.length === expected.length &&
    expected.every((step, i) =>
      Object.entries(step).every(([key, value]) => {
        const actual = steps[i]?.[key] ?? 0;
        return typeof value === 'number'
          ? Math.abs(Number(actual) - value) <= (TOLERANCE[key] ?? 0.05)
          : actual === value;
      }),
    )
  );
};

const runCase = async (evalCase: EvalCase) => {
  const messages: UIMessage[] = [
    {
      id: 'u1',
      role: 'user',
      parts: [{ type: 'text', text: evalCase.question }],
    },
  ];
  const started = Date.now();
  const result = await generateText(
    await chatSettings(messages, evalTools(evalCase)),
  );
  const calls: string[] = [];
  const approvals: Array<{ tool: string; input: unknown }> = [];
  for (const part of result.steps.flatMap((step) => step.content)) {
    if (part.type === 'tool-call') {
      calls.push(...callTokens(part.toolName, part.input));
    }
    if (part.type === 'tool-approval-request') {
      approvals.push({
        tool: part.toolCall.toolName,
        input: part.toolCall.input,
      });
    }
  }
  const text = result.text;
  const checks: Array<[string, boolean]> = [
    ...evalCase.all.map((token): [string, boolean] => [
      `calls ${token}`,
      calls.includes(token),
    ]),
    ...(evalCase.any.length > 0
      ? [
          [
            `calls any of ${evalCase.any.join(', ')}`,
            evalCase.any.some((token) => calls.includes(token)),
          ] as [string, boolean],
        ]
      : []),
    ...evalCase.none.map((token): [string, boolean] => [
      `never calls ${token}`,
      !calls.includes(token),
    ]),
    ...(evalCase.approval == null
      ? []
      : [
          [
            `asks approval for ${evalCase.approval}`,
            approvals.some((approval) => approval.tool === evalCase.approval),
          ] as [string, boolean],
        ]),
    ...(evalCase.approval_steps == null
      ? []
      : [
          [
            `approval steps match ${JSON.stringify(evalCase.approval_steps)}`,
            approvals.some((approval) =>
              stepsMatch(approval.input, evalCase.approval_steps ?? []),
            ),
          ] as [string, boolean],
        ]),
    ...evalCase.facts.map((fact): [string, boolean] => [
      `says /${fact}/`,
      new RegExp(fact, 'i').test(text),
    ]),
  ];
  return { id: evalCase.id, ms: Date.now() - started, calls, checks, text };
};

export const runChatEval = async (only?: string) => {
  const cases = z
    .array(Case)
    .parse(parseYaml(readFileSync(new URL('evals/chat.yml', ROOT), 'utf8')))
    .filter((evalCase) => only == null || evalCase.id === only);
  const results: Array<
    Awaited<ReturnType<typeof runCase>> | { id: string; error: string }
  > = [];
  for (let i = 0; i < cases.length; i += CONCURRENCY) {
    results.push(
      ...(await Promise.all(
        cases.slice(i, i + CONCURRENCY).map(async (evalCase) => {
          try {
            return await runCase(evalCase);
          } catch (error) {
            return { id: evalCase.id, error: errorMessage(error) };
          }
        }),
      )),
    );
  }
  const passed = results.filter(
    (result) => 'checks' in result && result.checks.every(([, ok]) => ok),
  );
  const checks = results.flatMap((result) =>
    'checks' in result ? result.checks : [],
  );
  return {
    cases: results.length,
    passed: passed.length,
    case_pass_rate:
      Math.round((passed.length / Math.max(results.length, 1)) * 100) / 100,
    check_pass_rate:
      Math.round(
        (checks.filter(([, ok]) => ok).length / Math.max(checks.length, 1)) *
          100,
      ) / 100,
    results: results.map((result) =>
      'checks' in result
        ? {
            id: result.id,
            pass: result.checks.every(([, ok]) => ok),
            seconds: Math.round(result.ms / 100) / 10,
            failed: result.checks.filter(([, ok]) => !ok).map(([name]) => name),
            calls: [...new Set(result.calls)],
            answer: result.text.slice(0, 600),
          }
        : result,
    ),
  };
};

import type z from 'zod';

import { withLocalTimes } from './local_time.ts';

export type ForgeTool<I extends z.ZodObject = z.ZodObject> = {
  title: string;
  description: string;
  input: I;
  run: (input: z.infer<I>) => Promise<unknown>;
  forModel?: (output: never) => unknown;
  requiresApproval?: true;
};

export const forgeTool = <I extends z.ZodObject, O>(
  tool: Omit<ForgeTool<I>, 'run' | 'forModel'> & {
    run: (input: z.infer<I>) => Promise<O>;
    forModel?: (output: O) => unknown;
  },
): ForgeTool<I> => tool;

export const modelView = (tool: ForgeTool, output: unknown) =>
  withLocalTimes(
    tool.forModel == null
      ? output
      : (tool.forModel as (value: unknown) => unknown)(output),
  );

export const approvalConfig = (tools: Record<string, ForgeTool>) =>
  Object.fromEntries(
    Object.entries(tools)
      .filter(([, tool]) => tool.requiresApproval === true)
      .map(([name]) => [name, 'user-approval' as const]),
  );

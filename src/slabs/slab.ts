import { readFileSync, readdirSync } from 'node:fs';
import { parse as parseYaml } from 'yaml';
import z from 'zod';

import { ROOT } from '../config.ts';
import { ForgeError } from '../errors.ts';

const AXIS_KINDS = ['time', 'ordinal', 'category', 'entity'] as const;

const Column = z
  .strictObject({
    kind: z.enum([...AXIS_KINDS, 'attribute']).optional(),
    measure: z.enum(['gauge', 'counter', 'event', 'ratio']).optional(),
    unit: z.string().optional(),
    description: z.string().optional(),
  })
  .refine((column) => (column.kind == null) !== (column.measure == null), {
    message: 'A column is either a dimension (kind) or a metric (measure)',
  });

const SubType = z.enum(['String', 'UInt32', 'Float64']);

const Sub = z.strictObject({
  type: SubType,
  description: z.string(),
  default: z.union([z.string(), z.number()]).optional(),
  enum: z.array(z.string()).optional(),
});

const SlabFile = z.strictObject({
  title: z.string(),
  description: z.string(),
  tags: z.array(z.string()).min(1),
  prompts: z.array(z.string()).default([]),
  guidelines: z.string().optional(),
  dims: z.array(z.string()),
  sql: z.string(),
  columns: z.record(z.string(), Column),
  subs: z.record(z.string(), Sub).default({}),
});

export type SlabSub = z.infer<typeof Sub>;
export type Slab = z.infer<typeof SlabFile> & { id: string };

const WELL_KNOWN_SUBS: Record<string, SlabSub> = {
  run_id: {
    type: 'String',
    default: 'latest',
    description:
      "Run id from list_runs, 'latest' for the most recent named run, or 'previous' for the one before it",
  },
  other_run_id: {
    type: 'String',
    default: 'previous',
    description: "Second run to compare with: a run id, 'latest' or 'previous'",
  },
  from: {
    type: 'String',
    default: '1970-01-01 00:00:00',
    description:
      'Start of the time range, UTC robot clock, e.g. 2026-10-01 11:00:00; the default covers the whole run',
  },
  to: {
    type: 'String',
    default: '2100-01-01 00:00:00',
    description:
      'End of the time range, UTC robot clock; the default covers the whole run',
  },
};

const PLACEHOLDER = /\{(\w+):([^}]+)\}/g;

const placeholders = (sql: string) =>
  new Map(
    [...sql.matchAll(PLACEHOLDER)].map(([, name, type]) => [
      name ?? '',
      type ?? '',
    ]),
  );

const slabErrors = (slab: Slab): string[] => {
  const errors: string[] = [];
  const used = placeholders(slab.sql);
  for (const [name, type] of used) {
    const sub = slab.subs[name];
    if (sub == null) {
      errors.push(`placeholder {${name}:${type}} is not declared in subs`);
    } else if (sub.type !== type) {
      errors.push(
        `placeholder {${name}:${type}} does not match sub type ${sub.type}`,
      );
    }
  }
  for (const [name, sub] of Object.entries(slab.subs)) {
    if (!used.has(name)) {
      errors.push(`sub ${name} is not used in sql`);
    }
    if (
      sub.enum != null &&
      sub.default != null &&
      !sub.enum.includes(String(sub.default))
    ) {
      errors.push(`sub ${name} default is not one of its enum values`);
    }
  }
  const axes = Object.entries(slab.columns)
    .filter(([, column]) => AXIS_KINDS.some((kind) => kind === column.kind))
    .map(([name]) => name);
  if (axes.toSorted().join() !== slab.dims.toSorted().join()) {
    errors.push(
      `dims [${slab.dims.join(', ')}] must list exactly the axis columns [${axes.join(', ')}]`,
    );
  }
  return errors;
};

const SLAB_DIR = new URL('slabs/', ROOT);

const loadSlab = (file: string): Slab => {
  const id = file.replace(/\.yml$/, '');
  const parsed = SlabFile.safeParse(
    parseYaml(readFileSync(new URL(file, SLAB_DIR), 'utf8')),
  );
  if (!parsed.success) {
    throw new ForgeError('Invalid slab file', {
      internal: { id, error: z.prettifyError(parsed.error) },
    });
  }
  const declared = Object.keys(parsed.data.subs).filter(
    (name) => name in WELL_KNOWN_SUBS,
  );
  if (declared.length > 0) {
    throw new ForgeError('Slab declares a well-known sub', {
      internal: { id, subs: declared },
    });
  }
  const wellKnown = Object.fromEntries(
    Object.entries(WELL_KNOWN_SUBS).filter(([name]) =>
      placeholders(parsed.data.sql).has(name),
    ),
  );
  const slab = {
    ...parsed.data,
    id,
    subs: { ...wellKnown, ...parsed.data.subs },
  };
  const errors = slabErrors(slab);
  if (errors.length > 0) {
    throw new ForgeError('Invalid slab', { internal: { id, errors } });
  }
  return slab;
};

let cache: Slab[] | null = null;

export const loadSlabs = (): Slab[] => {
  cache ??= readdirSync(SLAB_DIR)
    .filter((file) => file.endsWith('.yml'))
    .toSorted()
    .map(loadSlab);
  return cache;
};

export const getSlab = (id: string): Slab => {
  const slab = loadSlabs().find((candidate) => candidate.id === id);
  if (slab == null) {
    throw new ForgeError('Unknown slab', {
      llm: `There is no slab '${id}'. Use search_slabs to find one, or ask for a generated query.`,
      internal: { id },
    });
  }
  return slab;
};

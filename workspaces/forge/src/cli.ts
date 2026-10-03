import { parseArgs } from 'node:util';

import { ask } from './agent/ask.ts';
import { writeQuery } from './agent/sql_agent.ts';
import { detectAnomaliesTool } from './anomaly/detect.ts';
import { ForgeError, errorMessage } from './errors.ts';
import { runChatEval } from './eval/chat_eval.ts';
import { runToolEval } from './eval/tool_eval.ts';
import { checkGraph } from './graph/check.ts';
import { investigateTool, metricGraphTool } from './graph/tools.ts';
import { serveMcp } from './mcp/server.ts';
import { resolveRunParams } from './runs.ts';
import { listRuns, startRun, stopRun } from './runs.ts';
import { describeSchema } from './schema.ts';
import { serve } from './server.ts';
import { checkSlab, runSlab } from './slabs/run_slab.ts';
import { searchSlabs, slabSummary } from './slabs/search_slabs.ts';
import { loadSlabs } from './slabs/slab.ts';
import { runSql } from './sql/query_gate.ts';
import { bench } from './store/bench.ts';
import { applyRetention, compact } from './store/compact.ts';
import { closeStore } from './store/engine.ts';
import { importTables } from './store/import.ts';
import { parity } from './store/parity.ts';
import { syncMirror } from './store/sync.ts';
import { runWriter } from './writer.ts';

const USAGE = `Usage: pnpm forge <command>

  writer                           record NATS into Parquet files until Ctrl-C
  serve [--writer]                 serve the chat API on http://127.0.0.1:18080; --writer also records
  sync [<host:dir>]                mirror the robot's Parquet files into FORGE_DATA_DIR
  compact                          merge small Parquet files and apply retention once
  import <dir> [--before <time>]   import <table>.parquet exports (rows before <time> UTC replace the store's)
  bench [<run id>]                 time the heaviest tool queries and report memory
  parity [<clickhouse url>] --before <time> [--limit <runs>]   compare tool queries on the store and ClickHouse
  run start --name <name> [--note <text>]
  run stop
  run list [--limit <n>]
  slab list
  slab search <text>
  slab run <slab> [--param name=value ...] [--limit <n>]
  slab check                       validate every slab against the store and run it
  query <sql> [--param name=value ...] [--limit <n>]
  detect <signal>[,<signal>...] [--param run_id=<id>] [--param from=..] [--param to=..] [--param covariates=auto|a,b] [--param threshold=<n>]
  graph [<metric>] [--param to=<metric>] [--param hops=<n>]
  graph check                      validate graph/metrics.yml and run every metric against the store
  investigate <metric> [--param at=HH:MM] [--param from=..] [--param to=..] [--param run_id=..]
  schema
  ask <question>                   answer with the agent (fast path slabs, heavy path generated SQL)
  write-query <request>            run only the SQL sub-agent
  mcp                              serve the MCP server over stdio
  eval tools [<case id>]           run investigate and detect_anomalies against ground truth in evals/tools.yml
  eval [<case id>]                 run the chat agent eval in evals/chat.yml (robot actions are dry runs)
`;

const print = (value: unknown) => {
  process.stdout.write(
    `${typeof value === 'string' ? value : JSON.stringify(value, null, 2)}\n`,
  );
};

const { positionals, values } = parseArgs({
  allowPositionals: true,
  options: {
    name: { type: 'string' },
    note: { type: 'string' },
    limit: { type: 'string' },
    param: { type: 'string', multiple: true },
    writer: { type: 'boolean' },
    before: { type: 'string' },
  },
});

const [command, sub, ...rest] = positionals;

const params = Object.fromEntries(
  (values.param ?? []).map((pair) => {
    const separator = pair.indexOf('=');
    if (separator < 0) {
      throw new ForgeError('Parameters are name=value', { internal: { pair } });
    }
    return [pair.slice(0, separator), pair.slice(separator + 1)];
  }),
);

const limit = values.limit == null ? undefined : Number(values.limit);

const text = (parts: Array<string | undefined>) => {
  const joined = parts.filter((part) => part != null).join(' ');
  return joined.length === 0 ? undefined : joined;
};

const required = (value: string | undefined, flag: string) => {
  if (value == null) {
    throw new ForgeError('Missing required flag', {
      internal: { flag: `--${flag}` },
    });
  }
  return value;
};

const commands: Record<string, (() => Promise<void> | void) | undefined> = {
  sync: async () => {
    print(await syncMirror(sub));
  },
  compact: async () => {
    print({ merged: await compact(), ...(await applyRetention()) });
  },
  bench: async () => {
    print(await bench(sub));
  },
  parity: async () => {
    print(
      await parity(
        sub ?? 'http://192.168.1.53:18123',
        required(values.before, 'before'),
        limit,
      ),
    );
  },
  import: async () => {
    print(await importTables(required(sub, 'dir'), values.before));
  },
  writer: async () => {
    await runWriter();
  },
  'run start': async () => {
    print(await startRun(required(values.name, 'name'), values.note));
  },
  'run stop': async () => {
    print(await stopRun());
  },
  'run list': async () => {
    print(await listRuns(limit));
  },
  'slab list': async () => {
    print(loadSlabs().map(slabSummary));
  },
  'slab search': async () => {
    print(searchSlabs(required(text(rest), 'text')));
  },
  'slab run': async () => {
    print(await runSlab(required(rest[0], 'slab'), params, limit));
  },
  'slab check': async () => {
    for (const slab of loadSlabs()) {
      print(await checkSlab(slab));
    }
  },
  query: async () => {
    print(
      await runSql(required(sub, 'sql'), await resolveRunParams(params), limit),
    );
  },
  detect: async () => {
    const { threshold, covariates, ...rest } = params;
    print(
      await detectAnomaliesTool.run(
        detectAnomaliesTool.input.parse({
          signals: required(sub, 'signals').split(','),
          ...rest,
          ...(covariates == null
            ? {}
            : {
                covariates:
                  covariates === 'auto'
                    ? 'auto'
                    : covariates.split(',').filter((id) => id !== ''),
              }),
          ...(threshold == null ? {} : { threshold: Number(threshold) }),
        }),
      ),
    );
  },
  graph: async () => {
    const { hops, ...rest } = params;
    print(
      await metricGraphTool.run(
        metricGraphTool.input.parse({
          ...(sub == null ? {} : { node: sub }),
          ...rest,
          ...(hops == null ? {} : { hops: Number(hops) }),
        }),
      ),
    );
  },
  'graph check': async () => {
    print(await checkGraph());
  },
  investigate: async () => {
    const { depth, ...rest } = params;
    print(
      await investigateTool.run(
        investigateTool.input.parse({
          symptom: required(sub, 'metric'),
          ...rest,
          ...(depth == null ? {} : { depth: Number(depth) }),
        }),
      ),
    );
  },
  schema: async () => {
    print(await describeSchema());
  },
  ask: async () => {
    print(await ask(required(text([sub, ...rest]), 'question')));
  },
  'write-query': async () => {
    print(await writeQuery(required(text([sub, ...rest]), 'request')));
  },
  mcp: () => {
    serveMcp();
  },
  serve: async () => {
    serve();
    if (values.writer === true) {
      await runWriter();
    }
  },
  'eval tools': async () => {
    print(await runToolEval(rest[0]));
  },
  eval: async () => {
    print(await runChatEval(sub));
  },
};

const handler =
  commands[[command, sub].filter((part) => part != null).join(' ')] ??
  commands[command ?? ''];

if (handler == null) {
  process.stderr.write(USAGE);
  process.exit(1);
}

const longRunning =
  command === 'writer' || command === 'mcp' || command === 'serve';

try {
  await handler();
} catch (error) {
  const details =
    error instanceof ForgeError
      ? [
          error.llm,
          error.internal == null ? null : JSON.stringify(error.internal),
        ]
      : [];
  process.stderr.write(
    `${[errorMessage(error), ...details].filter((part) => part != null).join('\n')}\n`,
  );
  process.exitCode = 1;
} finally {
  if (!longRunning) {
    await closeStore();
  }
}

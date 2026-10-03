import { Dialect, parse } from '@polyglot-sql/sdk';

type Node = Record<string, unknown>;

type Identifier = { name: string };

type TableNode = {
  name: Identifier;
  schema: Identifier | null;
  alias: Identifier | null;
  final_: boolean;
};

type ColumnNode = { name: Identifier; table: Identifier | null };

type JoinNode = {
  this: unknown;
  on: unknown;
  using: Identifier[];
  kind: string;
};

type SelectNode = {
  from: { expressions: unknown[] } | null;
  joins: JoinNode[];
  group_by: { expressions: unknown[] } | null;
  settings?: unknown[] | null;
  format?: unknown;
  with: { ctes: Array<{ alias: Identifier; this: unknown }> } | null;
};

const RUN_KEY = 'run_id';

const PER_RUN_TABLES = new Set(['runs']);

const SYSTEM_QUALIFIERS = new Set(['system', 'information_schema']);

const COMBINATOR =
  /(If|Array|OrNull|OrDefault|Distinct|State|Merge|ForEach|Resample)$/;

const ALLOWED_FUNCTIONS = new Set(
  [
    'count',
    'sum',
    'avg',
    'min',
    'max',
    'any',
    'anyLast',
    'argMin',
    'argMax',
    'uniq',
    'uniqExact',
    'quantile',
    'quantiles',
    'quantileExact',
    'quantileTDigest',
    'quantileTiming',
    'median',
    'stddevPop',
    'stddevSamp',
    'varPop',
    'varSamp',
    'corr',
    'covarPop',
    'covarSamp',
    'simpleLinearRegression',
    'groupArray',
    'groupUniqArray',
    'topK',
    'histogram',
    'deltaSum',
    'row_number',
    'rank',
    'dense_rank',
    'percent_rank',
    'cume_dist',
    'ntile',
    'lagInFrame',
    'leadInFrame',
    'first_value',
    'last_value',
    'nth_value',
    'lag',
    'lead',
    'abs',
    'sqrt',
    'cbrt',
    'pow',
    'power',
    'exp',
    'log',
    'ln',
    'log2',
    'log10',
    'sin',
    'cos',
    'tan',
    'asin',
    'acos',
    'atan',
    'atan2',
    'hypot',
    'radians',
    'degrees',
    'round',
    'roundBankers',
    'floor',
    'ceil',
    'ceiling',
    'trunc',
    'truncate',
    'greatest',
    'least',
    'sign',
    'intDiv',
    'intDivOrZero',
    'modulo',
    'moduloOrZero',
    'plus',
    'minus',
    'multiply',
    'divide',
    'negate',
    'pi',
    'e',
    'isNaN',
    'isFinite',
    'isInfinite',
    'bitAnd',
    'bitOr',
    'bitXor',
    'bitTest',
    'bitShiftLeft',
    'bitShiftRight',
    'equals',
    'notEquals',
    'less',
    'greater',
    'lessOrEquals',
    'greaterOrEquals',
    'and',
    'or',
    'not',
    'xor',
    'in',
    'notIn',
    'like',
    'notLike',
    'ilike',
    'notILike',
    'match',
    'isNull',
    'isNotNull',
    'if',
    'multiIf',
    'coalesce',
    'ifNull',
    'nullIf',
    'assumeNotNull',
    'toNullable',
    'toFloat32',
    'toFloat64',
    'toInt8',
    'toInt16',
    'toInt32',
    'toInt64',
    'toUInt8',
    'toUInt16',
    'toUInt32',
    'toUInt64',
    'toString',
    'toDecimal32',
    'toDecimal64',
    'toBool',
    'toTypeName',
    'cast',
    'accurateCastOrNull',
    'toDate',
    'toDateTime',
    'toDateTime64',
    'parseDateTimeBestEffort',
    'parseDateTime64BestEffort',
    'parseDateTime64BestEffortOrNull',
    'parseDateTimeBestEffortOrNull',
    'toStartOfInterval',
    'toStartOfSecond',
    'toStartOfMinute',
    'toStartOfFiveMinutes',
    'toStartOfTenMinutes',
    'toStartOfFifteenMinutes',
    'toStartOfHour',
    'toStartOfDay',
    'toIntervalMillisecond',
    'toIntervalSecond',
    'toIntervalMinute',
    'toIntervalHour',
    'toIntervalDay',
    'dateDiff',
    'date_diff',
    'dateAdd',
    'dateSub',
    'addSeconds',
    'addMinutes',
    'addHours',
    'addMilliseconds',
    'subtractSeconds',
    'subtractMinutes',
    'subtractHours',
    'subtractMilliseconds',
    'now',
    'now64',
    'today',
    'toUnixTimestamp',
    'toUnixTimestamp64Milli',
    'toUnixTimestamp64Micro',
    'toUnixTimestamp64Nano',
    'fromUnixTimestamp',
    'fromUnixTimestamp64Milli',
    'fromUnixTimestamp64Nano',
    'toHour',
    'toMinute',
    'toSecond',
    'toYYYYMMDD',
    'formatDateTime',
    'toTimezone',
    'age',
    'timeDiff',
    'concat',
    'lower',
    'upper',
    'length',
    'lengthUTF8',
    'substring',
    'substr',
    'position',
    'positionCaseInsensitive',
    'hasToken',
    'hasAllTokens',
    'hasAnyTokens',
    'multiSearchAnyCaseInsensitive',
    'replaceAll',
    'replaceOne',
    'replaceRegexpAll',
    'replaceRegexpOne',
    'splitByChar',
    'splitByString',
    'startsWith',
    'endsWith',
    'trim',
    'trimBoth',
    'trimLeft',
    'trimRight',
    'empty',
    'notEmpty',
    'format',
    'leftPad',
    'rightPad',
    'extract',
    'JSONExtractFloat',
    'JSONExtractInt',
    'JSONExtractString',
    'JSONExtractBool',
    'JSONExtractRaw',
    'JSONExtractArrayRaw',
    'JSONHas',
    'JSONLength',
    'visitParamExtractFloat',
    'visitParamExtractString',
    'array',
    'arrayJoin',
    'arrayMap',
    'arrayFilter',
    'arraySum',
    'arrayAvg',
    'arrayMin',
    'arrayMax',
    'arrayEnumerate',
    'arrayElement',
    'mapKeys',
    'mapValues',
    'mapContains',
    'has',
    'hasAny',
    'hasAll',
    'indexOf',
    'range',
    'arraySort',
    'arrayReverse',
    'arrayDistinct',
    'arrayCount',
    'arrayExists',
    'arrayAll',
    'arraySlice',
    'arrayConcat',
    'arrayZip',
    'arrayCumSum',
    'arrayDifference',
    'arrayStringConcat',
    'tuple',
    'tupleElement',
    'untuple',
    'rowNumberInAllBlocks',
  ].map((name) => name.toLowerCase()),
);

const node = (value: unknown, key: string): Node | null => {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  const keys = Object.keys(value);
  const data = (value as Node)[key];
  return keys.length === 1 &&
    keys[0] === key &&
    data != null &&
    typeof data === 'object'
    ? (data as Node)
    : null;
};

const walk = (value: unknown, visit: (child: unknown) => void) => {
  if (Array.isArray(value)) {
    for (const child of value) {
      walk(child, visit);
    }
    return;
  }
  if (value == null || typeof value !== 'object') {
    return;
  }
  visit(value);
  for (const child of Object.values(value)) {
    walk(child, visit);
  }
};

const collect = <T>(value: unknown, key: string): T[] => {
  const found: T[] = [];
  walk(value, (child) => {
    const data = node(child, key);
    if (data != null) {
      found.push(data as T);
    }
  });
  return found;
};

const unwrap = (source: unknown): unknown => {
  const alias = node(source, 'alias');
  if (alias != null) {
    return unwrap(alias.this);
  }
  const paren = node(source, 'paren');
  return paren == null ? source : unwrap(paren.this);
};

const functionAllowed = (name: string) => {
  let base = name;
  while (!ALLOWED_FUNCTIONS.has(base.toLowerCase()) && COMBINATOR.test(base)) {
    base = base.replace(COMBINATOR, '');
  }
  return ALLOWED_FUNCTIONS.has(base.toLowerCase());
};

const tableList = (tables: ReadonlySet<string>) =>
  [...tables].toSorted().join(', ');

const LITERAL = /'(?:[^'\\]|\\.)*'/g;

const sourceAlias = (source: unknown): string | null => {
  const alias = node(source, 'alias');
  if (alias != null) {
    return (alias.alias as Identifier).name;
  }
  const subquery = node(source, 'subquery');
  if (subquery != null) {
    return (subquery.alias as Identifier | null)?.name ?? null;
  }
  const table = node(source, 'table') as TableNode | null;
  return table == null ? null : (table.alias?.name ?? table.name.name);
};

const groupsByRunOnly = (select: SelectNode | null) => {
  const keys = select?.group_by?.expressions ?? [];
  return (
    keys.length === 1 &&
    (node(keys[0], 'column') as ColumnNode | null)?.name.name === RUN_KEY
  );
};

type Scope = { ctes: Map<string, SelectNode> };

const isPerRun = (source: unknown, scope: Scope) => {
  const inner = unwrap(source);
  const table = node(inner, 'table') as TableNode | null;
  if (table != null) {
    const cte = scope.ctes.get(table.name.name);
    return cte == null
      ? PER_RUN_TABLES.has(table.name.name)
      : groupsByRunOnly(cte);
  }
  const subquery = node(inner, 'subquery');
  return (
    subquery != null &&
    groupsByRunOnly(node(subquery.this, 'select') as SelectNode | null)
  );
};

const conjuncts = (condition: unknown): unknown[] => {
  const inner = unwrap(condition);
  const and = node(inner, 'and');
  return and == null
    ? [inner]
    : [...conjuncts(and.left), ...conjuncts(and.right)];
};

const COMPARISONS = ['eq', 'gt', 'gte', 'lt', 'lte'];

const comparedColumns = (conjunct: unknown) => {
  for (const op of COMPARISONS) {
    const comparison = node(conjunct, op);
    if (comparison != null) {
      const left = node(unwrap(comparison.left), 'column') as ColumnNode | null;
      const right = node(
        unwrap(comparison.right),
        'column',
      ) as ColumnNode | null;
      return left == null || right == null ? null : { op, left, right };
    }
  }
  return null;
};

const joinError = (
  join: JoinNode,
  leftSources: unknown[],
  scope: Scope,
): string | null => {
  const leftAliases = new Set(
    leftSources.map(sourceAlias).filter((alias) => alias != null),
  );
  const rightAlias = sourceAlias(join.this);
  const perRun =
    isPerRun(join.this, scope) ||
    leftSources.every((source) => isPerRun(source, scope));
  if (join.using.length > 0) {
    if (!join.using.some((column) => column.name === RUN_KEY)) {
      return `Every JOIN must match ${RUN_KEY}; add it to USING.`;
    }
    return join.using.length > 1 || perRun
      ? null
      : `A JOIN on ${RUN_KEY} alone pairs every row of a run with every other; add a time or sequence key (USING (${RUN_KEY}, t)), use ASOF JOIN on ts, or aggregate one side to one row per run.`;
  }
  const parts = conjuncts(join.on);
  if (parts.some((part) => node(part, 'or') != null)) {
    return 'OR is not allowed in a JOIN condition; join on equalities combined with AND and filter in WHERE.';
  }
  const crossSides = (left: ColumnNode, right: ColumnNode) => {
    const a = left.table?.name;
    const b = right.table?.name;
    return (
      a != null &&
      b != null &&
      ((leftAliases.has(a) && b === rightAlias) ||
        (leftAliases.has(b) && a === rightAlias))
    );
  };
  const columns = parts.map(comparedColumns).filter((pair) => pair != null);
  const runKey = columns.some(
    (pair) =>
      pair.op === 'eq' &&
      pair.left.name.name === RUN_KEY &&
      pair.right.name.name === RUN_KEY &&
      crossSides(pair.left, pair.right),
  );
  if (!runKey) {
    return `Every JOIN must match ${RUN_KEY} between the two sides with qualified columns (ON a.${RUN_KEY} = b.${RUN_KEY} AND ...); joining on time alone pairs rows from different runs. Project ${RUN_KEY} in CTEs and subqueries you join.`;
  }
  const timeKey = columns.some(
    (pair) =>
      pair.left.name.name !== RUN_KEY &&
      pair.right.name.name !== RUN_KEY &&
      crossSides(pair.left, pair.right),
  );
  return timeKey || perRun
    ? null
    : `A JOIN on ${RUN_KEY} alone pairs every row of a run with every other; add a time or sequence key from both sides (AND a.t = b.t), use ASOF JOIN ... AND a.ts >= b.ts, or aggregate one side to one row per run with GROUP BY ${RUN_KEY}.`;
};

const sourceError = (
  source: unknown,
  scope: Scope,
  tables: ReadonlySet<string>,
): string | null => {
  const table = node(source, 'table') as TableNode | null;
  if (table != null) {
    const name = table.name.name;
    if (table.schema == null && scope.ctes.has(name)) {
      return null;
    }
    return tables.has(name)
      ? null
      : `Table '${name}' does not exist or is not queryable. The tables are: ${tableList(tables)}.`;
  }
  const fn = node(source, 'function');
  if (fn != null) {
    return `Table function '${String(fn.name)}(...)' is not allowed; read only the Forge tables, CTEs of this query, or subqueries.`;
  }
  return null;
};

const structuralError = (
  sql: string,
  ast: unknown[],
  tables: ReadonlySet<string>,
): string | null => {
  if (ast.length !== 1) {
    return 'Exactly one statement is allowed; remove the extra statements and semicolons.';
  }
  const [statement] = ast;
  if (node(statement, 'select') == null && node(statement, 'union') == null) {
    return 'Only SELECT queries (optionally with WITH or UNION) are allowed.';
  }
  if (/\binto\s+outfile\b/i.test(sql.replaceAll(LITERAL, "''"))) {
    return 'INTO OUTFILE is not allowed; results come back to you.';
  }
  const tableNodes = collect<TableNode>(ast, 'table');
  const foreign = tableNodes.find(
    (table) => table.schema != null && table.schema.name !== 'forge',
  );
  if (foreign?.schema != null) {
    return `Database '${foreign.schema.name}' is not allowed; query only Forge tables (${tableList(tables)}).`;
  }
  const systemColumn = collect<ColumnNode>(ast, 'column').find(
    (column) =>
      column.table != null &&
      SYSTEM_QUALIFIERS.has(column.table.name.toLowerCase()),
  );
  if (systemColumn != null) {
    return `References to '${systemColumn.table?.name ?? ''}' are not allowed; query only Forge tables.`;
  }
  if (
    collect<{ global?: boolean }>(ast, 'in').some(
      (clause) => clause.global === true,
    )
  ) {
    return 'GLOBAL IN is not allowed; use IN.';
  }
  if (tableNodes.some((table) => table.final_)) {
    return 'FINAL is not allowed and not needed: Forge tables are append-only views over Parquet files.';
  }
  const selects = collect<SelectNode>(ast, 'select');
  if (selects.some((select) => (select.settings?.length ?? 0) > 0)) {
    return 'SETTINGS clauses are not allowed; execution limits are applied by the server.';
  }
  if (selects.some((select) => select.format != null)) {
    return 'FORMAT clauses are not allowed; results always come back as JSON rows.';
  }
  const scope: Scope = {
    ctes: new Map(
      selects.flatMap(
        (select) =>
          select.with?.ctes.map(
            (cte) =>
              [cte.alias.name, node(cte.this, 'select') as SelectNode] as const,
          ) ?? [],
      ),
    ),
  };
  for (const select of selects) {
    const from = select.from?.expressions ?? [];
    if (from.length > 1) {
      return `Comma joins are not allowed; write JOIN ... ON a.${RUN_KEY} = b.${RUN_KEY} AND ... so rows of different runs never pair up.`;
    }
    const joins = select.joins.filter((join) => join.kind !== 'Array');
    for (const source of [...from, ...joins.map((join) => join.this)]) {
      const error = sourceError(unwrap(source), scope, tables);
      if (error != null) {
        return error;
      }
    }
    const left = [...from];
    for (const join of joins) {
      const error = joinError(join, left, scope);
      if (error != null) {
        return error;
      }
      left.push(join.this);
    }
  }
  const applied = collect<{ expression: unknown }>(ast, 'apply').flatMap(
    (apply) => {
      const column = node(apply.expression, 'column') as {
        name?: { name?: unknown };
      } | null;
      const name = column?.name?.name;
      return typeof name === 'string' ? [{ name }] : [];
    },
  );
  for (const fn of [
    ...collect<{ name: string }>(ast, 'function'),
    ...applied,
  ]) {
    if (!functionAllowed(fn.name)) {
      return `Function '${fn.name}' is not available here. Use standard aggregate, window, math, date and time, string, array, JSON and conditional functions.`;
    }
  }
  return null;
};

export const validateSql = (
  sql: string,
  tables: ReadonlySet<string>,
): string | null => {
  const result = parse(sql, Dialect.ClickHouse);
  return result.success
    ? structuralError(sql, result.ast, tables)
    : `SQL could not be parsed: ${result.error}.`;
};

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { loadSlabs } from '../slabs/slab.ts';
import { validateSql } from './validate_sql.ts';

const TABLES = new Set(['roboclaw', 'imu', 'runs']);

const SCHEMA_TABLES = new Set(
  [
    ...readFileSync(
      new URL('../../clickhouse/schema.sql', import.meta.url),
      'utf8',
    ).matchAll(/CREATE (?:TABLE|VIEW) IF NOT EXISTS forge\.(\w+)/g),
  ].map(([, name]) => name ?? ''),
);

describe('validateSql', () => {
  it.each([
    'SELECT avg(battery_voltage) AS v FROM roboclaw WHERE run_id = {run_id:String}',
    'SELECT r.run_id, avg(i.accel_z) AS z FROM forge.runs AS r JOIN imu AS i ON i.run_id = r.run_id GROUP BY r.run_id',
    'SELECT c.ts FROM roboclaw AS c ASOF JOIN imu AS i ON c.run_id = i.run_id AND c.ts >= i.ts',
    'SELECT ts FROM roboclaw JOIN imu USING (run_id, ts)',
    'WITH w AS (SELECT run_id, ts FROM roboclaw) SELECT w.ts FROM w JOIN imu AS i ON i.run_id = w.run_id AND i.ts = w.ts',
    'WITH m AS (SELECT run_id, max(left_current) AS peak FROM roboclaw GROUP BY run_id) SELECT i.ts, m.peak FROM imu AS i JOIN m ON m.run_id = i.run_id',
    'SELECT avgIf(left_current, left_pwm > 0) AS a, quantileExactIf(0.9)(right_current, right_pwm > 0) AS q FROM roboclaw',
    'SELECT x FROM (SELECT [1, 2] AS xs FROM roboclaw) ARRAY JOIN xs AS x',
    'SELECT 1 AS a FROM roboclaw UNION ALL SELECT 2 AS a FROM imu',
  ])('accepts %s', (sql) => {
    expect(validateSql(sql, TABLES)).toBeNull();
  });

  it.each([
    [
      'a second statement',
      'SELECT 1 FROM roboclaw; SELECT 2 FROM imu',
      'Exactly one statement',
    ],
    ['a write', 'INSERT INTO roboclaw (run_id) VALUES (1)', 'Only SELECT'],
    ['a system table', 'SELECT name FROM system.tables', "Database 'system'"],
    [
      'a system table through IN',
      'SELECT 1 FROM roboclaw WHERE run_id IN system.users',
      "References to 'system'",
    ],
    ['an unknown table', 'SELECT 1 FROM run_events', "Table 'run_events'"],
    ['FINAL', 'SELECT 1 FROM roboclaw FINAL', 'FINAL'],
    [
      'SETTINGS',
      'SELECT 1 FROM roboclaw SETTINGS max_threads = 64',
      'SETTINGS',
    ],
    ['FORMAT', 'SELECT 1 FROM roboclaw FORMAT JSON', 'FORMAT'],
    [
      'INTO OUTFILE',
      "SELECT 1 FROM roboclaw INTO OUTFILE 'x.csv'",
      'INTO OUTFILE',
    ],
    [
      'GLOBAL IN',
      'SELECT 1 FROM roboclaw WHERE run_id GLOBAL IN (SELECT run_id FROM imu)',
      'GLOBAL IN',
    ],
    ['a table function', 'SELECT number FROM numbers(10)', 'Table function'],
    [
      'a server-state function',
      "SELECT getSetting('max_threads') AS s FROM roboclaw",
      "Function 'getSetting'",
    ],
    [
      'a dictionary read',
      "SELECT dictGet('d', 'v', 1) AS v FROM roboclaw",
      "Function 'dictGet'",
    ],
    [
      'a function outside the allowlist',
      "SELECT hasColumnInTable('system', 'users', 'name') AS h FROM roboclaw",
      "Function 'hasColumnInTable'",
    ],
    [
      'a join on time alone',
      'SELECT 1 FROM roboclaw AS c JOIN imu AS i ON c.ts = i.ts',
      'Every JOIN must match run_id',
    ],
    [
      'a run key compared with itself',
      'SELECT 1 FROM roboclaw AS c JOIN imu AS i ON c.run_id = c.run_id AND c.ts = i.ts',
      'Every JOIN must match run_id',
    ],
    [
      'OR in a join condition',
      'SELECT 1 FROM roboclaw AS c JOIN imu AS i ON c.run_id = i.run_id OR 1 = 1',
      'OR is not allowed',
    ],
    [
      'a join on run_id alone',
      'SELECT 1 FROM roboclaw AS c JOIN imu AS i ON c.run_id = i.run_id',
      'pairs every row',
    ],
    [
      'a cross join',
      'SELECT 1 FROM roboclaw CROSS JOIN imu',
      'Every JOIN must match run_id',
    ],
    ['a comma join', 'SELECT 1 FROM roboclaw, imu', 'Comma joins'],
    ['unparseable SQL', 'SELECT (1 FROM roboclaw', 'could not be parsed'],
  ])('rejects %s', (_, sql, error) => {
    expect(validateSql(sql, TABLES)).toContain(error);
  });

  it.each(loadSlabs().map((slab) => [slab.id, slab.sql]))(
    'accepts slab %s',
    (_, sql) => {
      expect(validateSql(sql, SCHEMA_TABLES)).toBeNull();
    },
  );
});

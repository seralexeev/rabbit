import { describe, expect, it } from 'vitest';

import { causeChains, parseGraph, shortestPath } from './graph.ts';
import { leadLag, robustZ } from './stats.ts';

const SLABS = new Map([['gaps', new Set(['gap_start', 'rebooted'])]]);

const series = (id: string) => `
  ${id}:
    label: ${id}
    group: test
    description: ${id}
    unit: V
    source: { table: power, expr: battery_voltage }
    hz: 10
    floor: 0.01
    slabs: [gaps]`;

const GRAPH = `
nodes:${series('battery_voltage')}${series('battery_current')}${series('motor_current')}${series('motor_left')}
  reboots:
    label: reboots
    group: events
    description: reboots
    events: { slab: gaps, time: gap_start, where: { rebooted: 1 } }
    slabs: [gaps]
edges:
  - { from: battery_current, to: battery_voltage, type: causes, why: sag, evidence: physics, sign: negative }
  - { from: motor_current, to: battery_current, type: drives, why: load, evidence: physics }
  - { from: motor_current, to: motor_left, type: decomposes_into, why: sum, evidence: physics }
  - { from: reboots, to: battery_voltage, type: symptom_of, why: brownout, evidence: physics }
`;

describe('metric graph', () => {
  const graph = parseGraph(GRAPH, SLABS);

  it('walks from a symptom to its causes against symptom_of and decomposes_into', () => {
    const chains = causeChains(graph, 'reboots', 4).map((chain) =>
      chain.map((link) => link.cause),
    );
    expect(chains).toContainEqual([
      'battery_voltage',
      'battery_current',
      'motor_current',
      'motor_left',
    ]);
    expect(chains.flat()).not.toContain('reboots');
  });

  it('finds a path across edge directions', () => {
    expect(
      shortestPath(graph, 'motor_left', 'battery_voltage')?.map(
        (edge) => edge.to,
      ),
    ).toEqual(['motor_left', 'battery_current', 'battery_voltage']);
  });

  it.each([
    [
      'an edge to an unknown node',
      `${GRAPH}  - { from: reboots, to: nowhere, type: causes, why: x, evidence: design }\n`,
    ],
    [
      'an event column the slab does not project',
      GRAPH.replace('time: gap_start', 'time: gap_end'),
    ],
    ['an unknown slab', GRAPH.replace('slabs: [gaps]', 'slabs: [missing]')],
  ])('rejects %s', (_, text) => {
    expect(() => parseGraph(text, SLABS)).toThrow('Invalid metric graph');
  });
});

describe('graph statistics', () => {
  it('scores a spike against the trailing baseline, not the noise', () => {
    const values = Array.from(
      { length: 200 },
      (_, i) => 14 + 0.01 * Math.sin(i) - (i === 150 ? 0.5 : 0),
    );
    const { z } = robustZ(
      values,
      values.map(() => true),
      30,
      0.001,
    );
    const peak = z.reduce(
      (best, value, i) => (Math.abs(value) > Math.abs(z[best] ?? 0) ? i : best),
      0,
    );
    expect(peak).toBe(150);
    expect(z[150]).toBeLessThan(-20);
    expect(Math.abs(z[100] ?? 0)).toBeLessThan(3);
  });

  it('reports a positive lag when the cause leads the effect', () => {
    const cause = Array.from(
      { length: 120 },
      (_, i) => Math.sin(i / 3) + (i % 7) * 0.01,
    );
    const effect = cause.map((_, i) => -(cause[i - 4] ?? 0));
    expect(leadLag(cause, effect, 8, -1)).toMatchObject({ lag: 4 });
  });
});

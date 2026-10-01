import type { GraphSpec } from '../outputs.ts';

export const NODE_W = 132;
export const NODE_H = 42;
const COL_GAP = 58;
const ROW_GAP = 14;
const MARGIN = 12;
const SWEEPS = 6;

type Edge = GraphSpec['edges'][number];

export type PlacedNode = GraphSpec['nodes'][number] & { x: number; y: number; rank: number };

export type PlacedEdge = Edge & { cause: string; effect: string; directed: boolean };

export const REVERSED = new Set(['symptom_of', 'decomposes_into']);

export const orient = (edge: Edge): PlacedEdge =>
    REVERSED.has(edge.type)
        ? { ...edge, cause: edge.to, effect: edge.from, directed: true }
        : { ...edge, cause: edge.from, effect: edge.to, directed: edge.type !== 'correlates_with' };

const acyclic = (ids: string[], edges: PlacedEdge[]) => {
    const state = new Map<string, 'open' | 'done'>();
    const kept: PlacedEdge[] = [];
    const out = new Map<string, PlacedEdge[]>();
    for (const edge of edges) out.set(edge.cause, [...(out.get(edge.cause) ?? []), edge]);
    const visit = (id: string) => {
        state.set(id, 'open');
        for (const edge of out.get(id) ?? []) {
            const next = state.get(edge.effect);
            if (next === 'open') continue;
            kept.push(edge);
            if (next == null) visit(edge.effect);
        }
        state.set(id, 'done');
    };
    for (const id of ids) if (!state.has(id)) visit(id);
    return kept;
};

const ranks = (ids: string[], edges: PlacedEdge[]) => {
    const rank = new Map(ids.map((id) => [id, 0]));
    for (let pass = 0; pass < ids.length; pass++) {
        let changed = false;
        for (const edge of edges) {
            const next = (rank.get(edge.cause) ?? 0) + 1;
            if (next > (rank.get(edge.effect) ?? 0)) {
                rank.set(edge.effect, next);
                changed = true;
            }
        }
        if (!changed) break;
    }
    for (const id of ids) {
        const outgoing = edges.filter((edge) => edge.cause === id);
        if (outgoing.length > 0) {
            const tightest = Math.min(...outgoing.map((edge) => (rank.get(edge.effect) ?? 1) - 1));
            rank.set(id, Math.max(rank.get(id) ?? 0, tightest));
        }
    }
    return rank;
};

export const layoutGraph = (graph: GraphSpec) => {
    const ids = graph.nodes.map((node) => node.id);
    const known = new Set(ids);
    const placed = graph.edges.filter((edge) => known.has(edge.from) && known.has(edge.to)).map(orient);
    const directed = acyclic(
        ids,
        placed.filter((edge) => edge.directed),
    );
    const rank = ranks(ids, directed);
    for (const edge of placed.filter((candidate) => !candidate.directed)) {
        const a = rank.get(edge.cause) ?? 0;
        const b = rank.get(edge.effect) ?? 0;
        const linked = directed.some((other) => other.cause === edge.effect || other.effect === edge.effect);
        if (!linked) rank.set(edge.effect, a);
        else if (!directed.some((other) => other.cause === edge.cause || other.effect === edge.cause)) rank.set(edge.cause, b);
    }
    const columns: string[][] = [];
    for (const id of ids) {
        const r = rank.get(id) ?? 0;
        (columns[r] ??= []).push(id);
    }
    const order = new Map<string, number>();
    const reindex = () => columns.forEach((column) => column?.forEach((id, i) => order.set(id, i)));
    reindex();
    const neighbours = (id: string, side: 'cause' | 'effect') =>
        placed.filter((edge) => edge[side === 'cause' ? 'effect' : 'cause'] === id).map((edge) => edge[side]);
    for (let sweep = 0; sweep < SWEEPS; sweep++) {
        const side = sweep % 2 === 0 ? 'cause' : 'effect';
        for (const column of columns) {
            if (column == null) continue;
            const weight = (id: string) => {
                const linked = neighbours(id, side).filter((other) => order.has(other));
                return linked.length === 0
                    ? (order.get(id) ?? 0)
                    : linked.reduce((total, other) => total + (order.get(other) ?? 0), 0) / linked.length;
            };
            column.sort((a, b) => weight(a) - weight(b));
        }
        reindex();
    }
    const tallest = Math.max(1, ...columns.map((column) => column?.length ?? 0));
    const fullHeight = tallest * (NODE_H + ROW_GAP) - ROW_GAP;
    const nodes: PlacedNode[] = graph.nodes.map((node) => {
        const r = rank.get(node.id) ?? 0;
        const column = columns[r] ?? [];
        const height = column.length * (NODE_H + ROW_GAP) - ROW_GAP;
        return {
            ...node,
            rank: r,
            x: MARGIN + r * (NODE_W + COL_GAP),
            y: MARGIN + (fullHeight - height) / 2 + (order.get(node.id) ?? 0) * (NODE_H + ROW_GAP),
        };
    });
    return {
        nodes,
        edges: placed,
        width: MARGIN * 2 + columns.length * (NODE_W + COL_GAP) - COL_GAP,
        height: MARGIN * 2 + fullHeight,
    };
};

export const edgePath = (from: PlacedNode, to: PlacedNode) => {
    if (to.rank > from.rank) {
        const x1 = from.x + NODE_W;
        const y1 = from.y + NODE_H / 2;
        const x2 = to.x;
        const y2 = to.y + NODE_H / 2;
        const bend = (x2 - x1) / 2;
        const share = to.rank - from.rank > 1 ? 0.18 : 0.5;
        return {
            d: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`,
            mx: x1 + (x2 - x1) * share,
            my: y1 + (y2 - y1) * share * share * (3 - 2 * share),
        };
    }
    if (to.rank === from.rank) {
        const x = from.x + NODE_W;
        const y1 = from.y + NODE_H / 2;
        const y2 = to.y + NODE_H / 2;
        const bulge = 26 + Math.abs(y2 - y1) * 0.15;
        return { d: `M${x},${y1} C${x + bulge},${y1} ${x + bulge},${y2} ${x},${y2}`, mx: x + bulge * 0.75, my: (y1 + y2) / 2 };
    }
    const x1 = from.x + NODE_W / 2;
    const y1 = from.y;
    const x2 = to.x + NODE_W / 2;
    const y2 = to.y;
    const lift = 30;
    return {
        d: `M${x1},${y1} C${x1},${y1 - lift} ${x2},${y2 - lift} ${x2},${y2}`,
        mx: (x1 + x2) / 2,
        my: Math.min(y1, y2) - lift * 0.75,
    };
};

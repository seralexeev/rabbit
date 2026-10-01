import { css, cx } from '@emotion/css';
import React from 'react';

import { ChartView } from '../ChartView.tsx';
import { useChatActions } from '../ChatActions.ts';
import { Sparkline } from '../charts/Sparkline.tsx';
import { type GraphSpec, formatValue } from '../outputs.ts';
import { cardCss } from '../widgets/kit.tsx';
import { NODE_H, NODE_W, type PlacedEdge, type PlacedNode, edgePath, layoutGraph } from './layout.ts';

const MAX_HEIGHT = 380;
const MIN_SCALE = 0.35;
const MAX_SCALE = 2.5;

const RELATION: Record<string, { label: string; reverse?: string }> = {
    decomposes_into: { label: 'decomposes into', reverse: 'part of' },
    drives: { label: 'drives' },
    causes: { label: 'causes' },
    explains: { label: 'explains' },
    correlates_with: { label: 'correlates' },
    guards: { label: 'guards' },
    symptom_of: { label: 'symptom of', reverse: 'shows as' },
};

const relationLabel = (edge: PlacedEdge) => {
    const relation = RELATION[edge.type];
    if (relation == null) return edge.label ?? edge.type;
    return edge.cause === edge.from ? relation.label : (relation.reverse ?? relation.label);
};

const edgeKey = (edge: { from: string; to: string }) => `${edge.from}>${edge.to}`;

const followUp = (graph: GraphSpec, node: PlacedNode) => {
    if (graph.symptom != null && graph.run_id != null) {
        const range =
            graph.focus?.from != null && graph.focus.to != null
                ? ` between ${graph.focus.from.slice(11, 19)} and ${graph.focus.to.slice(11, 19)} UTC`
                : '';
        return node.id === graph.symptom
            ? `What else could explain ${node.label.toLowerCase()} (${node.id}) in run ${graph.run_id}${range}?`
            : `Investigate ${node.label.toLowerCase()} (${node.id}) in run ${graph.run_id}${range}: what drove it?`;
    }
    return `Show the metric graph around ${node.id} and explain how ${node.label.toLowerCase()} relates to its neighbours`;
};

type View = { x: number; y: number; scale: number };

export const GraphView: React.FC<{ graph: GraphSpec }> = ({ graph }) => {
    const { ask } = useChatActions();
    const layout = React.useMemo(() => layoutGraph(graph), [graph]);
    const [hover, setHover] = React.useState<string | null>(null);
    const [view, setView] = React.useState<View>({ x: 0, y: 0, scale: 1 });
    const dragRef = React.useRef<{ x: number; y: number; view: View; moved: boolean } | null>(null);
    const byId = new Map(layout.nodes.map((node) => [node.id, node]));
    const chain = new Set(graph.highlights?.nodes ?? []);
    const chainEdges = new Set((graph.highlights?.edges ?? []).map(([from, to]) => edgeKey({ from, to })));
    const height = Math.min(MAX_HEIGHT, layout.height);
    const labelAll = layout.edges.length <= 16;

    const onWheel = (event: React.WheelEvent<SVGSVGElement>) => {
        if (!event.ctrlKey && !event.metaKey && !event.altKey) return;
        event.preventDefault();
        const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
        setView((prev) => ({ ...prev, scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, prev.scale * factor)) }));
    };

    const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
        dragRef.current = { x: event.clientX, y: event.clientY, view, moved: false };
    };

    const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
        const drag = dragRef.current;
        if (drag == null) return;
        const dx = event.clientX - drag.x;
        const dy = event.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) < 4) return;
        if (!drag.moved) event.currentTarget.setPointerCapture(event.pointerId);
        drag.moved = true;
        setView({ ...drag.view, x: drag.view.x - dx / drag.view.scale, y: drag.view.y - dy / drag.view.scale });
    };

    const onPointerUp = (event: React.PointerEvent<SVGSVGElement>) => {
        const drag = dragRef.current;
        dragRef.current = null;
        if (drag?.moved === true) {
            event.currentTarget.releasePointerCapture(event.pointerId);
            return;
        }
        const target = (event.target as Element).closest('[data-node]');
        const node = target == null ? undefined : byId.get(target.getAttribute('data-node') ?? '');
        if (node != null) ask(followUp(graph, node));
    };

    const zoom = (factor: number) =>
        setView((prev) => ({ ...prev, scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, prev.scale * factor)) }));

    const box = `${view.x} ${view.y} ${layout.width / view.scale} ${height / view.scale}`;
    const topChain = graph.highlights?.nodes ?? [];

    return (
        <figure className={cx(cardCss, figureCss)}>
            <figcaption className={captionCss}>
                <span>{graph.title ?? 'METRIC GRAPH'}</span>
                <span className={countCss}>
                    {graph.nodes.length} NODES · {graph.edges.length} LINKS
                </span>
                <button className={toolCss} onClick={() => zoom(1.2)} title='Zoom in'>
                    +
                </button>
                <button className={toolCss} onClick={() => zoom(1 / 1.2)} title='Zoom out'>
                    −
                </button>
                <button className={toolCss} onClick={() => setView({ x: 0, y: 0, scale: 1 })} title='Fit'>
                    FIT
                </button>
            </figcaption>
            {topChain.length > 1 && (
                <div className={chainCss}>
                    {topChain
                        .map((id) => byId.get(id))
                        .filter((node) => node != null)
                        .map((node, i) => (
                            <React.Fragment key={node.id}>
                                {i > 0 && <span className={arrowCss}>←</span>}
                                <span data-status={node.status ?? 'ok'}>{node.label}</span>
                            </React.Fragment>
                        ))}
                </div>
            )}
            <svg
                className={svgCss}
                viewBox={box}
                height={height}
                preserveAspectRatio='xMinYMin meet'
                onWheel={onWheel}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerLeave={() => setHover(null)}>
                <defs>
                    <marker id='graph-arrow' viewBox='0 0 8 8' refX='7' refY='4' markerWidth='6' markerHeight='6' orient='auto'>
                        <path d='M0,0 L8,4 L0,8 z' className={arrowHeadCss} />
                    </marker>
                    <marker
                        id='graph-arrow-hot'
                        viewBox='0 0 8 8'
                        refX='7'
                        refY='4'
                        markerWidth='7'
                        markerHeight='7'
                        orient='auto'>
                        <path d='M0,0 L8,4 L0,8 z' className={arrowHotCss} />
                    </marker>
                </defs>
                {layout.edges.map((edge) => {
                    const from = byId.get(edge.cause);
                    const to = byId.get(edge.effect);
                    if (from == null || to == null) return null;
                    const { d, mx, my } = edgePath(from, to);
                    const hot = chainEdges.has(edgeKey(edge));
                    const touched = hover != null && (edge.from === hover || edge.to === hover);
                    const dim = hover != null && !touched;
                    return (
                        <g
                            key={`${edgeKey(edge)}-${edge.type}`}
                            className={edgeCss}
                            data-type={edge.type}
                            data-hot={hot}
                            data-dim={dim}>
                            <title>{`${edge.from} ${edge.type.replaceAll('_', ' ')} ${edge.to}${edge.why == null ? '' : `: ${edge.why}`}${edge.score == null ? '' : ` (score ${formatValue(edge.score)}${edge.lag_s == null ? '' : `, lag ${formatValue(edge.lag_s)} s`})`}`}</title>
                            <path
                                d={d}
                                markerEnd={edge.directed ? `url(#${hot ? 'graph-arrow-hot' : 'graph-arrow'})` : undefined}
                            />
                            {(labelAll || hot || touched) && (
                                <text x={mx} y={my - 3} textAnchor='middle'>
                                    {relationLabel(edge)}
                                    {edge.score == null ? '' : ` ${edge.score.toFixed(2)}`}
                                </text>
                            )}
                        </g>
                    );
                })}
                {layout.nodes.map((node) => (
                    <g
                        key={node.id}
                        data-node={node.id}
                        className={nodeCss}
                        data-role={node.role ?? 'context'}
                        data-status={node.status ?? 'none'}
                        data-hot={chain.has(node.id)}
                        data-dim={
                            hover != null &&
                            hover !== node.id &&
                            !layout.edges.some(
                                (edge) =>
                                    (edge.from === hover && edge.to === node.id) ||
                                    (edge.to === hover && edge.from === node.id),
                            )
                        }
                        transform={`translate(${node.x},${node.y})`}
                        onPointerEnter={() => setHover(node.id)}>
                        <title>{`${node.label} (${node.id})${node.group == null ? '' : ` · ${node.group}`}${node.value == null ? '' : ` · ${node.value}`}${node.score == null ? '' : ` · link score ${formatValue(node.score)}`}\nClick to ask about it`}</title>
                        <polygon points={`6,0 ${NODE_W},0 ${NODE_W},${NODE_H - 6} ${NODE_W - 6},${NODE_H} 0,${NODE_H} 0,6`} />
                        <text x={7} y={14} className={labelCss}>
                            {node.label.length > 21 ? `${node.label.slice(0, 20)}…` : node.label}
                        </text>
                        <text x={7} y={28} className={valueCss}>
                            {node.value ?? node.unit ?? node.group ?? ''}
                        </text>
                        {node.spark != null && node.spark.length > 1 && (
                            <foreignObject x={NODE_W - 58} y={NODE_H - 18} width={54} height={16}>
                                <Sparkline
                                    values={node.spark}
                                    width={52}
                                    height={14}
                                    tone={node.status == null || node.status === 'ok' ? 'info' : node.status}
                                />
                            </foreignObject>
                        )}
                    </g>
                ))}
            </svg>
            <div className={hintCss} data-hint>
                CLICK A NODE TO ASK · DRAG TO PAN · CTRL+WHEEL TO ZOOM · HOVER A LINK FOR ITS REASON
            </div>
            {graph.chart != null && <ChartView chart={graph.chart} height={150} />}
        </figure>
    );
};

const figureCss = css`
    &:not(:hover) [data-hint] {
        opacity: 0;
    }
`;

const captionCss = css`
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 4px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;

    & > span:first-child {
        flex: 1;
    }
`;

const countCss = css`
    font-size: 8px;
    font-weight: 400;
    opacity: 0.55;
`;

const toolCss = css`
    min-width: 16px;
    padding: 0 4px;
    border: none;
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 8px;
    cursor: pointer;

    &:hover {
        background: var(--hud-faint);
    }
`;

const chainCss = css`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    margin-bottom: 4px;
    font-size: 9px;
    text-transform: none;

    & > span[data-status] {
        padding: 0 4px;
        border: 1px solid var(--hud-dim);
        color: var(--hud);
    }

    & > span[data-status='warn'] {
        border-color: var(--hud-amber);
        color: var(--hud-amber);
    }

    & > span[data-status='alert'] {
        border-color: var(--hud-alert);
        color: var(--hud-alert);
    }
`;

const arrowCss = css`
    opacity: 0.5;
`;

const svgCss = css`
    display: block;
    width: 100%;
    cursor: grab;
    touch-action: none;
    user-select: none;

    &:active {
        cursor: grabbing;
    }
`;

const arrowHeadCss = css`
    fill: rgba(98, 232, 255, 0.55);
`;

const arrowHotCss = css`
    fill: #62e8ff;
`;

const edgeCss = css`
    --edge: rgba(98, 232, 255, 0.4);

    & path {
        fill: none;
        stroke: var(--edge);
        stroke-width: 1;
    }

    & text {
        fill: var(--edge);
        font:
            8px 'JetBrains Mono',
            monospace;
        paint-order: stroke;
        stroke: #03090d;
        stroke-width: 3px;
    }

    &[data-type='explains'] path {
        stroke-dasharray: 5 3;
    }

    &[data-type='correlates_with'] path {
        stroke-dasharray: 2 3;
    }

    &[data-type='guards'] {
        --edge: rgba(255, 181, 71, 0.6);
    }

    &[data-type='guards'] path {
        stroke-dasharray: 6 2 1 2;
    }

    &[data-type='symptom_of'] {
        --edge: rgba(255, 122, 168, 0.55);
    }

    &[data-type='decomposes_into'] path {
        stroke-width: 2;
        stroke-opacity: 0.5;
    }

    &[data-hot='true'] {
        --edge: #62e8ff;
    }

    &[data-hot='true'] path {
        stroke-width: 2;
        filter: drop-shadow(0 0 3px var(--hud-glow));
    }

    &[data-dim='true'] {
        opacity: 0.2;
    }
`;

const nodeCss = css`
    cursor: pointer;

    --edge: rgba(98, 232, 255, 0.45);

    & polygon {
        fill: #061218;
        stroke: var(--edge);
        stroke-width: 1;
    }

    &[data-status='warn'] {
        --edge: var(--hud-amber);
    }

    &[data-status='alert'] {
        --edge: var(--hud-alert);
    }

    &[data-role='symptom'] polygon,
    &[data-role='focus'] polygon {
        stroke-width: 2;
    }

    &[data-hot='true'] polygon {
        fill: #0a2530;
        filter: drop-shadow(0 0 4px var(--hud-glow));
    }

    &[data-dim='true'] {
        opacity: 0.3;
    }

    &:hover polygon {
        fill: #0d3240;
    }
`;

const labelCss = css`
    fill: #e6fbff;
    font:
        600 9px 'JetBrains Mono',
        monospace;
`;

const valueCss = css`
    fill: var(--edge);
    font:
        8.5px 'JetBrains Mono',
        monospace;
`;

const hintCss = css`
    margin: 2px 0;
    font-size: 7.5px;
    letter-spacing: 0.1em;
    opacity: 0.45;
`;

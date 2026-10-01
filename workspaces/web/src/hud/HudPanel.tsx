import { css, cx, keyframes } from '@emotion/css';
import React from 'react';

import { type ChannelName, isLive } from '../perception/Telemetry.ts';
import { type PanelId, useHud, useHudTick } from './HudContext.ts';
import { HudModal } from './HudModal.tsx';
import { frameCss } from './frame.ts';

type HudPanelProps = {
    id: PanelId;
    code: string;
    title: string;
    source?: ChannelName;
    live?: boolean;
    detail: React.ReactNode;
    children: React.ReactNode;
};

export const HudPanel: React.FC<HudPanelProps> = ({ id, code, title, source, live, detail, children }) => {
    const [expanded, setExpanded] = React.useState(false);
    const { engine, store, layout, toggle, swap, raise } = useHud();
    const ref = React.useRef<HTMLElement | null>(null);
    const linkRef = React.useRef<HTMLSpanElement | null>(null);
    const collapsed = layout.collapsed.includes(id);
    const side = layout.left.includes(id) ? 'left' : 'right';

    React.useLayoutEffect(() => {
        const element = ref.current;
        if (element == null) return;
        return engine.register(id, element);
    }, [engine, id]);

    useHudTick((now) => {
        const link = linkRef.current;
        if (source == null || link == null) return;
        const next = isLive(store[source], now) ? 'LINK' : 'LOST';
        if (link.textContent !== next) {
            link.textContent = next;
            link.dataset['lost'] = String(next === 'LOST');
            if (ref.current != null) ref.current.dataset['lost'] = String(next === 'LOST');
        }
    });

    return (
        <section ref={ref} className={panelCss} data-side={side} data-lost={source == null ? live === false : undefined}>
            <header className={headCss}>
                <button className={titleButtonCss} onClick={() => toggle(id)} title={collapsed ? 'Expand' : 'Collapse'}>
                    <span className={codeCss}>{code}</span>
                    <span className={titleCss}>{title}</span>
                    <span className={chevronCss}>{collapsed ? '▸' : '▾'}</span>
                </button>
                <span ref={linkRef} className={linkCss} data-lost={live === false}>
                    {source == null && live == null ? '' : live === false ? 'LOST' : 'LINK'}
                </span>
                <button className={iconButtonCss} onClick={() => setExpanded(true)} title='Expand'>
                    ⤢
                </button>
                <button className={iconButtonCss} onClick={() => raise(id)} title='Move up'>
                    ▲
                </button>
                <button className={iconButtonCss} onClick={() => swap(id)} title={side === 'left' ? 'Move right' : 'Move left'}>
                    {side === 'left' ? '▶' : '◀'}
                </button>
            </header>
            <div className={ticksCss} />
            {!collapsed && (
                <div className={cx(bodyCss, 'hud-body')}>
                    {expanded ? <div className={openCss}>OPEN IN DETAIL VIEW</div> : children}
                </div>
            )}
            {expanded && (
                <HudModal code={code} title={title} onClose={() => setExpanded(false)}>
                    {detail}
                </HudModal>
            )}
        </section>
    );
};

const blink = keyframes`
    0%, 60% { opacity: 1; }
    61%, 100% { opacity: 0.25; }
`;

const panelCss = cx(
    frameCss,
    css`
        position: absolute;
        left: 0;
        top: 0;
        width: var(--hud-column);
        pointer-events: auto;
        visibility: hidden;
        will-change: transform;

        &[data-placed='true'] {
            visibility: visible;
        }

        &[data-compact='true'] > .hud-body {
            display: none;
        }

        &[data-lost='true'] > .hud-body > :not(button, :has(button)) {
            opacity: 0.45;
        }
    `,
);

const headCss = css`
    display: flex;
    align-items: center;
    gap: 4px;
    height: 16px;
`;

const buttonResetCss = css`
    padding: 0;
    border: none;
    background: none;
    color: inherit;
    font: inherit;
    letter-spacing: inherit;
    text-transform: inherit;
    text-shadow: inherit;
    cursor: pointer;
`;

const titleButtonCss = cx(
    buttonResetCss,
    css`
        flex: 1 1 auto;
        display: flex;
        align-items: center;
        gap: 6px;
        font-weight: 600;
        text-align: left;
        overflow: hidden;
    `,
);

const iconButtonCss = cx(
    buttonResetCss,
    css`
        width: 16px;
        height: 16px;
        font-size: 8px;
        opacity: 0.45;

        &:hover {
            opacity: 1;
            background: var(--hud-faint);
        }
    `,
);

const codeCss = css`
    padding: 0 5px;
    font-size: 9px;
    line-height: 12px;
    color: #031016;
    background: var(--hud);
    clip-path: polygon(4px 0, calc(100% - 4px) 0, 100% 50%, calc(100% - 4px) 100%, 4px 100%, 0 50%);
    text-shadow: none;
`;

const titleCss = css`
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const chevronCss = css`
    font-size: 8px;
    opacity: 0.5;
`;

const linkCss = css`
    font-size: 8px;
    opacity: 0.8;
    animation: ${blink} 1.6s steps(1) infinite;

    &[data-lost='true'] {
        color: var(--hud-amber);
        animation: none;
    }
`;

const ticksCss = css`
    height: 4px;
    margin: 3px 0 4px;
    border-top: 1px solid var(--hud-faint);
    background: repeating-linear-gradient(90deg, var(--hud-faint) 0 1px, transparent 1px 6px);
`;

const openCss = css`
    padding: 6px 0;
    text-align: center;
    font-size: 9px;
    opacity: 0.5;
`;

const bodyCss = css`
    display: flex;
    flex-direction: column;
`;

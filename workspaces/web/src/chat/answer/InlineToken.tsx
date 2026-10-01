import { css } from '@emotion/css';
import React from 'react';

import { useChatActions } from '../ChatActions.ts';
import { Sparkline } from '../charts/Sparkline.tsx';
import { type Token, refLabel, refQuestion } from './tokens.ts';

const FLASH_MS = 1400;

const reveal = (id: string) => {
    const target = document.querySelector<HTMLElement>(`[data-output-id="${CSS.escape(id)}"]`);
    if (target == null) return false;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.setAttribute('data-flash', 'true');
    window.setTimeout(() => target.removeAttribute('data-flash'), FLASH_MS);
    return true;
};

export const InlineToken: React.FC<{ token: Token }> = ({ token }) => {
    const { ask } = useChatActions();
    switch (token.kind) {
        case 'status':
            return (
                <span className={statusCss} data-tone={token.tone}>
                    {token.tone === 'ok' || token.tone === 'info' ? '●' : '▲'} {token.text}
                </span>
            );
        case 'kpi':
            return (
                <span className={kpiCss}>
                    <span>{token.label}</span>
                    <b>{token.value}</b>
                </span>
            );
        case 'spark':
            return (
                <span className={sparkCss}>
                    <Sparkline values={token.values} width={Math.min(96, Math.max(40, token.values.length * 3))} />
                </span>
            );
        case 'next':
            return (
                <button className={nextCss} onClick={() => ask(token.text)}>
                    › {token.text}
                </button>
            );
        case 'ref':
            return (
                <button
                    className={refCss}
                    data-ref={token.ref}
                    title={refQuestion(token)}
                    onClick={() => {
                        if ((token.ref === 'chart' || token.ref === 'graph') && reveal(token.target)) return;
                        ask(refQuestion(token));
                    }}>
                    ⌖ {refLabel(token)}
                </button>
            );
    }
};

const chipBase = `
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin: 1px 2px;
    padding: 0 5px;
    font: inherit;
    font-size: 9.5px;
    line-height: 15px;
    letter-spacing: 0.04em;
    vertical-align: baseline;
`;

const statusCss = css`
    ${chipBase}
    border: 1px solid var(--tone);
    color: var(--tone);
    background: #03090d;
    font-weight: 600;
    text-transform: uppercase;

    --tone: var(--hud-good);

    &[data-tone='info'] {
        --tone: var(--hud-dim);
    }

    &[data-tone='warn'] {
        --tone: var(--hud-amber);
    }

    &[data-tone='alert'] {
        --tone: var(--hud-alert);
    }
`;

const kpiCss = css`
    ${chipBase}
    flex-direction: column;
    align-items: flex-start;
    gap: 0;
    padding: 2px 7px;
    border-left: 2px solid var(--hud);
    background: #071a22;
    line-height: 12px;

    & > span {
        font-size: 7.5px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        opacity: 0.6;
    }

    & > b {
        color: #fff;
        font-size: 12px;
        font-weight: 600;
    }
`;

const sparkCss = css`
    display: inline-block;
    margin: 0 3px;
    padding: 1px 3px;
    background: #03090d;
    border: 1px solid var(--hud-faint);
    line-height: 0;
    vertical-align: middle;
`;

const refCss = css`
    ${chipBase}
    border: 1px dashed var(--hud-dim);
    background: #03090d;
    color: var(--hud);
    cursor: pointer;
    text-transform: none;

    &:hover {
        border-style: solid;
        background: #0a2530;
    }
`;

const nextCss = css`
    ${chipBase}
    border: 1px solid var(--hud-faint);
    background: #061218;
    color: var(--hud);
    cursor: pointer;
    text-align: left;

    &:hover {
        border-color: var(--hud);
        background: #0a2530;
    }
`;

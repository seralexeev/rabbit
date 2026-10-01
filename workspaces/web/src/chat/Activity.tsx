import { css, keyframes } from '@emotion/css';
import { type DynamicToolUIPart, type ToolUIPart, getToolName } from 'ai';
import React from 'react';

import { summarizeInput } from './outputs.ts';

export type ToolPart = ToolUIPart | DynamicToolUIPart;

type Outcome = 'running' | 'waiting' | 'done' | 'failed' | 'denied';

const outcomeOf = (part: ToolPart): Outcome => {
    switch (part.state) {
        case 'input-streaming':
        case 'input-available':
            return 'running';
        case 'approval-requested':
            return 'waiting';
        case 'approval-responded':
            return part.approval.approved ? 'running' : 'denied';
        case 'output-available':
            return 'done';
        case 'output-error':
            return 'failed';
        case 'output-denied':
            return 'denied';
    }
};

const GLYPHS: Record<Outcome, string> = { running: '◌', waiting: '▲', done: '✓', failed: '✕', denied: '⊘' };

const countBy = (items: string[]) => {
    const counts = new Map<string, number>();
    for (const item of items) counts.set(item, (counts.get(item) ?? 0) + 1);
    return [...counts].map(([name, count]) => (count > 1 ? `${name} ×${count}` : name));
};

const toolLabel = (name: string) => name.replace(/_/g, ' ');

const ToolRow: React.FC<{ part: ToolPart }> = ({ part }) => {
    const [open, setOpen] = React.useState(false);
    const outcome = outcomeOf(part);
    return (
        <li className={rowCss} data-outcome={outcome}>
            <button className={rowButtonCss} onClick={() => setOpen((value) => !value)} title='Show input and output'>
                <span className={glyphCss}>{GLYPHS[outcome]}</span>
                <span className={nameCss}>{toolLabel(getToolName(part))}</span>
                <span className={argsCss}>{summarizeInput(part.input)}</span>
            </button>
            {part.state === 'output-error' && <div className={errorCss}>{part.errorText}</div>}
            {part.state === 'output-denied' && part.approval.reason != null && (
                <div className={errorCss}>{part.approval.reason}</div>
            )}
            {open && (
                <pre className={detailsCss}>
                    {JSON.stringify(
                        { input: part.input, output: part.state === 'output-available' ? part.output : undefined },
                        null,
                        2,
                    )}
                </pre>
            )}
        </li>
    );
};

export const Activity: React.FC<{ parts: ToolPart[] }> = ({ parts }) => {
    const [open, setOpen] = React.useState(false);
    const outcomes = parts.map(outcomeOf);
    const running = parts.find((_, i) => outcomes[i] === 'running');
    const failed = outcomes.filter((outcome) => outcome === 'failed').length;
    const denied = outcomes.filter((outcome) => outcome === 'denied').length;
    const tone = running != null ? 'busy' : failed > 0 || denied > 0 ? 'alert' : 'done';
    const status = [
        running == null ? null : `${toolLabel(getToolName(running))}…`,
        failed > 0 ? `${failed} failed` : null,
        denied > 0 ? `${denied} denied` : null,
    ].filter((item) => item != null);

    return (
        <div className={activityCss}>
            <button className={summaryCss} data-tone={tone} aria-expanded={open} onClick={() => setOpen((value) => !value)}>
                <span className={caretCss}>{open ? '▾' : '▸'}</span>
                <span className={countCss}>
                    {parts.length} {parts.length === 1 ? 'step' : 'steps'}
                </span>
                <span className={namesCss}>{countBy(parts.map((part) => toolLabel(getToolName(part)))).join(' · ')}</span>
                {status.length > 0 && <span className={statusCss}>{status.join(' · ')}</span>}
            </button>
            {open && (
                <ol className={listCss}>
                    {parts.map((part) => (
                        <ToolRow key={part.toolCallId} part={part} />
                    ))}
                </ol>
            )}
        </div>
    );
};

const pulse = keyframes`
    50% { opacity: 0.35; }
`;

const activityCss = css`
    margin: 0 0 4px;
`;

const summaryCss = css`
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 1px 0;
    border: none;
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 9px;
    letter-spacing: 0.06em;
    text-align: left;
    text-transform: uppercase;
    cursor: pointer;
    opacity: 0.55;

    &:hover,
    &[aria-expanded='true'] {
        opacity: 0.9;
    }

    &[data-tone='busy'] {
        opacity: 0.9;
    }

    &[data-tone='alert'] {
        opacity: 0.85;
    }
`;

const caretCss = css`
    width: 8px;
`;

const countCss = css`
    font-weight: 600;
    white-space: nowrap;
`;

const namesCss = css`
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    opacity: 0.75;
`;

const statusCss = css`
    white-space: nowrap;

    [data-tone='busy'] > & {
        color: var(--hud);
        animation: ${pulse} 1s steps(2) infinite;
    }

    [data-tone='alert'] > & {
        color: var(--hud-alert);
    }
`;

const listCss = css`
    margin: 2px 0 0 3px;
    padding: 0 0 0 9px;
    list-style: none;
    border-left: 1px solid var(--hud-faint);
`;

const rowCss = css`
    --tone: var(--hud-dim);

    &[data-outcome='running'] {
        --tone: var(--hud);
    }

    &[data-outcome='waiting'] {
        --tone: var(--hud-amber);
    }

    &[data-outcome='failed'],
    &[data-outcome='denied'] {
        --tone: var(--hud-alert);
    }
`;

const rowButtonCss = css`
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 1px 0;
    border: none;
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 9.5px;
    text-align: left;
    cursor: pointer;

    &:hover {
        background: rgba(98, 232, 255, 0.05);
    }
`;

const glyphCss = css`
    width: 10px;
    color: var(--tone);
    text-align: center;
`;

const nameCss = css`
    font-weight: 600;
    text-transform: uppercase;
    white-space: nowrap;
`;

const argsCss = css`
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    opacity: 0.5;
`;

const errorCss = css`
    margin: 1px 0 3px 16px;
    color: var(--hud-alert);
    font-size: 9.5px;
    text-transform: none;
`;

const detailsCss = css`
    margin: 2px 0 4px 16px;
    padding: 6px;
    max-height: 200px;
    overflow: auto;
    font-size: 9px;
    background: rgba(0, 0, 0, 0.5);
    text-transform: none;
`;

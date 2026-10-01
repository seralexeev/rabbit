import { css } from '@emotion/css';
import React from 'react';

import { type MissionStep, describeStep } from '../perception/mission.ts';

const GLYPHS: Record<MissionStep['type'], string> = { turn: '↻', move: '➜', goto: '◎', path: '⤳' };

type MissionStepsProps = { steps: MissionStep[]; current?: number; progress?: string; start?: number };

export const MissionSteps: React.FC<MissionStepsProps> = ({ steps, current, progress, start = 1 }) => (
    <ol className={listCss}>
        {steps.map((step, i) => {
            const status = current == null ? 'pending' : i + 1 < current ? 'done' : i + 1 === current ? 'current' : 'pending';
            return (
                <li key={i} className={stepCss} data-status={status}>
                    <span className={indexCss}>{String(start + i).padStart(2, '0')}</span>
                    <span className={glyphCss}>{status === 'done' ? '✓' : GLYPHS[step.type]}</span>
                    <span className={textCss}>{describeStep(step)}</span>
                    {status === 'current' && progress != null && <span className={progressCss}>{progress}</span>}
                </li>
            );
        })}
    </ol>
);

const listCss = css`
    margin: 4px 0;
    padding: 0;
    list-style: none;
`;

const stepCss = css`
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 1px 0;
    font-size: 10px;
    color: var(--hud);

    &[data-status='done'] {
        opacity: 0.4;
    }

    &[data-status='current'] {
        color: var(--hud-amber);
        font-weight: 600;
    }
`;

const indexCss = css`
    opacity: 0.5;
    font-size: 8px;
`;

const glyphCss = css`
    width: 10px;
    text-align: center;
`;

const textCss = css`
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const progressCss = css`
    font-size: 9px;
    text-transform: none;
`;

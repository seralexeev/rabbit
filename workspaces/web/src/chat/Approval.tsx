import { css, cx } from '@emotion/css';
import React from 'react';

import { useHud } from '../hud/HudContext.ts';
import { MissionSteps } from '../hud/MissionSteps.tsx';
import { isLive } from '../perception/Telemetry.ts';
import { readSteps } from '../perception/mission.ts';
import { summarizeInput } from './outputs.ts';
import { type Point, type Pose, missionPath } from './results.ts';
import { PathView } from './widgets/PathView.tsx';

const LIVE_POSE_MS = 3000;

const useStartPose = () => {
    const { store } = useHud();
    const [snapshot] = React.useState(() => {
        const now = performance.now();
        const { derived } = store;
        const pose: Pose | null =
            derived.hasPose && isLive(store.pose, now, LIVE_POSE_MS)
                ? { x: derived.x, z: derived.z, heading: derived.heading }
                : null;
        const obstacle = isLive(store.obstacle, now, LIVE_POSE_MS) ? store.obstacle.value : null;
        const obstacles: Point[] = [obstacle?.nearest, obstacle?.ahead].flatMap((contact) =>
            contact == null ? [] : [{ x: contact.point[0], z: contact.point[2] }],
        );
        return { pose, obstacles };
    });
    return snapshot;
};

type ApprovalProps = {
    name: string;
    input: unknown;
    reason: string | undefined;
    onDecision: (approved: boolean) => void;
};

export const Approval: React.FC<ApprovalProps> = ({ name, input, reason, onDecision }) => {
    const steps = readSteps(input);
    const { pose, obstacles } = useStartPose();
    const path = steps == null ? null : missionPath(steps, pose ?? { x: 0, z: 0, heading: 0 }, pose == null ? [] : obstacles);

    return (
        <section className={approvalCss}>
            <header className={titleCss}>
                <span>▲ Approve motion</span>
                <span className={toolCss}>{name.replace(/_/g, ' ')}</span>
            </header>
            {reason != null && <div className={reasonCss}>{reason}</div>}
            {steps == null || path == null ? (
                <div className={reasonCss}>{summarizeInput(input, 160)}</div>
            ) : (
                <div className={planCss}>
                    <MissionSteps steps={steps} />
                    <div>
                        <PathView path={path} height={120} />
                        {pose == null && <div className={hintCss}>NO LIVE POSE · DRAWN FROM THE ORIGIN, FACING -Z</div>}
                    </div>
                </div>
            )}
            <div className={actionsCss}>
                <button className={cx(decisionCss, approveCss)} onClick={() => onDecision(true)}>
                    APPROVE
                </button>
                <button className={cx(decisionCss, denyCss)} onClick={() => onDecision(false)}>
                    DENY
                </button>
            </div>
        </section>
    );
};

const approvalCss = css`
    margin: 8px 0 0;
    padding: 7px 9px 8px;
    background: #140e04;
    box-shadow:
        inset 0 0 0 1px var(--hud-amber),
        0 0 14px rgba(255, 181, 71, 0.18);
    color: var(--hud-amber);
`;

const titleCss = css`
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;

    & > span:first-child {
        flex: 1;
    }
`;

const toolCss = css`
    font-size: 8px;
    font-weight: 400;
    opacity: 0.7;
`;

const reasonCss = css`
    margin: 4px 0;
    font-size: 10px;
    color: #fff;
    text-transform: none;
`;

const planCss = css`
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(120px, 0.9fr);
    gap: 8px;
    align-items: start;
    margin-top: 4px;
`;

const hintCss = css`
    margin-top: 2px;
    font-size: 7.5px;
    letter-spacing: 0.08em;
    opacity: 0.7;
`;

const actionsCss = css`
    display: flex;
    gap: 6px;
    margin-top: 7px;
`;

const decisionCss = css`
    flex: 1;
    padding: 5px;
    font: inherit;
    font-weight: 700;
    letter-spacing: 0.14em;
    cursor: pointer;
`;

const approveCss = css`
    border: 1px solid var(--hud-amber);
    background: var(--hud-amber);
    color: #1a0f00;

    &:hover {
        filter: brightness(1.15);
    }
`;

const denyCss = css`
    border: 1px solid var(--hud-dim);
    background: transparent;
    color: var(--hud);

    &:hover {
        background: var(--hud-faint);
    }
`;

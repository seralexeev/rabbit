import { css, cx } from '@emotion/css';
import React from 'react';

import { type PanelId, useHud } from './HudContext.ts';

export const HudColumns: React.FC<{ panels: Record<PanelId, React.ReactNode> }> = ({ panels }) => {
    const { layout } = useHud();
    return (
        <>
            <div className={cx(columnCss, leftCss)}>
                {layout.left.map((id) => (
                    <React.Fragment key={id}>{panels[id]}</React.Fragment>
                ))}
            </div>
            <div className={cx(columnCss, rightCss)}>
                {layout.right.map((id) => (
                    <React.Fragment key={id}>{panels[id]}</React.Fragment>
                ))}
            </div>
        </>
    );
};

const columnCss = css`
    position: absolute;
    top: 46px;
    bottom: 12px;
    width: var(--hud-column);
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow-y: auto;
    overscroll-behavior: contain;
    pointer-events: none;
    scrollbar-width: none;

    &::-webkit-scrollbar {
        display: none;
    }
`;

const leftCss = css`
    left: 12px;
`;

const rightCss = css`
    right: 12px;
`;

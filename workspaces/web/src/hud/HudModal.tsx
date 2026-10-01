import { css, cx } from '@emotion/css';
import React from 'react';
import { createPortal } from 'react-dom';

import { frameCss } from './frame.ts';

type HudModalProps = { code: string; title: string; onClose: () => void; children: React.ReactNode };

export const HudModal: React.FC<HudModalProps> = ({ code, title, onClose, children }) => {
    React.useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            onClose();
        };
        window.addEventListener('keydown', onKeyDown, true);
        return () => window.removeEventListener('keydown', onKeyDown, true);
    }, [onClose]);

    return createPortal(
        <div
            className={backdropCss}
            onPointerDown={(event) => {
                if (event.target === event.currentTarget) onClose();
            }}>
            <section className={cx(frameCss, dialogCss)} role='dialog' aria-label={title}>
                <header className={headerCss}>
                    <span className={codeCss}>{code}</span>
                    <span className={titleCss}>{title}</span>
                    <button className={closeCss} onClick={onClose} title='Close (Esc)'>
                        ✕ CLOSE
                    </button>
                </header>
                <div className={ticksCss} />
                <div className={bodyCss}>{children}</div>
            </section>
        </div>,
        document.body,
    );
};

const backdropCss = css`
    position: fixed;
    inset: 0;
    z-index: 2000;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(2, 8, 12, 0.55);
    backdrop-filter: blur(4px);
`;

const dialogCss = css`
    width: 80vw;
    height: 80vh;
    display: flex;
    flex-direction: column;
    padding: 10px 14px 12px;
    font-size: 11px;
    line-height: 16px;
`;

const headerCss = css`
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
`;

const codeCss = css`
    padding: 0 6px;
    font-size: 10px;
    line-height: 14px;
    color: #031016;
    background: var(--hud);
    clip-path: polygon(4px 0, calc(100% - 4px) 0, 100% 50%, calc(100% - 4px) 100%, 4px 100%, 0 50%);
    text-shadow: none;
`;

const titleCss = css`
    flex: 1;
    font-weight: 600;
    letter-spacing: 0.12em;
`;

const closeCss = css`
    padding: 2px 8px;
    border: 1px solid var(--hud-dim);
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 10px;
    letter-spacing: 0.1em;
    cursor: pointer;

    &:hover {
        background: var(--hud-faint);
    }
`;

const ticksCss = css`
    height: 4px;
    margin: 6px 0 10px;
    border-top: 1px solid var(--hud-faint);
    background: repeating-linear-gradient(90deg, var(--hud-faint) 0 1px, transparent 1px 6px);
`;

const bodyCss = css`
    flex: 1;
    min-height: 0;
    overflow: auto;
`;

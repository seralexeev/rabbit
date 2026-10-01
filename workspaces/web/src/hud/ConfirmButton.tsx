import { css, cx } from '@emotion/css';
import React from 'react';

const CONFIRM_MS = 4000;

type ConfirmButtonProps = {
    label: string;
    confirmLabel: string;
    title: string;
    disabled?: boolean;
    onConfirm: () => void;
};

export const ConfirmButton: React.FC<ConfirmButtonProps> = ({ label, confirmLabel, title, disabled, onConfirm }) => {
    const [confirming, setConfirming] = React.useState(false);

    React.useEffect(() => {
        if (!confirming) return;
        const timer = window.setTimeout(() => setConfirming(false), CONFIRM_MS);
        return () => window.clearTimeout(timer);
    }, [confirming]);

    const click = () => {
        if (!confirming) {
            setConfirming(true);
            return;
        }
        setConfirming(false);
        onConfirm();
    };

    return (
        <button className={cx(actionButtonCss, confirming && confirmCss)} onClick={click} disabled={disabled} title={title}>
            {confirming ? confirmLabel : label}
        </button>
    );
};

export const actionsCss = css`
    display: flex;
    gap: 6px;
    margin-top: 6px;
`;

export const actionButtonCss = css`
    flex: 1;
    padding: 2px 4px;
    border: 1px solid var(--hud-dim);
    background: transparent;
    color: var(--hud);
    font: inherit;
    letter-spacing: inherit;
    cursor: pointer;

    &:hover:not(:disabled) {
        background: var(--hud-faint);
    }

    &:disabled {
        opacity: 0.35;
        cursor: not-allowed;
    }
`;

const confirmCss = css`
    border-color: var(--hud-amber);
    background: var(--hud-amber);
    color: #1a0f00;
    text-shadow: none;

    &:hover:not(:disabled) {
        background: var(--hud-amber);
    }
`;

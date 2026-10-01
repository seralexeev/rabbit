import { css } from '@emotion/css';
import React from 'react';

export type Tone = 'normal' | 'ok' | 'warn' | 'alert';

type CardProps = { title: string; meta?: React.ReactNode; children: React.ReactNode; outputId?: string | undefined };

export const Card: React.FC<CardProps> = ({ title, meta, children, outputId }) => (
    <section className={cardCss} data-output-id={outputId}>
        <header className={cardHeaderCss}>
            <span>{title}</span>
            {meta != null && <span className={metaCss}>{meta}</span>}
        </header>
        {children}
    </section>
);

export const Kpi: React.FC<{ label: string; value: string; sub?: string | undefined; tone?: Tone }> = ({
    label,
    value,
    sub,
    tone = 'normal',
}) => (
    <div className={kpiCss} data-tone={tone}>
        <span>{label}</span>
        <b>{value}</b>
        {sub != null && <small>{sub}</small>}
    </div>
);

type DisclosureProps = { label: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode };

export const Disclosure: React.FC<DisclosureProps> = ({ label, defaultOpen = false, children }) => {
    const [open, setOpen] = React.useState(defaultOpen);
    return (
        <div>
            <button className={toggleCss} aria-expanded={open} onClick={() => setOpen((value) => !value)}>
                <span className={caretCss}>{open ? '▾' : '▸'}</span>
                {label}
            </button>
            {open && children}
        </div>
    );
};

export const cardCss = css`
    position: relative;
    margin: 8px 0 0;
    padding: 6px 8px 7px;
    background: #03090d;
    box-shadow: inset 0 0 0 1px rgba(98, 232, 255, 0.1);
    transition: box-shadow 0.3s;

    &[data-flash='true'] {
        box-shadow:
            inset 0 0 0 1px var(--hud),
            0 0 14px var(--hud-glow);
    }
`;

const cardHeaderCss = css`
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 5px;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;

    & > span:first-child {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        opacity: 0.75;
    }
`;

const metaCss = css`
    font-weight: 400;
    font-size: 8px;
    letter-spacing: 0.08em;
    opacity: 0.5;
    white-space: nowrap;
`;

const kpiCss = css`
    display: flex;
    flex-direction: column;
    padding: 2px 0 2px 7px;
    border-left: 2px solid var(--tone);
    line-height: 13px;

    --tone: var(--hud-dim);

    &[data-tone='ok'] {
        --tone: var(--hud-good);
    }

    &[data-tone='warn'] {
        --tone: var(--hud-amber);
    }

    &[data-tone='alert'] {
        --tone: var(--hud-alert);
    }

    & > span {
        font-size: 7.5px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        opacity: 0.55;
    }

    & > b {
        color: #fff;
        font-size: 12px;
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    &[data-tone='warn'] > b,
    &[data-tone='alert'] > b {
        color: var(--tone);
    }

    & > small {
        font-size: 8.5px;
        opacity: 0.6;
        white-space: nowrap;
    }
`;

const toggleCss = css`
    display: flex;
    align-items: center;
    gap: 5px;
    width: 100%;
    padding: 2px 0;
    border: none;
    background: none;
    color: var(--hud);
    font: inherit;
    font-size: 9px;
    letter-spacing: 0.08em;
    text-align: left;
    text-transform: uppercase;
    cursor: pointer;
    opacity: 0.7;

    &:hover {
        opacity: 1;
    }
`;

const caretCss = css`
    width: 8px;
`;

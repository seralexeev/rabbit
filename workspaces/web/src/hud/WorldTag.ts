import { css, cx } from '@emotion/css';

import { type Tone, toneCss } from './fields.ts';

const tagCss = css`
    position: absolute;
    left: 0;
    top: 0;
    width: 0;
    height: 0;
    will-change: transform;
    pointer-events: none;

    &[data-visible='false'] {
        display: none;
    }

    &::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        width: 26px;
        height: 1px;
        background: currentColor;
        opacity: 0.8;
        transform: rotate(-45deg);
        transform-origin: 0 0;
    }
`;

const labelCss = cx(
    toneCss,
    css`
        position: absolute;
        left: 18px;
        bottom: 18px;
        padding: 1px 6px;
        border-left: 2px solid currentColor;
        background: var(--hud-bg);
        color: var(--hud);
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.08em;
        white-space: nowrap;
        text-shadow: 0 0 6px var(--hud-glow);
    `,
);

const emphasisCss = css`
    font-size: 12px;
    padding: 2px 8px;
`;

export type WorldTag = {
    update: (x: number, y: number, visible: boolean, text: string, tone: Tone) => void;
    dispose: () => void;
};

export const createWorldTag = (parent: HTMLElement, emphasized: boolean): WorldTag => {
    const tag = document.createElement('div');
    tag.className = tagCss;
    tag.dataset['visible'] = 'false';
    const label = document.createElement('div');
    label.className = emphasized ? cx(labelCss, emphasisCss) : labelCss;
    tag.appendChild(label);
    parent.appendChild(tag);

    let shown = false;
    let px = Number.NaN;
    let py = Number.NaN;
    let lastText = '';
    let lastTone: Tone = 'normal';

    return {
        update: (x, y, visible, text, tone) => {
            if (visible !== shown) {
                shown = visible;
                tag.dataset['visible'] = String(visible);
            }
            if (!visible) return;
            const nx = Math.round(x);
            const ny = Math.round(y);
            if (nx !== px || ny !== py) {
                px = nx;
                py = ny;
                tag.style.transform = `translate3d(${nx}px, ${ny}px, 0)`;
            }
            if (text !== lastText) {
                lastText = text;
                label.textContent = text;
            }
            if (tone !== lastTone) {
                lastTone = tone;
                label.dataset['tone'] = tone;
                tag.style.color = tone === 'alert' ? 'var(--hud-alert)' : tone === 'warn' ? 'var(--hud-amber)' : '';
            }
        },
        dispose: () => tag.remove(),
    };
};

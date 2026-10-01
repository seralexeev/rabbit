import { css } from '@emotion/css';

const corner = (x: string, y: string) =>
    `linear-gradient(var(--hud-dim), var(--hud-dim)) ${x} ${y} / 8px 1px no-repeat, linear-gradient(var(--hud-dim), var(--hud-dim)) ${x} ${y} / 1px 8px no-repeat`;

export const frameCss = css`
    padding: 6px 8px 7px;
    background:
        ${corner('left', 'top')}, ${corner('right', 'top')}, ${corner('left', 'bottom')}, ${corner('right', 'bottom')},
        linear-gradient(180deg, rgba(98, 232, 255, 0.07), rgba(98, 232, 255, 0) 40%), var(--hud-bg);
    box-shadow: inset 0 0 0 1px rgba(98, 232, 255, 0.06);
    color: var(--hud);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 10px;
    line-height: 14px;
    font-variant-numeric: tabular-nums;
    text-shadow: 0 0 6px var(--hud-glow);
`;

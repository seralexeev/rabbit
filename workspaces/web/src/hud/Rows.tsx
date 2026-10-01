import { css, cx } from '@emotion/css';
import React from 'react';

import { type FieldRefs, type RowSpec, labelCss, rowCss, valueCss } from './fields.ts';

const barCss = css`
    position: relative;
    height: 5px;
    background: repeating-linear-gradient(90deg, rgba(98, 232, 255, 0.14) 0 3px, transparent 3px 4px);
`;

const centerBarCss = cx(
    barCss,
    css`
        &::after {
            content: '';
            position: absolute;
            left: 50%;
            top: -2px;
            width: 1px;
            height: 9px;
            background: var(--hud-dim);
        }
    `,
);

const fillCss = css`
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(90deg, var(--hud) 0 3px, transparent 3px 4px);
    clip-path: inset(0 100% 0 0);
`;

export const Rows: React.FC<{ rows: readonly RowSpec[]; fields: React.RefObject<FieldRefs> }> = ({ rows, fields }) => (
    <>
        {rows.map((row, i) => (
            <div key={row.label} className={rowCss}>
                <span className={labelCss}>{row.label}</span>
                {row.bar == null ? (
                    <span />
                ) : (
                    <div className={row.bar === 'center' ? centerBarCss : barCss}>
                        <div
                            className={fillCss}
                            data-kind={row.bar}
                            ref={(el) => {
                                fields.current.bars[i] = el;
                            }}
                        />
                    </div>
                )}
                <span
                    className={valueCss}
                    ref={(el) => {
                        fields.current.values[i] = el;
                    }}>
                    —
                </span>
            </div>
        ))}
    </>
);

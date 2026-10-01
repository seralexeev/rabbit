import { css, cx } from '@emotion/css';
import React from 'react';

type Segment = {
    id: string;
    label: string;
};

type SegmentedControlProps = {
    segments: readonly Segment[];
    value: string;
    onChange: (id: string) => void;
};

export const SegmentedControl: React.FC<SegmentedControlProps> = ({ segments, value, onChange }) => {
    return (
        <div
            className={css`
                display: inline-flex;
                border: 1px solid var(--color-primary);
            `}>
            {segments.map((segment) => (
                <button
                    key={segment.id}
                    onClick={() => onChange(segment.id)}
                    className={cx(
                        css`
                            padding: 4px 10px;
                            font-size: 10px;
                            font-family: inherit;
                            text-transform: uppercase;
                            letter-spacing: 0.05em;
                            cursor: pointer;
                            border: none;
                            border-right: 1px solid var(--color-primary);

                            &:last-child {
                                border-right: none;
                            }
                        `,
                        segment.id === value
                            ? css`
                                  background: var(--color-primary);
                                  color: var(--color-black);
                              `
                            : css`
                                  background: transparent;
                                  color: var(--color-primary);

                                  &:hover {
                                      background: var(--hud-faint);
                                  }
                              `,
                    )}>
                    {segment.label}
                </button>
            ))}
        </div>
    );
};

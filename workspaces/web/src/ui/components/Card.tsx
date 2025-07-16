import { css, cx } from '@emotion/css';
import React from 'react';

type CardProps = {
    header?: React.ReactNode;
    children?: React.ReactNode;
    className?: string;
};

export const Card: React.FC<CardProps> = ({ header, children, className }) => {
    return (
        <div
            className={cx(
                className,
                css`
                    display: flex;
                    width: 100%;
                    height: 100%;
                    flex-direction: column;
                    background-color: var(--color-black);
                    border: 1px solid var(--color-primary);
                `,
            )}>
            {header != null && (
                <div
                    className={css`
                        padding: 8px;
                        display: flex;
                        align-items: center;
                        overflow-x: auto;
                        overflow-y: hidden;
                        flex-shrink: 0;
                    `}>
                    {header}
                </div>
            )}
            {children != null && (
                <div
                    className={css`
                        width: 100%;
                        height: 100%;
                        flex: 1;
                        border-top: 1px solid var(--color-primary);
                        overflow: hidden;
                    `}>
                    {children}
                </div>
            )}
        </div>
    );
};

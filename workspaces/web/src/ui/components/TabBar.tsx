import { css, cx } from '@emotion/css';
import React from 'react';

type Tab = {
    id: string;
    label: string;
};

type TabBarProps = {
    tabs: readonly Tab[];
    activeTab: string;
    onTabChange: (id: string) => void;
};

export const TabBar: React.FC<TabBarProps> = ({ tabs, activeTab, onTabChange }) => {
    return (
        <div
            className={css`
                display: flex;
                border-bottom: 1px solid var(--color-primary);
            `}>
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    onClick={() => onTabChange(tab.id)}
                    className={cx(
                        css`
                            flex: 1;
                            padding: 8px 12px;
                            font-size: 11px;
                            font-family: inherit;
                            text-transform: uppercase;
                            letter-spacing: 0.05em;
                            cursor: pointer;
                            border: none;
                            border-right: 1px solid var(--color-primary);
                            transition: background-color 100ms;

                            &:last-child {
                                border-right: none;
                            }
                        `,
                        tab.id === activeTab
                            ? css`
                                  background: var(--color-primary);
                                  color: var(--color-black);
                              `
                            : css`
                                  background: transparent;
                                  color: var(--color-primary);

                                  &:hover {
                                      background: rgba(0, 255, 65, 0.1);
                                  }
                              `,
                    )}>
                    {tab.label}
                </button>
            ))}
        </div>
    );
};

import { css, cx } from '@emotion/css';
import React from 'react';

import { ui } from '../ui/index.ts';
import { ConfigTab } from './tabs/ConfigTab.tsx';
import { ControlsTab } from './tabs/ControlsTab.tsx';
import { NodesTab } from './tabs/NodesTab.tsx';
import { SysTab } from './tabs/SysTab.tsx';

const SIDEBAR_TABS = [
    { id: 'controls', label: 'CTRL' },
    { id: 'sys', label: 'SYS' },
    { id: 'nodes', label: 'NODES' },
    { id: 'config', label: 'CONF' },
] as const;

const SIDEBAR_WIDTH = 360;
const COLLAPSED_WIDTH = 28;

export const Sidebar: React.FC = () => {
    const [activeTab, setActiveTab] = React.useState('controls');
    const [collapsed, setCollapsed] = React.useState(false);

    React.useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
                return;
            }

            if (e.key === '[') {
                setCollapsed((prev) => !prev);
            }
        };

        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, []);

    return (
        <div
            className={css`
                display: flex;
                height: 100%;
                flex-shrink: 0;
                transition: width 200ms ease;
                border: 1px solid var(--color-primary);
                background: var(--color-black);
            `}
            style={{ width: collapsed ? COLLAPSED_WIDTH : SIDEBAR_WIDTH }}>
            <button
                onClick={() => setCollapsed((prev) => !prev)}
                className={css`
                    width: ${COLLAPSED_WIDTH}px;
                    flex-shrink: 0;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: transparent;
                    color: var(--color-primary);
                    border: none;
                    border-right: 1px solid var(--color-primary);
                    cursor: pointer;
                    font-size: 12px;
                    font-family: inherit;
                    padding: 0;

                    &:hover {
                        background: rgba(0, 255, 65, 0.1);
                    }
                `}>
                <span
                    className={cx(
                        css`
                            writing-mode: vertical-lr;
                            letter-spacing: 0.1em;
                            font-size: 10px;
                        `,
                        collapsed &&
                            css`
                                transform: rotate(180deg);
                            `,
                    )}>
                    {collapsed ? 'OPEN' : 'CLOSE'}
                </span>
            </button>

            {!collapsed && (
                <div
                    className={css`
                        flex: 1;
                        display: flex;
                        flex-direction: column;
                        overflow: hidden;
                        min-width: 0;
                    `}>
                    <ui.TabBar tabs={SIDEBAR_TABS} activeTab={activeTab} onTabChange={setActiveTab} />
                    <div
                        className={css`
                            flex: 1;
                            overflow-y: auto;
                            overflow-x: hidden;
                        `}>
                        {activeTab === 'controls' && <ControlsTab />}
                        {activeTab === 'sys' && <SysTab />}
                        {activeTab === 'nodes' && <NodesTab />}
                        {activeTab === 'config' && <ConfigTab />}
                    </div>
                </div>
            )}
        </div>
    );
};

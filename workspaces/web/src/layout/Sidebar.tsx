import { css, cx } from '@emotion/css';
import React from 'react';

import { useWatchKV } from '../app/NatsProvider.tsx';
import { CameraSettings } from '../camera/CameraSettings.tsx';
import { ui } from '../ui/index.ts';

const SIDEBAR_TABS = [
    { id: 'camera', label: 'CAMERA' },
    { id: 'config', label: 'CONF' },
] as const;

const SIDEBAR_WIDTH = 360;
const COLLAPSED_WIDTH = 28;

export const Sidebar: React.FC = () => {
    const [activeTab, setActiveTab] = React.useState('camera');
    const [sidebarState, setSidebarState] = useWatchKV({
        key: 'rabbit.ui.sidebar',
        parse: (data) => data.json() as { visible: boolean },
    });

    const collapsed = !(sidebarState?.visible ?? false);
    const toggle = () => setSidebarState({ visible: collapsed });

    React.useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
                return;
            }

            if (e.key === '[') {
                toggle();
            }
        };

        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [collapsed]);

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
                onClick={toggle}
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
                        {activeTab === 'camera' && <CameraSettings />}
                    </div>
                </div>
            )}
        </div>
    );
};

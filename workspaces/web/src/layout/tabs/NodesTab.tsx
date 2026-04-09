import { css } from '@emotion/css';
import React from 'react';

import { NodeHealthBar } from '../../telemetry/NodeHealthBar.tsx';

export const NodesTab: React.FC = () => {
    return (
        <div
            className={css`
                padding: 8px;
            `}>
            <NodeHealthBar />
        </div>
    );
};

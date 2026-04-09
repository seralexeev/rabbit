import { css } from '@emotion/css';
import React from 'react';

export const ConfigTab: React.FC = () => {
    return (
        <div
            className={css`
                padding: 16px;
                opacity: 0.5;
            `}>
            NO CONFIGURATION AVAILABLE
        </div>
    );
};

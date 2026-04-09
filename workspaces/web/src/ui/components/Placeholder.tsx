import { css } from '@emotion/css';
import React from 'react';

type PlaceholderProps = {
    label: string;
};

export const Placeholder: React.FC<PlaceholderProps> = ({ label }) => {
    return (
        <div
            className={css`
                padding: 16px;
                text-align: center;
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                opacity: 0.4;
            `}>
            {label}
        </div>
    );
};

import { css } from '@emotion/css';
import React from 'react';

import spinner from '../../assets/spinner.gif';

type SpinnerProps = {
    width?: React.CSSProperties['width'];
    height?: React.CSSProperties['height'];
    children?: React.ReactNode;
};

export const Spinner: React.FC<SpinnerProps> = ({ children, height = 32, width = 64 }) => {
    return (
        <div
            className={css`
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 4px;
            `}>
            <div style={{ width, height }}>
                <div
                    className={css`
                        background-image: url(${spinner});
                        background-repeat: no-repeat;
                        background-position: center;
                        background-size: contain;
                        width: 100%;
                        height: 100%;
                    `}
                />
            </div>
            {children}
        </div>
    );
};

export const SplashSpinner: React.FC<SpinnerProps> = React.memo(({ children, height, width }) => {
    return (
        <div
            className={css`
                width: 100%;
                height: 100%;
                display: flex;
                justify-content: center;
                align-items: center;
            `}>
            <div
                className={css`
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                `}>
                <Spinner children={children} height={height} width={width} />
            </div>
        </div>
    );
});

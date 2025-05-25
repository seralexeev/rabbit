import { css } from '@emotion/css';
import React from 'react';

import { useWebSocket } from '../realtime/WebSocketProvider.tsx';
import { type DualSenseState, type StickState, useGamepad } from './GamepadProvider.tsx';

export const GamepadController: React.FC = () => {
    const ws = useWebSocket();
    const { gamepad, subscribe } = useGamepad();
    const [state, setState] = React.useState<DualSenseState | null>(null);

    React.useEffect(() => {
        return subscribe((state) => {
            setState(state);
            ws.send({ type: 'joy/STATE' });
        });
    }, [gamepad]);

    return (
        <div
            className={css`
                width: 100%;
                height: 500px;
                border: 1px solid var(--color);
                display: flex;
                flex-direction: column;
            `}>
            <div>Gamepad Controller</div>
            <p>Selected Gamepad: {gamepad ? gamepad.id : 'None'}</p>
            {state && (
                <div>
                    <div
                        className={css`
                            display: flex;
                            gap: 16px;
                        `}>
                        <Stick stick={state.sticks.left} />
                        <Stick stick={state.sticks.right} />
                    </div>
                </div>
            )}
        </div>
    );
};

const Stick: React.FC<{ stick: StickState }> = ({ stick }) => {
    return (
        <div
            className={css`
                width: 128px;
                height: 128px;
                border-radius: 50%;
                border: 2px solid var(--color);
                position: relative;
                --dot-size: 8px;
            `}>
            <div
                className={css`
                    width: 0px;
                    height: 100%;
                    border: 1px dashed var(--color);
                    position: absolute;
                    left: 50%;
                    transform-origin: center;
                    opacity: 0.3;
                `}
            />
            <div
                className={css`
                    height: 0px;
                    width: 100%;
                    border: 1px dashed var(--color);
                    position: absolute;
                    top: 50%;
                    transform-origin: center;
                    opacity: 0.3;
                `}
            />

            <div
                className={css`
                    width: var(--dot-size);
                    height: var(--dot-size);
                    border-radius: 50%;
                    background-color: var(--color);
                    position: absolute;
                `}
                style={{
                    left: `calc(${(stick.x * 60) / 2 + 50}% - calc(var(--dot-size) / 2))`,
                    top: `calc(${(stick.y * 60) / 2 + 50}% - calc(var(--dot-size) / 2))`,
                }}
            />
            <div
                className={css`
                    font-size: 12px;
                    text-align: right;
                    position: absolute;
                    top: calc(50% - 34px);
                    left: calc(50% - 46px);
                    width: 40px;
                `}>
                <div children={stick.x.toFixed(2)} />
                <div children={stick.y.toFixed(2)} />
            </div>
        </div>
    );
};

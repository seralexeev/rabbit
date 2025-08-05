import { css } from '@emotion/css';
import React from 'react';

import { useNats } from '../app/NatsProvider.tsx';
import { type DualSenseState, type StickState, useGamepad } from './GamepadProvider.tsx';

export const GamepadController: React.FC = () => {
    const { nc } = useNats();
    const { gamepad, subscribe } = useGamepad();
    const [state, setState] = React.useState<DualSenseState | null>(null);

    React.useEffect(() => {
        return subscribe((state) => {
            setState(state);
            nc.publish('rabbit.cmd.joy', JSON.stringify(state));
            nc.flush();
        });
    }, [gamepad, nc]);

    return (
        <div
            className={css`
                width: 100%;
                height: 500px;
                border: 1px solid var(--color-primary);
                display: flex;
                flex-direction: column;
            `}>
            <div>Gamepad Controller</div>
            <p>Selected Gamepad: {gamepad ? gamepad.id : 'None'}</p>
            <p>
                {/* <span
                    style={{
                        color: connected ? 'green' : 'red',
                        marginLeft: '8px',
                        fontWeight: 'bold',
                    }}>
                    {connected ? '🟢 Connected' : '🔴 Disconnected'}
                </span>
                {connectionState && (
                    <span style={{ marginLeft: '8px', fontSize: '12px', opacity: 0.7 }}>({connectionState})</span>
                )} */}
            </p>
            {state && (
                <div>
                    <div
                        className={css`
                            display: flex;
                            gap: 16px;
                            width: 100%;
                            justify-content: center;
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
                border: 2px solid var(--color-primary);
                position: relative;
                --dot-size: 8px;
            `}>
            <div
                className={css`
                    width: 0px;
                    height: 100%;
                    border: 1px dashed var(--color-primary);
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
                    border: 1px dashed var(--color-primary);
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
                    background-color: var(--color-primary);
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

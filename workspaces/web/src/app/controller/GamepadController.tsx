import React from 'react';

import { type DualSenseState, useGamepad } from './GamepadProvider.tsx';

export const GamepadController: React.FC = () => {
    const { gamepad, gamepads, setGamepad, subscribe } = useGamepad();
    const [state, setState] = React.useState<DualSenseState | null>(null);

    React.useEffect(() => {
        const unsubscribe = subscribe(setState);

        return unsubscribe;
    }, [gamepad]);

    return (
        <div>
            <h1>Gamepad Controller</h1>
            <p>Connected Gamepads: {gamepads.length}</p>
            <p>Selected Gamepad: {gamepad ? gamepad.id : 'None'}</p>
            <div>
                <h2>Available Gamepads</h2>
                <ul>
                    {gamepads.map((gp, index) => (
                        <li key={index} onClick={() => setGamepad(gp)}>
                            {gp.id}
                        </li>
                    ))}
                </ul>
            </div>

            <pre>?{JSON.stringify(state, null, 2)}</pre>
        </div>
    );
};

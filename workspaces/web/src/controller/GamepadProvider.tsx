import { createNanoEvents } from 'nanoevents';
import React from 'react';

import { useEvent } from '../hooks.ts';

type GamepadContext = {
    gamepads: Gamepad[];
    gamepad: Gamepad | null;
    setGamepad: (id: string | null) => void;
    subscribe: (fn: (state: DualSenseState) => void) => () => void;
};

const GamepadContext = React.createContext<GamepadContext | null>(null);

export const GamepadProvider: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
    const cycleRef = React.useRef(0);
    const now = React.useRef(Date.now());
    const intervalRef = React.useRef<number | null>(null);
    const [gamepads, setGamepads] = React.useState<Gamepad[]>([]);
    const [current, setCurrent] = React.useState<string | null>(null);
    const [emitter] = React.useState(() => createNanoEvents<{ onUpdate: (state: DualSenseState) => void }>());
    const gamepad = gamepads.find((x) => x.id === current) ?? null;

    const updateGamepads = useEvent(() => {
        const allGamepads = navigator.getGamepads().filter((x) => x != null);
        setGamepads(allGamepads);
        if (current == null) {
            setCurrent(allGamepads[0]?.id ?? null);
        }
    });

    const subscribe = useEvent((fn: (state: DualSenseState) => void) => emitter.on('onUpdate', fn));

    React.useEffect(() => {
        const abortController = new AbortController();

        window.addEventListener('gamepadconnected', updateGamepads, { signal: abortController.signal });
        window.addEventListener('gamepaddisconnected', updateGamepads, { signal: abortController.signal });

        return () => abortController.abort();
    }, []);

    const updateLoop = useEvent(() => {
        cycleRef.current += 1;

        const gamepad = navigator.getGamepads().find((x) => x?.id === current);
        if (!gamepad) {
            return;
        }

        const state = mapDualSenseState(gamepad);
        try {
            emitter.emit('onUpdate', state);
        } catch (e) {
            console.error('🔴 Error emitting gamepad update:', e);
        }

        if (cycleRef.current % 30 === 0) {
            const total_diff = Date.now() - now.current;
            const fps = Math.round((cycleRef.current / total_diff) * 1000);

            console.log(`FPS: ${fps} `);
        }
    });

    React.useEffect(() => {
        if (intervalRef.current !== null) {
            clearInterval(intervalRef.current);
        }

        intervalRef.current = window.setInterval(updateLoop, 1000 / 30);

        return () => {
            if (intervalRef.current != null) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
            }
        };
    }, [current]);

    return (
        <GamepadContext.Provider value={{ gamepads, gamepad, setGamepad: setCurrent, subscribe }}>
            {children}
        </GamepadContext.Provider>
    );
};

export const useGamepad = () => {
    const context = React.useContext(GamepadContext);
    if (!context) {
        throw new Error('useGamepad must be used within a GamepadProvider');
    }

    return context;
};

const round = (num: number) => Math.round(num * 100) / 100;

const mapDualSenseState = (gamepad: Gamepad): DualSenseState => {
    const b = gamepad.buttons;
    const a = gamepad.axes;

    return {
        buttons: {
            up: { pressed: b[12]?.pressed ?? false, value: round(b[12]?.value ?? 0) },
            down: { pressed: b[13]?.pressed ?? false, value: round(b[13]?.value ?? 0) },
            left: { pressed: b[14]?.pressed ?? false, value: round(b[14]?.value ?? 0) },
            right: { pressed: b[15]?.pressed ?? false, value: round(b[15]?.value ?? 0) },
            cross: { pressed: b[0]?.pressed ?? false, value: round(b[0]?.value ?? 0) },
            circle: { pressed: b[1]?.pressed ?? false, value: round(b[1]?.value ?? 0) },
            square: { pressed: b[2]?.pressed ?? false, value: round(b[2]?.value ?? 0) },
            triangle: { pressed: b[3]?.pressed ?? false, value: round(b[3]?.value ?? 0) },
            l1: { pressed: b[4]?.pressed ?? false, value: round(b[4]?.value ?? 0) },
            r1: { pressed: b[5]?.pressed ?? false, value: round(b[5]?.value ?? 0) },
            l2: { pressed: b[6]?.pressed ?? false, value: round(b[6]?.value ?? 0) },
            r2: { pressed: b[7]?.pressed ?? false, value: round(b[7]?.value ?? 0) },
            share: { pressed: b[8]?.pressed ?? false, value: round(b[8]?.value ?? 0) },
            options: { pressed: b[9]?.pressed ?? false, value: round(b[9]?.value ?? 0) },
            l3: { pressed: b[10]?.pressed ?? false, value: round(b[10]?.value ?? 0) },
            r3: { pressed: b[11]?.pressed ?? false, value: round(b[11]?.value ?? 0) },
        },
        sticks: {
            left: {
                x: round(a[0] ?? 0),
                y: round(a[1] ?? 0),
            },
            right: {
                x: round(a[2] ?? 0),
                y: round(a[3] ?? 0),
            },
        },
    };
};

type ButtonState = {
    pressed: boolean;
    value: number;
};

export type StickState = {
    x: number;
    y: number;
};

export type DualSenseState = {
    buttons: {
        cross: ButtonState;
        circle: ButtonState;
        square: ButtonState;
        triangle: ButtonState;
        l1: ButtonState;
        r1: ButtonState;
        l2: ButtonState;
        r2: ButtonState;
        l3: ButtonState;
        r3: ButtonState;
        share: ButtonState;
        options: ButtonState;
        up: ButtonState;
        down: ButtonState;
        left: ButtonState;
        right: ButtonState;
    };
    sticks: {
        left: StickState;
        right: StickState;
    };
};

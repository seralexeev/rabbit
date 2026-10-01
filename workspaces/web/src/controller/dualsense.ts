const DEADZONE = 0.08;

const BUTTONS = {
    cross: 0,
    circle: 1,
    square: 2,
    triangle: 3,
    l1: 4,
    r1: 5,
    l2: 6,
    r2: 7,
    share: 8,
    options: 9,
    l3: 10,
    r3: 11,
    up: 12,
    down: 13,
    left: 14,
    right: 15,
} as const;

type ButtonName = keyof typeof BUTTONS;
type ButtonState = { pressed: boolean; value: number };
type StickState = { x: number; y: number };

export type DualSenseState = {
    buttons: Record<ButtonName, ButtonState>;
    sticks: { left: StickState; right: StickState };
};

const BUTTON_NAMES = Object.keys(BUTTONS) as ButtonName[];

const round = (value: number) => Math.round(value * 1000) / 1000;

const deadzone = (value: number) => {
    const magnitude = Math.abs(value);
    return magnitude < DEADZONE ? 0 : round((Math.sign(value) * (magnitude - DEADZONE)) / (1 - DEADZONE));
};

export const NEUTRAL_STATE: DualSenseState = {
    buttons: Object.fromEntries(BUTTON_NAMES.map((name) => [name, { pressed: false, value: 0 }])) as DualSenseState['buttons'],
    sticks: { left: { x: 0, y: 0 }, right: { x: 0, y: 0 } },
};

export const readDualSense = (gamepad: Gamepad): DualSenseState => {
    const axis = (index: number) => deadzone(gamepad.axes[index] ?? 0);
    const buttons = {} as DualSenseState['buttons'];
    for (const name of BUTTON_NAMES) {
        const button = gamepad.buttons[BUTTONS[name]];
        const value = deadzone(button?.value ?? 0);
        buttons[name] = { pressed: (button?.pressed ?? false) && value > 0, value };
    }
    return {
        buttons,
        sticks: { left: { x: axis(0), y: axis(1) }, right: { x: axis(2), y: axis(3) } },
    };
};

export const isNeutral = (state: DualSenseState) =>
    state.sticks.left.x === 0 &&
    state.sticks.left.y === 0 &&
    state.sticks.right.x === 0 &&
    state.sticks.right.y === 0 &&
    BUTTON_NAMES.every((name) => !state.buttons[name].pressed && state.buttons[name].value === 0);

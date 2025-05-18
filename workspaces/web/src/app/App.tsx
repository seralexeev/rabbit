import React from 'react';

import { GamepadController } from './controller/GamepadController.tsx';
import { GamepadProvider } from './controller/GamepadProvider.tsx';

export const App: React.FC = () => {
    return (
        <GamepadProvider>
            <GamepadController />
        </GamepadProvider>
    );
};

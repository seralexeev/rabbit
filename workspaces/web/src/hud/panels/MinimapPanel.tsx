import React from 'react';

import { HudPanel } from '../HudPanel.tsx';
import { Minimap } from '../Minimap.tsx';

type MinimapPanelProps = {
    armed: boolean;
    onGoal: (point: { x: number; z: number }, append: boolean) => void;
};

export const MinimapPanel: React.FC<MinimapPanelProps> = ({ armed, onGoal }) => (
    <HudPanel
        id='minimap'
        code='MP'
        title='MAP // FLOOR PLAN'
        source='pose'
        detail={<Minimap fill armed={armed} onGoal={onGoal} />}>
        <Minimap armed={armed} onGoal={onGoal} />
    </HudPanel>
);

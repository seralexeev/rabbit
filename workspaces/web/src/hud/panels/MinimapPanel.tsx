import React from 'react';

import { useNats } from '../../app/NatsProvider.tsx';
import { L } from '../../log.ts';
import { ConfirmButton, actionsCss } from '../ConfirmButton.tsx';
import { useHud } from '../HudContext.ts';
import { HudPanel } from '../HudPanel.tsx';
import { Minimap } from '../Minimap.tsx';

const RESET_SUBJECT = 'rabbit.map.reset';

type MinimapPanelProps = {
    armed: boolean;
    onGoal: (point: { x: number; z: number }, append: boolean) => void;
};

export const MinimapPanel: React.FC<MinimapPanelProps> = ({ armed, onGoal }) => {
    const { connected } = useHud();
    const { nc, link } = useNats();

    const reset = () => {
        if (link() !== 'connected') {
            L.warn('Map not reset: NATS is not connected');
            return;
        }
        nc.publish(RESET_SUBJECT, JSON.stringify({ source: 'hud' }));
        L.info('Map reset requested');
    };

    return (
        <HudPanel
            id='minimap'
            code='MP'
            title='MAP // FLOOR PLAN'
            source='pose'
            detail={<Minimap fill armed={armed} onGoal={onGoal} />}>
            <Minimap armed={armed} onGoal={onGoal} />
            <div className={actionsCss}>
                <ConfirmButton
                    label='⟲ RESET MAP'
                    confirmLabel='▲ CONFIRM RESET'
                    onConfirm={reset}
                    disabled={!connected}
                    title='Archive the saved room map and start an empty one (the camera restarts for about 10 s)'
                />
            </div>
        </HudPanel>
    );
};

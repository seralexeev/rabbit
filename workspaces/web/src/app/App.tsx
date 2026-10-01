import React from 'react';

import { PerceptionView } from '../perception/PerceptionView.tsx';
import { NatsProvider } from './NatsProvider.tsx';

export const App: React.FC = () => (
    <NatsProvider>
        <PerceptionView />
    </NatsProvider>
);

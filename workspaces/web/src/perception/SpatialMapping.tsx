import React from 'react';

import { useWatchObj } from '../app/NatsProvider.tsx';

type SpatialMappingProps = {};

export const SpatialMapping: React.FC<SpatialMappingProps> = ({}) => {
    const [value] = useWatchObj({
        name: 'rabbit.zed.mesh',
    });

    console.log('SpatialMapping value:', value);

    return <div></div>;
};

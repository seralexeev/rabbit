import * as uuid from 'uuid';

import type { Branded } from './types.ts';

export const uuidRegex = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
export const v7 = () => uuid.v7() as UUID;

export const isUUID = (uuid: unknown) => {
    return typeof uuid === 'string' && uuidRegex.test(uuid);
};

export const suffix = () => {
    return uuid.v4().split('-').pop();
};

export type UUID = Branded<string, 'UUID'>;
export const parse = (uuid: string): UUID => {
    if (!isUUID(uuid)) {
        throw new Error('Invalid UUID');
    }

    return uuid as UUID;
};

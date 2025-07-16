import type { Msg } from '@nats-io/nats-core';
import type z from 'zod';

export const parseNatsHeaders = <T>(schema: z.ZodType<T>, msg: Msg) => {
    return schema.parse(Object.fromEntries(msg.headers?.keys().map((key) => [key, msg.headers?.get(key)]) ?? []));
};

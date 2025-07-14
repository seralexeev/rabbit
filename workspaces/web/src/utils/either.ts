import { z } from 'zod';

export const ResultSchema = <T extends z.ZodTypeAny>(schema: T) => {
    return z.union([schema, z.object({ __error: z.literal(true), cause: schema })]);
};

export type ResultError<T = unknown> = { __error: true; cause?: T };
export type Result<T, E = unknown> = T | ResultError<E>;
export type AsyncResult<T = unknown, E = unknown> = Promise<Result<T, E>>;

export const error = <E = unknown>(cause: E): ResultError<E> => ({ __error: true, cause });

export const ifSuccess = <T, E, R>(map: (res: T) => R) => {
    return (res: Result<T, E>) => {
        if (isSuccess(res)) {
            return map(res);
        }

        return res;
    };
};

export const ifError = <T, P, R>(map: (res: ResultError<P>) => R) => {
    return (res: Result<T, P>) => {
        if (isError(res)) {
            return map(res);
        }

        return res;
    };
};

export const isError = <T, P>(result: Result<T, P>): result is ResultError<P> => {
    return typeof result === 'object' && result !== null && '__error' in result && result.__error === true;
};

export const isSuccess = <T, P>(result: Result<T, P>): result is T => !isError(result);

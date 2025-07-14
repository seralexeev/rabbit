export const delay = (ms: number) => {
    return new Promise<void>((resolve) => setTimeout(resolve, ms));
};

export const settled = <T>(promise: PromiseSettledResult<T>): promise is PromiseFulfilledResult<T> => {
    return promise.status === 'fulfilled';
};

export const unsettled = <T>(promise: PromiseSettledResult<T>): promise is PromiseRejectedResult => {
    return promise.status === 'rejected';
};

export const isPromise = <T>(value: unknown): value is Promise<T> => {
    return typeof value === 'object' && value !== null && 'then' in value && typeof (value as any).then === 'function';
};

export const run = async <T>(fn: () => Promise<T>) => fn();

export function all<T extends readonly unknown[] | []>(values: T): Promise<{ -readonly [P in keyof T]: Awaited<T[P]> }>;
export function all<T extends Record<string, unknown>>(values: T): Promise<{ [P in keyof T]: Awaited<T[P]> }>;
export async function all(values: Array<Promise<unknown>> | Record<string, Promise<unknown>>): Promise<unknown> {
    if (Array.isArray(values)) {
        return Promise.all(values);
    }

    return Promise.all(Object.entries(values).map(async ([key, promise]) => [key, await promise])).then(Object.fromEntries);
}

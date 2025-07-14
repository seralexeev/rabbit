import { type AsyncResult, type Result, error } from './either.ts';
import { UnreachableError } from './error.ts';
import { isPromise } from './promise.ts';

export function trycatch<T, R = null>(fn: () => Promise<T>, default_value?: R): Promise<T>;
export function trycatch<T, R = null>(fn: () => T, default_value?: R): T | R;
export function trycatch(fn: () => unknown, default_value?: unknown) {
    try {
        const result = fn();
        return isPromise(result) ? result.catch(() => default_value ?? null) : result;
    } catch {
        return default_value ?? null;
    }
}

export function noexept<T>(fn: () => Promise<T>): AsyncResult<T>;
export function noexept<T>(fn: () => T): Result<T>;
export function noexept(fn: () => unknown) {
    try {
        const result = fn();
        return isPromise(result) ? result.catch(error) : result;
    } catch (cause) {
        return error(cause);
    }
}

export function never<T>(check: never, defaultValue: T): T;
export function never(message?: string): never; // TODO: this is incorrect
export function never(...args: unknown[]) {
    if (args.length > 1) {
        return args[1];
    }

    throw new UnreachableError(null as never, args[0] as string | undefined);
}

export const existsBy = <T>(key: keyof T) => {
    return (obj?: T | undefined | null): obj is T & { [K in keyof T]: Exclude<T[K], null | undefined> } => {
        return obj != null && obj[key] != null;
    };
};

export const notnull = <T>(value: T | null | undefined, message = 'Not null assertion failed'): T => {
    if (value == null) {
        throw new Error(message);
    }

    return value;
};

export function invariant(condition: unknown, message = 'Invariant failed'): asserts condition {
    if (!condition) {
        throw new Error(message);
    }
}

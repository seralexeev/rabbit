import React from 'react';

export const useEvent = <T extends (...args: any[]) => any>(fn?: T) => {
    const ref = React.useRef(fn);

    React.useInsertionEffect(() => {
        ref.current = fn;
    });

    return React.useCallback((...args: any[]) => ref.current?.(...args), []) as T;
};

export const readLocal = <T>(key: string, parse: (raw: unknown) => T, fallback: T): T => {
    try {
        const raw = localStorage.getItem(key);
        return raw == null ? fallback : parse(JSON.parse(raw));
    } catch {
        return fallback;
    }
};

export const writeLocal = (key: string, value: unknown) => {
    try {
        if (value == null) localStorage.removeItem(key);
        else localStorage.setItem(key, JSON.stringify(value));
        return true;
    } catch {
        return false;
    }
};

export const useLocalState = <T>(key: string, parse: (raw: unknown) => T, fallback: T) => {
    const [value, setValue] = React.useState(() => readLocal(key, parse, fallback));
    const update = (fn: (prev: T) => T) =>
        setValue((prev) => {
            const next = fn(prev);
            writeLocal(key, next);
            return next;
        });
    return [value, update] as const;
};

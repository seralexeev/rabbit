import React from 'react';

export const useLiveRef = <T>(value: T) => {
    const ref = React.useRef(value);
    ref.current = value;
    return ref;
};

export const useEvent = <T extends (...args: any[]) => any>(fn?: T) => {
    const ref = useLiveRef(fn);

    return React.useRef((...args: any[]) => ref.current?.(...args)).current as T;
};

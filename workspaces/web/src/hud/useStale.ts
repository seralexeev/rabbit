import React from 'react';

export const useStale = (value: unknown, timeoutMs: number) => {
    const [live, setLive] = React.useState(false);

    React.useEffect(() => {
        if (value == null) return;
        setLive(true);
        const timer = window.setTimeout(() => setLive(false), timeoutMs);
        return () => window.clearTimeout(timer);
    }, [value, timeoutMs]);

    return live;
};

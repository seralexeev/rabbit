const write = (method: 'info' | 'warn' | 'error', level: string) => (message: string, data?: unknown) => {
    if (data === undefined) console[method](`[${level}] ${message}`);
    else console[method](`[${level}] ${message}`, data);
};

export const L = {
    info: write('info', 'INF'),
    warn: write('warn', 'WRN'),
    error: write('error', 'ERR'),
};

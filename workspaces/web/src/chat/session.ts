const BASE_URL = import.meta.env['VITE_CHAT_URL'] ?? 'http://127.0.0.1:18080';
const TOKEN_HEADER = 'x-forge-token';

export const CHAT_URL = `${BASE_URL}/api/chat`;
export const HEALTH_URL = `${BASE_URL}/api/health`;

let token: Promise<string> | null = null;

const sessionToken = () => {
    token ??= fetch(`${BASE_URL}/api/session`)
        .then(async (response) => {
            if (!response.ok) throw new Error(`Chat session request failed (${response.status})`);
            const body = (await response.json()) as { token?: string };
            if (body.token == null) throw new Error('Chat session response has no token');
            return body.token;
        })
        .catch((error: unknown) => {
            token = null;
            throw error;
        });
    return token;
};

const send = async (input: RequestInfo | URL, init: RequestInit | undefined) => {
    const headers = new Headers(init?.headers);
    headers.set(TOKEN_HEADER, await sessionToken());
    return fetch(input, { ...init, headers });
};

export const chatFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await send(input, init);
    if (response.status !== 401) return response;
    token = null;
    return send(input, init);
};

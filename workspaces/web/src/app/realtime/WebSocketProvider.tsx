import React from 'react';
import { z } from 'zod/v4';

const WebSocketContext = React.createContext<WebSocketWrapper | null>(null);

export const useWebSocket = () => {
    const ws = React.useContext(WebSocketContext);
    if (ws == null) {
        throw new Error('useWebSocket must be used within a WebSocketProvider');
    }

    return ws;
};

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [ws] = React.useState(() => {
        return new WebSocketWrapper('ws://localhost:3000?role=browser');
    });

    React.useEffect(() => {
        ws.connect();
        return () => ws.disconnect();
    }, [ws]);

    return <WebSocketContext.Provider value={ws}>{children}</WebSocketContext.Provider>;
};

class WebSocketWrapper {
    private url;
    private ws: WebSocket | null = null;
    private reconnect = true;
    private listeners: Array<{
        schema: z.ZodType;
        listener: (data: unknown) => void;
    }> = [];

    public constructor(url: string) {
        this.url = url;
    }

    public connect = () => {
        if (this.ws != null) {
            return;
        }

        const ws = new WebSocket(this.url);
        this.reconnect = true;

        ws.onopen = () => this.onOpen(ws);
        ws.onmessage = (e) => this.onMessage(ws, e);
        ws.onclose = (e) => this.onClose(ws, e);
        ws.onerror = (e) => this.onError(ws, e);

        this.ws = ws;
    };

    public disconnect = () => {
        this.reconnect = false;
        this.ws?.close();
        this.ws = null;
    };

    public send = (message: object) => {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        }
    };

    public subscribe = <T extends z.ZodType>(schema: T, listener: (data: z.infer<T>) => void) => {
        const item = { schema, listener };
        this.listeners.push(item as never);

        return () => {
            this.listeners = this.listeners.filter((x) => x !== item);
        };
    };

    private onOpen = (ws: WebSocket) => {
        if (this.ws !== ws) {
            return;
        }

        console.log('🟢 WebSocket connected');
    };

    private onClose = (ws: WebSocket, e: CloseEvent) => {
        if (this.ws !== ws) {
            return;
        }

        console.log('🟡 Socket closed', e.code, e.reason);

        if (this.reconnect) {
            setTimeout(this.connect, 1000);
        }
        this.ws = null;
    };

    private onMessage = async (ws: WebSocket, e: MessageEvent) => {
        console.log('🔵 Message received', { type: typeof e.data });

        if (this.ws !== ws) {
            return;
        }

        if (typeof e.data !== 'string') {
            console.error('🔴 Received non-string message:', e.data);
            return;
        }

        try {
            const data = JSON.parse(e.data);
            for (const { schema, listener } of this.listeners) {
                const parsed = schema.safeParse(data);
                if (parsed.success) {
                    listener(parsed.data);
                }
            }
        } catch (error) {
            console.error('🔴 Error parsing WebSocket message', {
                error,
                message: e.data,
            });
        }
    };

    private onError = (ws: WebSocket, e: Event) => {
        if (this.ws !== ws) {
            return;
        }

        console.error('🔴 WebSocket error', e);
        ws.close();
    };
}

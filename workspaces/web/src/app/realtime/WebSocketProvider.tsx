import React from 'react';

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
        return new WebSocketWrapper('ws://localhost:3005/realtime');
    });

    React.useEffect(ws.connect, [ws]);

    return <WebSocketContext.Provider value={ws} children={children} />;
};

class WebSocketWrapper {
    private url;
    private ws: WebSocket | null = null;
    private reconnect = true;

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
        ws.onmessage = (e: MessageEvent) => this.onMessage(ws, e);
        ws.onclose = (e: CloseEvent) => this.onClose(ws, e);
        ws.onerror = (e: Event) => this.onError(ws, e);

        this.ws = ws;
    };

    public disconnect = () => {
        this.reconnect = false;

        if (this.ws !== null) {
            this.ws.close();
            this.ws = null;
        }
    };

    public send = (data: { type: string; payload?: unknown }) => {
        if (this.ws != null) {
            this.ws.send(JSON.stringify(data));
        }
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

        console.log('🔴 Socket is closed', e.code, e.reason);
        if (this.reconnect) {
            setTimeout(this.connect, 1000);
        }

        this.ws = null;
    };

    private onMessage = (ws: WebSocket, e: MessageEvent) => {
        if (this.ws !== ws) {
            return;
        }

        console.log('🔵 Received:', e.data);
    };

    private onError = (ws: WebSocket, e: Event) => {
        if (this.ws !== ws) {
            return;
        }

        console.error('🔴 Socket encountered error: ', e);
        ws.close();
    };
}

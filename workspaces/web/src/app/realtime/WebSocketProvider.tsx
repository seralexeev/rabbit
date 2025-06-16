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
    private listeners: ((data: any) => void)[] = [];

    constructor(url: string) {
        this.url = url;
    }

    connect = () => {
        if (this.ws != null) return;

        const ws = new WebSocket(this.url);
        this.reconnect = true;

        ws.onopen = () => this.onOpen(ws);
        ws.onmessage = (e) => this.onMessage(ws, e);
        ws.onclose = (e) => this.onClose(ws, e);
        ws.onerror = (e) => this.onError(ws, e);

        this.ws = ws;
    };

    disconnect = () => {
        this.reconnect = false;
        this.ws?.close();
        this.ws = null;
    };

    send = (message: object) => {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        }
    };

    subscribe = (listener: (data: any) => void) => {
        this.listeners.push(listener);
        return () => this.unsubscribe(listener);
    };

    unsubscribe = (listener: (data: any) => void) => {
        this.listeners = this.listeners.filter((l) => l !== listener);
    };

    private onOpen = (ws: WebSocket) => {
        if (this.ws !== ws) {
            return;
        }

        console.log('🟢 WebSocket connected');
        
        // Notify listeners that WebSocket is connected
        this.listeners.forEach((listener) => listener({ type: 'ws_connected' }));
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
        if (this.ws !== ws) {
            return;
        }

        try {
            let messageData: string;
            
            // Handle different data types
            if (e.data instanceof Blob) {
                messageData = await e.data.text();
            } else if (typeof e.data === 'string') {
                messageData = e.data;
            } else {
                messageData = String(e.data);
            }

            const data = JSON.parse(messageData);
            console.log('🔵 Message received:', data);
            this.listeners.forEach((listener) => listener(data));
        } catch (error) {
            console.error('🔴 Error parsing WebSocket message:', error);
            console.error('🔴 Raw message data:', e.data);
        }
    };

    private onError = (ws: WebSocket, e: Event) => {
        if (this.ws !== ws) {
            return;
        }

        console.error('🔴 WebSocket error:', e);
        ws.close();
    };
}

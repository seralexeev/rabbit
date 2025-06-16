import express from 'express';
import { WebSocketServer } from 'ws';

const app = express();
const port = 3000;

const server = app.listen(port, () => {
    console.log(`🟢 HTTP server running on http://localhost:${port}`);
});

const wss = new WebSocketServer({ server });
console.log(`🟢 WebSocket server running on ws://localhost:${port}`);

wss.on('connection', (ws) => {
    console.log('🟢 New client connected');

    ws.on('message', (data) => {
        try {
            const message = JSON.parse(data.toString());
            const messageType = message.type || 'unknown';
            console.log(`🔵 Broadcasting message type: ${messageType}`);

            for (const client of wss.clients) {
                if (client !== ws && client.readyState === client.OPEN) {
                    // Ensure we send as string, not buffer
                    client.send(data.toString());
                }
            }
        } catch (error) {
            console.error('🔴 Error parsing message:', error);
        }
    });

    ws.on('close', () => {
        console.log('🟡 Client disconnected');
    });

    ws.on('error', (error) => {
        console.error('🔴 WebSocket error:', error);
    });
});

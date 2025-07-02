import express from 'express';
import { WebSocketServer } from 'ws';

const app = express();
const port = 3000;

const server = app.listen(port, () => {
    console.log('HTTP server running', { url: `http://localhost:${port}` });
});

const wss = new WebSocketServer({ server });

wss.on('connection', (ws) => {
    console.log('New client connected');

    ws.on('message', (data, isBinary) => {
        const message_preview = isBinary ? '[Binary]' : data.toString();
        console.log('Broadcasting message preview', message_preview);

        for (const client of wss.clients) {
            if (client !== ws && client.readyState === client.OPEN) {
                client.send(data.toString());
            }
        }
    });

    ws.on('close', () => {
        console.log('Client disconnected');
    });

    ws.on('error', (error) => {
        console.error('WebSocket error', error);
    });
});

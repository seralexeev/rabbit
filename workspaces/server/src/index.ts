import express from 'express';
import { WebSocketServer } from 'ws';
import { z } from 'zod/v4';

const app = express();
const port = 3000;

const server = app.listen(port, () => {
    console.log('Server started', {
        http: `http://localhost:${port}`,
        ws: `ws://localhost:${port}/ws?role=<${Object.keys(Role.enum).join('|')}>`,
    });
});

const wss = new WebSocketServer({ server });

wss.on('connection', (ws, request) => {
    const role = Role.safeParse(new URL(request.url ?? '', 'http://localhost').searchParams.get('role'));
    if (!role.success) {
        console.error('Invalid role provided', request.url);
        ws.close(1008, 'Invalid role provided');
        return;
    }

    console.log('New client connected', {
        role: role.data,
    });

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

const Role = z.enum(['browser', 'robot']);

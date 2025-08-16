import React from 'react';
import z from 'zod';

import { useNats } from '../app/NatsProvider.tsx';
import { L } from '../terminal/LogProvider.tsx';
import { util } from '../utils/index.ts';

type Stats = {
    bytes: number;
    fps: number;
    width: number;
    height: number;
    type: string;
    throughput: number;
    frameSize: number;
    subject: string;
};

export const useCameraStream = ({ subject }: { subject: string }) => {
    const { nc } = useNats();
    const canvas = React.useRef<HTMLCanvasElement>(null);
    const [stats, setStats] = React.useState<Stats | null>(null);

    React.useEffect(() => {
        const img = new Image();

        let bytes = 0;
        let type = 'unknown';

        let tick = {
            now: Date.now(),
            frames: 0,
            bytes: 0,
        };

        const intervalId = setInterval(() => {
            const elapsed = Date.now() - tick.now;
            bytes += tick.bytes;

            setStats({
                bytes,
                fps: Math.round((tick.frames * 1000) / elapsed),
                throughput: tick.bytes / (elapsed / 1000),
                width: canvas.current?.width ?? 0,
                height: canvas.current?.height ?? 0,
                type,
                frameSize: tick.frames !== 0 ? tick.bytes / tick.frames : 0,
                subject,
            });

            tick = {
                now: Date.now(),
                frames: 0,
                bytes: 0,
            };
        }, 500);

        const subscription = nc.subscribe(subject, {
            callback: (_, msg) => {
                const ctx = canvas.current?.getContext('2d');
                if (canvas.current == null || ctx == null) {
                    return;
                }

                const headers = util.parseNatsHeaders(MessageHeader, msg);

                if (canvas.current.width !== headers.width || canvas.current.height !== headers.height) {
                    canvas.current.width = headers.width;
                    canvas.current.height = headers.height;
                }

                const blob = new Blob([msg.data], { type: headers.type });
                const url = URL.createObjectURL(blob);

                img.onload = () => {
                    ctx.drawImage(img, 0, 0);
                    URL.revokeObjectURL(url);
                };

                img.onerror = () => {
                    URL.revokeObjectURL(url);
                    console.error('Failed to load camera frame');
                };

                img.src = url;

                tick.frames += 1;
                tick.bytes += msg.data.length;
                type = headers.type;
            },
        });

        L.info('Subscribed to NATS', { subject });

        return () => {
            subscription.unsubscribe();
            clearInterval(intervalId);

            L.info('Unsubscribed from NATS', { subject });
        };
    }, [nc]);

    return { canvas, stats };
};

const MessageHeader = z.object({
    type: z.string(),
    width: z.coerce.number().int(),
    height: z.coerce.number().int(),
});

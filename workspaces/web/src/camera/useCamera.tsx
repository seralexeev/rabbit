import type { Msg } from '@nats-io/nats-core';
import React from 'react';
import z from 'zod';

import { useNats } from '../app/NatsProvider.tsx';
import { L } from '../log.ts';
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

        let pending: Msg | null = null;
        let decoding = false;

        const drawLatest = async () => {
            decoding = true;
            while (pending != null) {
                const msg = pending;
                pending = null;
                try {
                    type = await drawFrame(canvas, msg);
                } catch (e) {
                    console.error('Failed to decode camera frame', e);
                }
            }
            decoding = false;
        };

        const subscription = nc.subscribe(subject, {
            callback: (_, msg) => {
                tick.frames += 1;
                tick.bytes += msg.data.length;

                if (canvas.current == null) {
                    return;
                }

                pending = msg;
                if (!decoding) {
                    void drawLatest();
                }
            },
        });

        L.info('Subscribed to NATS', { subject });

        return () => {
            subscription.unsubscribe();
            clearInterval(intervalId);

            L.info('Unsubscribed from NATS', { subject });
        };
    }, [nc, subject]);

    return { canvas, stats };
};

const drawFrame = async (canvas: React.RefObject<HTMLCanvasElement | null>, msg: Msg) => {
    const { type } = util.parseNatsHeaders(MessageHeader, msg);
    const bitmap = await createImageBitmap(new Blob([msg.data as Uint8Array<ArrayBuffer>], { type }));

    try {
        const target = canvas.current;
        const ctx = target?.getContext('2d');
        if (target == null || ctx == null) {
            return type;
        }

        if (target.width !== bitmap.width || target.height !== bitmap.height) {
            target.width = bitmap.width;
            target.height = bitmap.height;
        }

        ctx.drawImage(bitmap, 0, 0);
        return type;
    } finally {
        bitmap.close();
    }
};

const MessageHeader = z.object({
    type: z.string(),
});

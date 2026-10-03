import type { Msg } from '@nats-io/nats-core';
import React from 'react';
import z from 'zod';

import { useNats } from '../app/NatsProvider.tsx';
import { L } from '../log.ts';
import type { DetectedObjects } from '../perception/Telemetry.ts';
import { util } from '../utils/index.ts';

const SIGNAL_TIMEOUT_MS = 1500;
const OBJECTS_TIMEOUT_MS = 1000;
const BOX_COLOR = '#3dff7a';
const MOVING_COLOR = '#ffb547';

type Source = { type: string; width: number; height: number };
type Overlay = { objects: DetectedObjects | null; receivedAt: number };

type Stats = {
    bytes: number;
    fps: number;
    width: number;
    height: number;
    type: string;
    throughput: number;
    frameSize: number;
    subject: string;
    live: boolean;
};

export const useCameraStream = ({ subject, objects }: { subject: string; objects?: string | undefined }) => {
    const { nc } = useNats();
    const canvas = React.useRef<HTMLCanvasElement>(null);
    const [stats, setStats] = React.useState<Stats | null>(null);

    React.useEffect(() => {
        let bytes = 0;
        const source: Source = { type: 'unknown', width: 0, height: 0 };
        const overlay: Overlay = { objects: null, receivedAt: -Infinity };

        let lastFrameAt = -Infinity;
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
                width: source.width,
                height: source.height,
                type: source.type,
                frameSize: tick.frames !== 0 ? tick.bytes / tick.frames : 0,
                subject,
                live: Date.now() - lastFrameAt < SIGNAL_TIMEOUT_MS,
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
                    await drawFrame(canvas, msg, source, overlay);
                } catch (e) {
                    console.error('Failed to decode camera frame', e);
                }
            }
            decoding = false;
        };

        const subscription = nc.subscribe(subject, {
            callback: (_, msg) => {
                lastFrameAt = Date.now();
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

        const objectsSubscription =
            objects == null
                ? null
                : nc.subscribe(objects, {
                      callback: (_, msg) => {
                          try {
                              overlay.objects = msg.json();
                              overlay.receivedAt = Date.now();
                          } catch {}
                      },
                  });

        L.info('Subscribed to NATS', { subject });

        return () => {
            subscription.unsubscribe();
            objectsSubscription?.unsubscribe();
            clearInterval(intervalId);

            L.info('Unsubscribed from NATS', { subject });
        };
    }, [nc, subject, objects]);

    return { canvas, stats };
};

const drawObjects = (ctx: CanvasRenderingContext2D, overlay: Overlay) => {
    if (overlay.objects == null || Date.now() - overlay.receivedAt > OBJECTS_TIMEOUT_MS) return;
    const { width, height } = ctx.canvas;
    const scale = Math.max(1, width / 640);
    ctx.lineWidth = 1.5 * scale;
    ctx.font = `600 ${Math.round(10 * scale)}px monospace`;
    ctx.textBaseline = 'bottom';
    for (const object of overlay.objects.objects) {
        const [x0, y0, x1, y1] = object.box;
        const color = object.moving ? MOVING_COLOR : BOX_COLOR;
        ctx.strokeStyle = color;
        ctx.strokeRect(x0 * width, y0 * height, (x1 - x0) * width, (y1 - y0) * height);
        const label = `${object.label.toUpperCase()} ${Math.round(object.confidence)}`;
        const textWidth = ctx.measureText(label).width + 6 * scale;
        const top = Math.max(y0 * height, 14 * scale);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect(x0 * width, top - 13 * scale, textWidth, 13 * scale);
        ctx.fillStyle = color;
        ctx.fillText(label, x0 * width + 3 * scale, top - scale);
    }
};

const drawFrame = async (canvas: React.RefObject<HTMLCanvasElement | null>, msg: Msg, source: Source, overlay: Overlay) => {
    const header = util.parseNatsHeaders(MessageHeader, msg);
    source.type = header.type;
    source.width = header.width ?? source.width;
    source.height = header.height ?? source.height;
    const target = canvas.current;
    const width = target == null ? 0 : Math.round(target.clientWidth * window.devicePixelRatio);
    if (target == null || width === 0) return;

    const blob = new Blob([msg.data as Uint8Array<ArrayBuffer>], { type: header.type });
    const bitmap = await (header.width != null && header.height != null && width < header.width
        ? createImageBitmap(blob, {
              resizeWidth: width,
              resizeHeight: Math.round((width * header.height) / header.width),
              resizeQuality: 'medium',
          })
        : createImageBitmap(blob));

    try {
        if (header.width == null || header.height == null) {
            source.width = bitmap.width;
            source.height = bitmap.height;
        }
        const ctx = target.getContext('2d');
        if (ctx == null) return;
        if (target.width !== bitmap.width || target.height !== bitmap.height) {
            target.width = bitmap.width;
            target.height = bitmap.height;
        }
        ctx.drawImage(bitmap, 0, 0);
        drawObjects(ctx, overlay);
    } finally {
        bitmap.close();
    }
};

const MessageHeader = z.object({
    type: z.string(),
    width: z.coerce.number().optional(),
    height: z.coerce.number().optional(),
});

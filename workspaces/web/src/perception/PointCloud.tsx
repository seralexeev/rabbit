import { css } from '@emotion/css';
import { inflate } from 'pako';
import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

import { useSubscribe } from '../app/NatsProvider.tsx';

export const PointCloud: React.FC = () => {
    const ref = React.useRef<HTMLCanvasElement | null>(null);
    const geometryRef = React.useRef<THREE.BufferGeometry | null>(null);
    const pointsRef = React.useRef<THREE.Points | null>(null);

    const updateGeometry = (positions: number[], colors: number[]) => {
        if (!geometryRef.current) return;
        geometryRef.current.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometryRef.current.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
        geometryRef.current.computeBoundingSphere();
    };

    React.useLayoutEffect(() => {
        if (!ref.current) return;

        const renderer = new THREE.WebGLRenderer({ canvas: ref.current, antialias: true });
        renderer.setSize(1200, 600);

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(75, 800 / 600, 0.1, 1000);
        camera.position.z = -5;

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.update();

        const geometry = new THREE.BufferGeometry();
        geometryRef.current = geometry;

        const material = new THREE.PointsMaterial({ size: 0.05, vertexColors: true });
        const points = new THREE.Points(geometry, material);
        pointsRef.current = points;
        scene.add(points);

        renderer.setAnimationLoop(() => {
            // points.rotation.y += 0.002;
            controls.update();
            renderer.render(scene, camera);
        });

        return () => {
            renderer.dispose();
        };
    }, []);

    useSubscribe('rabbit.camera.point_cloud', {
        callback: async (msg) => {
            try {
                const shapeStr = msg.headers?.get('shape') ?? '[0,0,0]';
                const [H, W, C] = JSON.parse(shapeStr); // [720,1280,4]
                const buf = inflate(new Uint8Array(msg.data)).buffer;
                const arr = new Float32Array(buf);

                const positions: number[] = [];
                const colors: number[] = [];

                const dv = new DataView(new ArrayBuffer(4));

                for (let i = 0; i < H; i++) {
                    for (let j = 0; j < W; j++) {
                        const idx = (i * W + j) * 4;
                        const rawX = arr[idx + 0];
                        const rawY = arr[idx + 1];
                        const rawZ = arr[idx + 2];

                        if (!Number.isFinite(rawX) || !Number.isFinite(rawY) || !Number.isFinite(rawZ)) continue;

                        const scale = 1.5; // от 1.2 до 3 — экспериментируй
                        const x = rawX * scale;
                        const y = rawY * scale;
                        const z = rawZ * scale;

                        positions.push(x, y, z);

                        const depth = Math.sqrt(rawX * rawX + rawY * rawY + rawZ * rawZ);
                        const t = Math.max(0, Math.min(1, (depth - 0.2) / (5.0 - 0.2)));

                        const r = (1 - t) * 255 + t * 0;
                        const g = (1 - t) * 0 + t * 100;
                        const b = (1 - t) * 0 + t * 0;

                        colors.push(r / 255, g / 255, b / 255);
                    }
                }

                updateGeometry(positions, colors);
            } catch (err) {
                console.error('Failed to decode point cloud', err);
            }
        },
    });

    return (
        <div
            className={css`
                width: 100%;
                height: 100%;
            `}>
            <canvas
                className={css`
                    width: 100%;
                `}
                ref={ref}
                width={1200}
                height={600}
            />
        </div>
    );
};

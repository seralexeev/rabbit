import { css } from '@emotion/css';
import React from 'react';
import * as THREE from 'three';
import z from 'zod';

import { useKVSubscribe } from '../app/NatsProvider.tsx';

export const PointCloud: React.FC = () => {
    const ref = React.useRef<HTMLCanvasElement | null>(null);
    const intrinsics = React.useRef<CameraIntrinsics | null>(null);
    const kv = useKVSubscribe();
    const [pose, setPose] = React.useState<Pose | null>(null);

    React.useLayoutEffect(() => {
        if (!ref.current) {
            return;
        }

        const { width, height } = ref.current.getBoundingClientRect();

        const renderer = new THREE.WebGLRenderer({
            canvas: ref.current,
            antialias: true,
        });

        const scene = new THREE.Scene();

        const grid = new THREE.GridHelper(25, 100, 0x00ff41, 0x00ff41);
        scene.add(grid);

        const light = new THREE.DirectionalLight(0xffffff, 1);
        light.position.set(10, 10, 10);
        scene.add(light);

        const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);

        let poseFrame = 0;
        const poseWatcher = kv('rabbit.zed.pose', (entry) => {
            const pose = Pose.parse(entry?.json());

            const [px, py, pz] = pose.translation;
            const [qx, qy, qz, qw] = pose.orientation;

            camera.position.set(px, py, pz);
            camera.quaternion.set(qx, qy, qz, qw).normalize();
            camera.updateMatrixWorld(true);

            if (poseFrame++ % 30 === 0) {
                setPose(pose);
            }
        });

        const cameraIntrinsicWatcher = kv('rabbit.zed.intrinsics', (entry) => {
            intrinsics.current = CameraIntrinsics.parse(entry?.json());

            const { fx, fy, cx, cy, width, height } = intrinsics.current;

            const near = 0.01;
            const far = 1000;

            const left = (-cx * near) / fx;
            const right = ((width - cx) * near) / fx;
            const top = (cy * near) / fy;
            const bottom = (-(height - cy) * near) / fy;

            camera.projectionMatrix.makePerspective(left, right, top, bottom, near, far);
            camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
        });

        renderer.setAnimationLoop(() => {
            renderer.render(scene, camera);
        });

        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                if (entry.target !== ref.current) {
                    continue;
                }

                const { width, height } = entry.contentRect;
                renderer.setSize(width, height);
                camera.aspect = width / height;
                camera.updateProjectionMatrix();
            }
        });
        observer.observe(ref.current);

        return () => {
            observer.disconnect();
            renderer.dispose();
            poseWatcher.unsubscribe();
            cameraIntrinsicWatcher.unsubscribe();
        };
    }, [ref.current]);

    return (
        <div
            className={css`
                width: 100% !important;
                height: 100% !important;
                position: relative;
            `}>
            <canvas
                ref={ref}
                className={css`
                    width: 100% !important;
                    height: 100% !important;
                `}
            />
            <div
                className={css`
                    position: absolute;
                    top: 8px;
                    left: 8px;
                `}>
                <div>ALTITUDE: {pose?.translation[1].toFixed(2)}m</div>
            </div>
        </div>
    );
};

type Pose = z.infer<typeof Pose>;
const Pose = z.object({
    translation: z.tuple([z.number(), z.number(), z.number()]),
    orientation: z.tuple([z.number(), z.number(), z.number(), z.number()]), // x,y,z,w
});

type CameraIntrinsics = z.infer<typeof CameraIntrinsics>;
const CameraIntrinsics = z.object({
    fx: z.number(),
    fy: z.number(),
    cx: z.number(),
    cy: z.number(),
    width: z.number(),
    height: z.number(),
});

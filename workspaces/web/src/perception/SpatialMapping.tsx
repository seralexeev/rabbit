import { css } from '@emotion/css';
import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import z from 'zod';

import { useObjectStoreSubscribe, useWatchKV } from '../app/NatsProvider.tsx';
import { useLiveRef } from '../hooks.ts';

export const SpatialMapping: React.FC = () => {
    const ref = React.useRef<HTMLCanvasElement | null>(null);
    const objectStoreSubscribe = useObjectStoreSubscribe();
    const [pose] = useWatchKV({
        key: 'rabbit.zed.pose',
        parse: (x) => Pose.parse(x.json()),
    });

    const posRef = useLiveRef(pose);

    React.useEffect(() => {
        const canvas = ref.current;
        if (canvas == null) {
            return;
        }

        const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
        renderer.setSize(1200, 600);
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x0f1012);

        const camera = new THREE.PerspectiveCamera(60, 1200 / 600, 0.1, 1000);
        camera.position.set(0.8, 1.6, 3.2);

        const controls = new OrbitControls(camera, canvas);
        controls.enableDamping = true;

        scene.add(new THREE.DirectionalLight(0xffffff, 1));

        const poseMarker = new THREE.AxesHelper(0.5);
        scene.add(poseMarker);

        renderer.setAnimationLoop(() => {
            controls.update();
            renderer.render(scene, camera);

            if (posRef.current) {
                poseMarker.position.set(...posRef.current.translation);
                poseMarker.quaternion.set(...posRef.current.orientation);
            }
        });

        let prev: THREE.Object3D | null = null;
        const unsubscribe = objectStoreSubscribe('rabbit.zed.mesh', async (res) => {
            if (res?.data == null) {
                return;
            }

            const mesh = await new Response(res.data)
                .arrayBuffer()
                .then((x) => new TextDecoder().decode(new Uint8Array(x)))
                .then((buffer) => new OBJLoader().parse(buffer));

            mesh.traverse((child) => {
                if ((child as THREE.Mesh).isMesh) {
                    (child as THREE.Mesh).material = new THREE.MeshBasicMaterial({
                        color: 0x00ff00,
                        wireframe: true,
                    });
                }
            });

            if (prev != null) {
                scene.remove(prev);
            }

            scene.add(mesh);
            prev = mesh;
        });

        return () => {
            unsubscribe();
            controls.dispose();
            renderer.dispose();
        };
    }, []);

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

const Pose = z.object({
    translation: z.tuple([z.number(), z.number(), z.number()]),
    orientation: z.tuple([z.number(), z.number(), z.number(), z.number()]),
});

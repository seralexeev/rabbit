import { css } from '@emotion/css';
import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';

import { useSubscribeObj } from '../app/NatsProvider.tsx';

export const SpatialMapping: React.FC = () => {
    const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
    const subscribe = useSubscribeObj();

    React.useEffect(() => {
        const canvas = canvasRef.current;
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

        renderer.setAnimationLoop(() => {
            controls.update();
            renderer.render(scene, camera);
        });

        let prev: THREE.Object3D | null = null;
        const unsubscribe = subscribe('rabbit.zed.mesh', async (res) => {
            if (res?.data == null) {
                return;
            }

            const mesh = await new Response(res.data)
                .arrayBuffer()
                .then((x) => new TextDecoder().decode(new Uint8Array(x)))
                .then((buffer) => new OBJLoader().parse(buffer));

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
        <canvas
            ref={canvasRef}
            className={css`
                width: 100%;
                height: 100%;
                display: block;
            `}
            width={1200}
            height={600}
        />
    );
};

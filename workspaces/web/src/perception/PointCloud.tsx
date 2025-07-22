import { css } from '@emotion/css';
import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

type PointCloudProps = {};

export const PointCloud: React.FC<PointCloudProps> = ({}) => {
    const ref = React.useRef<HTMLCanvasElement | null>(null);

    React.useLayoutEffect(() => {
        if (!ref.current) {
            return;
        }

        const renderer = new THREE.WebGLRenderer({
            canvas: ref.current,
            antialias: true,
        });

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
        camera.position.z = 5;

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.update();

        // === ТЕСТОВЫЕ ТОЧКИ ===
        const testPoints: [number, number, number, number][] = [
            [0, 0, 0, 0xff0000], // красная
            [1, 1, 0, 0x00ff00], // зелёная
            [-1, 1, 0, 0x0000ff], // синяя
            [0, -1, 1, 0xffff00], // жёлтая
        ];

        const positions: number[] = [];
        const colors: number[] = [];

        for (const [x, y, z, color] of testPoints) {
            positions.push(x, y, z);
            const colorObj = new THREE.Color(color);
            colors.push(colorObj.r, colorObj.g, colorObj.b);
        }

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
        geometry.computeBoundingSphere();

        const material = new THREE.PointsMaterial({ size: 0.1, vertexColors: true });

        const pointsMesh = new THREE.Points(geometry, material);
        scene.add(pointsMesh);

        // === АНИМАЦИЯ ===
        renderer.setAnimationLoop(() => {
            pointsMesh.rotation.y += 0.005;
            controls.update();
            renderer.render(scene, camera);
        });

        return () => {
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
                width={800}
                height={600}
            />
        </div>
    );
};

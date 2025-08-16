import { css } from '@emotion/css';
import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
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

        // Lighting
        scene.add(new THREE.DirectionalLight(0xffffff, 1));
        scene.add(new THREE.AmbientLight(0x404040, 0.4));

        // Pose marker
        const poseMarker = new THREE.AxesHelper(0.5);
        scene.add(poseMarker);

        // Voxel container
        const voxelGroup = new THREE.Group();
        scene.add(voxelGroup);

        // Instanced mesh for efficient voxel rendering
        const voxelGeometry = new THREE.BoxGeometry(1, 1, 1);
        const voxelMaterial = new THREE.MeshBasicMaterial({
            color: 0x00ff00,
            transparent: false,
            side: THREE.DoubleSide,
        });

        const instancedMesh = new THREE.InstancedMesh(
            voxelGeometry,
            voxelMaterial,
            10000, // Max voxels
        );
        instancedMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        instancedMesh.count = 0; // Start with 0 instances

        // Enable per-instance colors
        const colors = new Float32Array(10000 * 3);
        instancedMesh.instanceColor = new THREE.InstancedBufferAttribute(colors, 3);
        instancedMesh.instanceColor.setUsage(THREE.DynamicDrawUsage);

        voxelGroup.add(instancedMesh);

        // Update voxel data
        const updateVoxels = (voxelData: any) => {
            const voxels = voxelData.voxels || [];
            const voxelSize = voxelData.voxel_size || 0.05;

            console.log(`Received ${voxels.length} voxels with size ${voxelSize}`);
            console.log('Bounds:', voxelData.bounds);
            console.log('Sample voxels:', voxels.slice(0, 3));

            if (voxels.length === 0) {
                instancedMesh.count = 0;
                return;
            }

            // Update instance count
            instancedMesh.count = Math.min(voxels.length, 10000);

            // Create matrices and colors for each voxel
            const matrix = new THREE.Matrix4();
            const color = new THREE.Color();

            for (let i = 0; i < instancedMesh.count; i++) {
                const voxel = voxels[i];

                if (!voxel.position || voxel.position.length !== 3) {
                    console.error('Invalid voxel position:', voxel);
                    continue;
                }

                // Position and scale matrix
                matrix.makeScale(voxelSize, voxelSize, voxelSize);
                matrix.setPosition(voxel.position[0], voxel.position[1], voxel.position[2]);
                instancedMesh.setMatrixAt(i, matrix);

                // Color
                if (voxel.color && voxel.color.length === 3) {
                    color.setRGB(voxel.color[0] / 255, voxel.color[1] / 255, voxel.color[2] / 255);
                } else {
                    // Make all voxels green for debugging
                    color.setRGB(0, 1, 0); // Bright green
                }
                instancedMesh.setColorAt(i, color);
            }

            // Update buffers
            instancedMesh.instanceMatrix.needsUpdate = true;
            if (instancedMesh.instanceColor) {
                instancedMesh.instanceColor.needsUpdate = true;
            }

            console.log(`Successfully updated ${instancedMesh.count} voxel instances`);
        };

        // Animation loop
        renderer.setAnimationLoop(() => {
            controls.update();
            renderer.render(scene, camera);

            // Update pose marker
            if (posRef.current) {
                poseMarker.position.set(...posRef.current.translation);
                poseMarker.quaternion.set(...posRef.current.orientation);
            }
        });

        // Subscribe to voxel updates
        const unsubscribe = objectStoreSubscribe('rabbit.nvblox.voxels', async (res) => {
            if (res?.data == null) {
                console.log('No voxel data received');
                return;
            }

            try {
                const voxelData = await new Response(res.data)
                    .arrayBuffer()
                    .then((x) => new TextDecoder().decode(new Uint8Array(x)))
                    .then((text) => JSON.parse(text));

                console.log('Raw voxel data received:', {
                    num_voxels: voxelData.num_voxels,
                    voxel_size: voxelData.voxel_size,
                    bounds: voxelData.bounds,
                });

                updateVoxels(voxelData);
            } catch (error) {
                console.error('Error parsing voxel data:', error);
            }
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

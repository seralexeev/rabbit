import { css } from '@emotion/css';
import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import z from 'zod';

import { useObjectStoreSubscribe, useWatchKV } from '../app/NatsProvider.tsx';
import { useLiveRef } from '../hooks.ts';

const Pose = z.object({
    translation: z.tuple([z.number(), z.number(), z.number()]),
    orientation: z.tuple([z.number(), z.number(), z.number(), z.number()]), // x,y,z,w
});

const Voxel = z.object({
    position: z.tuple([z.number(), z.number(), z.number()]),
    color: z.tuple([z.number(), z.number(), z.number()]).optional(), // 0..255 sRGB
    tsdf: z.number().min(-1).max(1).optional(),
    weight: z.number().optional(),
});

const VoxelPayload = z.object({
    voxels: z.array(Voxel),
    voxel_size: z.number(),
    num_voxels: z.number(),
    bounds: z.object({
        min: z.tuple([z.number(), z.number(), z.number()]),
        max: z.tuple([z.number(), z.number(), z.number()]),
    }),
});
type VoxelPayloadT = z.infer<typeof VoxelPayload>;

// sRGB -> linear (0..1)
const s2l = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));

export const SpatialMapping: React.FC = () => {
    const canvasRef = React.useRef<HTMLCanvasElement | null>(null);

    const objectStoreSubscribe = useObjectStoreSubscribe();
    const [pose] = useWatchKV({
        key: 'rabbit.zed.pose',
        parse: (x) => Pose.parse(x.json()),
    });
    const posRef = useLiveRef(pose);

    React.useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        // ===== Renderer
        const renderer = new THREE.WebGLRenderer({
            canvas,
            antialias: true,
            alpha: false,
            powerPreference: 'high-performance',
        });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio ?? 1, 2));
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.physicallyCorrectLights = true;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.6;

        // ===== Scene
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x14171c);

        // ===== Camera + controls
        const camera = new THREE.PerspectiveCamera(60, 1, 0.02, 5000);
        camera.position.set(2, 2, 2);
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;

        // ===== Lights (достаточно яркие)
        scene.add(new THREE.AmbientLight(0xffffff, 0.6));
        const hemi = new THREE.HemisphereLight(0xffffff, 0x222222, 0.9);
        scene.add(hemi);
        const dir = new THREE.DirectionalLight(0xffffff, 1.8);
        dir.position.set(6, 10, 8);
        dir.castShadow = false;
        scene.add(dir);

        // ===== Axes: мировая + ось позы (ось позы всегда поверх)
        const worldAxes = new THREE.AxesHelper(0.6);
        scene.add(worldAxes);

        const poseAxes = new THREE.AxesHelper(0.35);
        poseAxes.renderOrder = 9999;
        poseAxes.traverse((o: any) => {
            if (o.material) {
                o.material.depthTest = false;
                o.material.depthWrite = false;
                o.material.transparent = true;
                o.material.opacity = 1.0;
                o.material.toneMapped = false;
            }
        });
        scene.add(poseAxes);

        // ===== Resize
        const resize = () => {
            const parent = canvas.parentElement ?? document.body;
            const w = parent.clientWidth || window.innerWidth;
            const h = parent.clientHeight || window.innerHeight;
            renderer.setSize(w, h, false);
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
        };
        resize();
        const ro = new ResizeObserver(resize);
        ro.observe(canvas.parentElement ?? document.body);

        const boxGeo = new THREE.BoxGeometry(1, 1, 1);
        {
            const vc = boxGeo.attributes.position.count;
            const white = new Float32Array(vc * 3);
            white.fill(1);
            boxGeo.setAttribute('color', new THREE.BufferAttribute(white, 3));
        }

        const boxMat = new THREE.MeshLambertMaterial({
            vertexColors: true,
            transparent: false,
            opacity: 0.9,
        });
        // const boxMat = new THREE.MeshStandardMaterial({
        //   vertexColors: true, roughness: 0.95, metalness: 0.0
        // });

        let voxelMesh: THREE.InstancedMesh | null = null;
        let capacity = 0;
        let lastBounds: { min: THREE.Vector3; max: THREE.Vector3 } | null = null;

        const ensureMesh = (cap: number) => {
            if (voxelMesh && capacity >= cap) return;
            if (voxelMesh) {
                scene.remove(voxelMesh);
                // @ts-ignore
                voxelMesh.instanceColor = null;
                voxelMesh.dispose?.();
            }
            capacity = Math.max(cap, 1);
            voxelMesh = new THREE.InstancedMesh(boxGeo, boxMat, capacity);
            voxelMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
            voxelMesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(capacity * 3), 3);
            scene.add(voxelMesh);
        };

        const matTmp = new THREE.Matrix4();
        const quatTmp = new THREE.Quaternion();
        const scaleTmp = new THREE.Vector3();
        const posTmp = new THREE.Vector3();

        const fitCameraToBounds = (min: THREE.Vector3, max: THREE.Vector3) => {
            const center = new THREE.Vector3().addVectors(min, max).multiplyScalar(0.5);
            const size = new THREE.Vector3().subVectors(max, min);
            const radius = Math.max(size.length() * 0.5, 0.5);
            camera.near = 0.02;
            camera.far = Math.max(5000, radius * 20);
            camera.updateProjectionMatrix();
            camera.position.copy(center).add(new THREE.Vector3(radius, radius * 0.6, radius));
            camera.lookAt(center);
            controls.target.copy(center);
            controls.update();
        };

        const updateVoxels = (payload: VoxelPayloadT) => {
            const { voxels, voxel_size, bounds } = payload;

            ensureMesh(voxels.length);
            if (!voxelMesh) return;

            voxelMesh.count = voxels.length;
            scaleTmp.set(voxel_size, voxel_size, voxel_size);

            const instCol = voxelMesh.instanceColor as THREE.InstancedBufferAttribute;
            const colArr = instCol.array as Float32Array;

            for (let i = 0; i < voxels.length; i++) {
                const v = voxels[i];

                // матрица
                const [x, y, z] = v.position;
                posTmp.set(x, y, z);
                matTmp.compose(posTmp, quatTmp, scaleTmp);
                voxelMesh.setMatrixAt(i, matTmp);

                // цвет (0..255 sRGB -> 0..1 linear)
                let r = 0.6,
                    g = 0.6,
                    b = 0.6;
                if (v.color) {
                    r = s2l(v.color[0] / 255);
                    g = s2l(v.color[1] / 255);
                    b = s2l(v.color[2] / 255);
                } else if (typeof v.tsdf === 'number') {
                    const t = Math.max(-1, Math.min(1, v.tsdf));
                    const sr = 0.5 + 0.5 * Math.max(0, t);
                    const sg = 0.5 * (1 - Math.abs(t));
                    const sb = 0.5 + 0.5 * Math.max(0, -t);
                    r = s2l(sr);
                    g = s2l(sg);
                    b = s2l(sb);
                }
                // Чуть поднимем яркость
                const k = 1.15;
                colArr[i * 3 + 0] = Math.min(1, r * k);
                colArr[i * 3 + 1] = Math.min(1, g * k);
                colArr[i * 3 + 2] = Math.min(1, b * k);
            }

            voxelMesh.instanceMatrix.needsUpdate = true;
            instCol.needsUpdate = true;

            // Камера по боксам
            const min = new THREE.Vector3(...bounds.min);
            const max = new THREE.Vector3(...bounds.max);
            const needsRefit =
                !lastBounds ||
                min.distanceTo(lastBounds.min) > voxel_size * 2 ||
                max.distanceTo(lastBounds.max) > voxel_size * 2;

            if (needsRefit) {
                fitCameraToBounds(min, max);
                lastBounds = { min, max };
            }
        };

        // ===== Render loop
        renderer.setAnimationLoop(() => {
            const p = posRef.current;
            if (p) {
                const [tx, ty, tz] = p.translation;
                const [qx, qy, qz, qw] = p.orientation;
                poseAxes.position.set(tx, ty, tz);
                poseAxes.quaternion.set(qx, qy, qz, qw);
            }
            controls.update();
            renderer.render(scene, camera);
        });

        // ===== Subscribe
        const unsubscribe = objectStoreSubscribe('rabbit.nvblox.voxels', async (res) => {
            if (!res?.data) return;
            const buffer = await new Response(res.data).arrayBuffer();
            const text = new TextDecoder().decode(new Uint8Array(buffer));
            const parsed = VoxelPayload.safeParse(JSON.parse(text));
            if (!parsed.success) {
                console.warn('Invalid voxel payload', parsed.error);
                return;
            }
            updateVoxels(parsed.data);
        });

        return () => {
            unsubscribe();
            renderer.setAnimationLoop(null);
            ro.disconnect();
            if (voxelMesh) {
                scene.remove(voxelMesh);
                // @ts-ignore
                voxelMesh.instanceColor = null;
                voxelMesh.dispose?.();
                voxelMesh = null;
            }
            boxGeo.dispose();
            (boxMat as THREE.Material).dispose();
            renderer.dispose();
        };
    }, [objectStoreSubscribe, posRef]);

    return (
        <canvas
            className={css`
                width: 100%;
                height: 100%;
                display: block;
            `}
            ref={canvasRef}
        />
    );
};

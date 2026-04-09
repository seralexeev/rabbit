import { css } from '@emotion/css';
import { decompress } from 'lz4js';
import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import z from 'zod';

import { useNats, useWatchKV } from '../app/NatsProvider.tsx';
import { L } from '../terminal/LogProvider.tsx';
import { ui } from '../ui/index.ts';

const VOXELS_DELTA_SUBJECT = 'rabbit.nvblox.voxels.delta';
const VOXELS_SNAPSHOT_SUBJECT = 'rabbit.nvblox.voxels.snapshot';
const VOXELS_REQUEST_SUBJECT = 'rabbit.nvblox.voxels.request';

const MSG_TYPE_DELTA = 0x01;
const MSG_TYPE_SNAPSHOT = 0x02;

const VOXEL_KIND_STRUCTURE = 2;

const BLOCK_SIDE_VOXELS = 8;
const MAX_INSTANCES = 262_144;
const EMPTY_PAYLOAD = new Uint8Array(0);
const NVBLOX_HEALTH_SUBJECT = 'rabbit.health.map_local';

type NvbloxHealth = {
    received_bundle_count: number;
    processed_bundle_count: number;
    replaced_bundle_count: number;
    lock_busy_skip_count: number;
    last_integration_duration_ms: number;
    last_esdf_update_duration_ms: number;
    esdf_update_count: number;
    num_blocks: number;
    allocated_bytes: number;
};

const VIEW_MODES = [
    { id: 'fpv', label: 'FPV' },
    { id: 'third', label: '3RD' },
    { id: 'top', label: 'TOP' },
] as const;

type ViewMode = (typeof VIEW_MODES)[number]['id'];

const VOXEL_KIND_COLORS = [
    new THREE.Color(0x00ff66),
    new THREE.Color(0xff5533),
    new THREE.Color(0x505064),
    new THREE.Color(0x282844),
];

type BlockIndex = [number, number, number];
type PackedBlock = {
    blockIndex: BlockIndex;
    voxels: Uint8Array;
};

type DeltaMessage = {
    msgType: typeof MSG_TYPE_DELTA;
    sequence: number;
    voxelSize: number;
    removeBlocks: BlockIndex[];
    upsertBlocks: PackedBlock[];
};

type SnapshotMessage = {
    msgType: typeof MSG_TYPE_SNAPSHOT;
    sequence: number;
    voxelSize: number;
    blocks: PackedBlock[];
};

type StoredBlock = {
    blockIndex: BlockIndex;
    voxels: Uint8Array;
    slots: number[];
};

class VoxelMap {
    private readonly blocks = new Map<string, StoredBlock>();
    private readonly freeSlots: number[] = [];
    private readonly capacity: number;
    private nextSlot = 0;
    private _voxelCount = 0;

    lastSeq = 0;

    constructor(capacity: number) {
        this.capacity = capacity;
    }

    get voxelCount() {
        return this._voxelCount;
    }

    get blockCount() {
        return this.blocks.size;
    }

    get activeCount() {
        return this.nextSlot;
    }

    clear() {
        this.blocks.clear();
        this.freeSlots.length = 0;
        this.nextSlot = 0;
        this._voxelCount = 0;
        this.lastSeq = 0;
    }

    applySnapshot(
        mesh: THREE.InstancedMesh,
        dummy: THREE.Object3D,
        snapshot: SnapshotMessage,
    ) {
        this.clear();
        mesh.count = 0;

        for (const block of snapshot.blocks) {
            this.upsertBlock(mesh, dummy, snapshot.voxelSize, block);
        }

        this.lastSeq = snapshot.sequence;
        mesh.count = this.activeCount;
    }

    applyDelta(
        mesh: THREE.InstancedMesh,
        dummy: THREE.Object3D,
        delta: DeltaMessage,
    ) {
        for (const blockIndex of delta.removeBlocks) {
            this.removeBlock(mesh, dummy, toBlockKey(blockIndex));
        }

        for (const block of delta.upsertBlocks) {
            this.upsertBlock(mesh, dummy, delta.voxelSize, block);
        }

        this.lastSeq = delta.sequence;
        mesh.count = this.activeCount;
    }

    private upsertBlock(
        mesh: THREE.InstancedMesh,
        dummy: THREE.Object3D,
        voxelSize: number,
        block: PackedBlock,
    ) {
        const key = toBlockKey(block.blockIndex);
        this.removeBlock(mesh, dummy, key);

        const slots: number[] = [];
        const [bx, by, bz] = block.blockIndex;
        const voxelBlockOffsetX = bx * BLOCK_SIDE_VOXELS;
        const voxelBlockOffsetY = by * BLOCK_SIDE_VOXELS;
        const voxelBlockOffsetZ = bz * BLOCK_SIDE_VOXELS;

        for (let offset = 0; offset < block.voxels.length; offset += 4) {
            const slot = this.allocSlot();
            const lx = block.voxels[offset]!;
            const ly = block.voxels[offset + 1]!;
            const lz = block.voxels[offset + 2]!;
            const kind = block.voxels[offset + 3]!;

            dummy.position.set(
                (voxelBlockOffsetX + lx + 0.5) * voxelSize,
                (voxelBlockOffsetY + ly + 0.5) * voxelSize,
                (voxelBlockOffsetZ + lz + 0.5) * voxelSize,
            );
            dummy.scale.setScalar(voxelSize);
            dummy.updateMatrix();

            mesh.setMatrixAt(slot, dummy.matrix);
            mesh.setColorAt(slot, VOXEL_KIND_COLORS[kind] ?? VOXEL_KIND_COLORS[VOXEL_KIND_STRUCTURE]!);
            slots.push(slot);
        }

        this.blocks.set(key, {
            blockIndex: block.blockIndex,
            voxels: block.voxels,
            slots,
        });
        this._voxelCount += slots.length;
    }

    private removeBlock(mesh: THREE.InstancedMesh, dummy: THREE.Object3D, key: string) {
        const existing = this.blocks.get(key);
        if (existing == null) {
            return;
        }

        for (const slot of existing.slots) {
            dummy.position.set(0, 0, 0);
            dummy.scale.setScalar(0);
            dummy.updateMatrix();
            mesh.setMatrixAt(slot, dummy.matrix);
            this.freeSlots.push(slot);
        }

        this._voxelCount -= existing.slots.length;
        this.blocks.delete(key);
    }

    private allocSlot() {
        const recycled = this.freeSlots.pop();
        if (recycled != null) {
            return recycled;
        }

        if (this.nextSlot >= this.capacity) {
            throw new Error(`Voxel capacity exceeded (${this.capacity.toLocaleString()} instances)`);
        }

        const slot = this.nextSlot;
        this.nextSlot += 1;
        return slot;
    }
}

function toBlockKey([x, y, z]: BlockIndex) {
    return `${x},${y},${z}`;
}

function parseBlockIndex(view: DataView, offset: number): { blockIndex: BlockIndex; offset: number } {
    const blockIndex: BlockIndex = [
        view.getInt32(offset, true),
        view.getInt32(offset + 4, true),
        view.getInt32(offset + 8, true),
    ];
    return { blockIndex, offset: offset + 12 };
}

function parsePackedBlock(data: Uint8Array, view: DataView, offset: number): { block: PackedBlock; offset: number } {
    const parsedIndex = parseBlockIndex(view, offset);
    offset = parsedIndex.offset;

    const numVoxels = view.getUint16(offset, true);
    offset += 2;

    const byteLength = numVoxels * 4;
    const voxels = data.slice(offset, offset + byteLength);
    offset += byteLength;

    return {
        block: {
            blockIndex: parsedIndex.blockIndex,
            voxels,
        },
        offset,
    };
}

function parseVoxelMessage(payload: Uint8Array): DeltaMessage | SnapshotMessage {
    const data = decompress(payload);
    const view = new DataView(data.buffer, data.byteOffset, data.byteLength);

    let offset = 0;
    const msgType = view.getUint8(offset);
    offset += 1;

    if (msgType === MSG_TYPE_DELTA) {
        const sequence = view.getUint32(offset, true);
        offset += 4;

        const voxelSize = view.getFloat32(offset, true);
        offset += 4;

        const numRemoveBlocks = view.getUint32(offset, true);
        offset += 4;

        const numUpsertBlocks = view.getUint32(offset, true);
        offset += 4;

        const removeBlocks: BlockIndex[] = [];
        for (let i = 0; i < numRemoveBlocks; i += 1) {
            const parsedIndex = parseBlockIndex(view, offset);
            removeBlocks.push(parsedIndex.blockIndex);
            offset = parsedIndex.offset;
        }

        const upsertBlocks: PackedBlock[] = [];
        for (let i = 0; i < numUpsertBlocks; i += 1) {
            const parsedBlock = parsePackedBlock(data, view, offset);
            upsertBlocks.push(parsedBlock.block);
            offset = parsedBlock.offset;
        }

        return {
            msgType,
            sequence,
            voxelSize,
            removeBlocks,
            upsertBlocks,
        };
    }

    if (msgType === MSG_TYPE_SNAPSHOT) {
        const sequence = view.getUint32(offset, true);
        offset += 4;

        const voxelSize = view.getFloat32(offset, true);
        offset += 4;

        const numBlocks = view.getUint32(offset, true);
        offset += 4;

        const blocks: PackedBlock[] = [];
        for (let i = 0; i < numBlocks; i += 1) {
            const parsedBlock = parsePackedBlock(data, view, offset);
            blocks.push(parsedBlock.block);
            offset = parsedBlock.offset;
        }

        return {
            msgType,
            sequence,
            voxelSize,
            blocks,
        };
    }

    throw new Error(`Unknown voxel message type: ${msgType}`);
}

export const PointCloud: React.FC = () => {
    const { nc } = useNats();
    const ref = React.useRef<HTMLCanvasElement | null>(null);
    const svgRef = React.useRef<SVGSVGElement | null>(null);
    const [pose, setPose] = React.useState<Pose | null>(null);
    const [voxelCount, setVoxelCount] = React.useState<number | null>(null);
    const [blockCount, setBlockCount] = React.useState<number | null>(null);
    const [lastSeq, setLastSeq] = React.useState<number>(0);
    const [storedViewMode, setStoredViewMode] = useWatchKV<ViewMode>({
        key: 'rabbit.perception.view_mode',
        parse: (data) => {
            const val = data.json() as string;
            return VIEW_MODES.some((m) => m.id === val) ? (val as ViewMode) : 'third';
        },
    });
    const viewMode = storedViewMode ?? 'third';
    const viewModeRef = React.useRef<ViewMode>(viewMode);
    const [nvblox, setNvblox] = React.useState<NvbloxHealth | null>(null);

    const setViewMode = (mode: ViewMode) => {
        viewModeRef.current = mode;
        setStoredViewMode(() => mode);
    };

    React.useEffect(() => {
        viewModeRef.current = viewMode;
    }, [viewMode]);

    React.useLayoutEffect(() => {
        const canvas = ref.current;
        if (canvas == null) {
            return;
        }

        const { width, height } = canvas.getBoundingClientRect();
        const renderer = new THREE.WebGLRenderer({
            canvas,
            antialias: true,
        });
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.setClearColor(0x1a1a2e);
        renderer.setSize(width, height);

        const scene = new THREE.Scene();

        const gridMaterial = new THREE.ShaderMaterial({
            transparent: true,
            side: THREE.DoubleSide,
            uniforms: {
                uColor: { value: new THREE.Color(0x00ff41) },
                uFade: { value: 8.0 },
            },
            vertexShader: `
                varying vec2 vWorldPos;
                void main() {
                    vec4 world = modelMatrix * vec4(position, 1.0);
                    vWorldPos = world.xz;
                    gl_Position = projectionMatrix * viewMatrix * world;
                }
            `,
            fragmentShader: `
                uniform vec3 uColor;
                uniform float uFade;
                varying vec2 vWorldPos;
                void main() {
                    vec2 grid = abs(fract(vWorldPos - 0.5) - 0.5);
                    vec2 line = fwidth(vWorldPos);
                    vec2 g = smoothstep(line * 0.5, line * 1.5, grid);
                    float gridLine = 1.0 - min(g.x, g.y);

                    // Major grid every 1m, minor every 0.25m
                    vec2 gridMajor = abs(fract(vWorldPos * 0.25 - 0.5) - 0.5);
                    vec2 lineMajor = fwidth(vWorldPos * 0.25);
                    vec2 gM = smoothstep(lineMajor * 0.5, lineMajor * 1.5, gridMajor);
                    float majorLine = 1.0 - min(gM.x, gM.y);

                    float a = max(gridLine * 0.15, majorLine * 0.35);

                    // Fade with distance from origin
                    float dist = length(vWorldPos);
                    a *= 1.0 - smoothstep(uFade * 0.3, uFade, dist);

                    if (a < 0.005) discard;
                    gl_FragColor = vec4(uColor, a);
                }
            `,
        });
        const grid = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), gridMaterial);
        grid.rotation.x = -Math.PI / 2;
        scene.add(grid);

        const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
        scene.add(ambientLight);

        const light = new THREE.DirectionalLight(0xffffff, 0.8);
        light.position.set(10, 10, 10);
        scene.add(light);

        const backLight = new THREE.DirectionalLight(0xffffff, 0.3);
        backLight.position.set(-5, 5, -5);
        scene.add(backLight);

        const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);
        camera.position.set(0, 3, 5);

        const controls = new OrbitControls(camera, canvas);
        controls.enableDamping = true;
        controls.dampingFactor = 0.1;
        controls.target.set(0, 0.5, 0);

        const robotMarker = new THREE.Group();
        const robotBody = new THREE.Mesh(
            new THREE.BoxGeometry(0.15, 0.06, 0.30),
            new THREE.MeshStandardMaterial({ color: 0xff3333 }),
        );
        robotMarker.add(robotBody);

        // Wheels
        const WHEEL_RADIUS = 0.04;
        const WHEEL_WIDTH = 0.02;
        const HALF_TRACK = 0.1; // lateral offset from center
        const FRONT_AXLE = -0.12; // forward from center (-Z is forward)
        const REAR_AXLE = 0.12; // backward from center

        const wheelGeometry = new THREE.CylinderGeometry(WHEEL_RADIUS, WHEEL_RADIUS, WHEEL_WIDTH, 12);
        wheelGeometry.rotateZ(Math.PI / 2); // align cylinder axis to X (lateral)
        const wheelMaterial = new THREE.MeshStandardMaterial({ color: 0x333333 });

        const createWheel = (x: number, z: number) => {
            const pivot = new THREE.Group(); // pivot for steering
            pivot.position.set(x, -0.03 + WHEEL_RADIUS, z);
            const mesh = new THREE.Mesh(wheelGeometry, wheelMaterial);
            pivot.add(mesh);
            robotMarker.add(pivot);
            return { pivot, mesh };
        };

        const wheelFL = createWheel(-HALF_TRACK, FRONT_AXLE);
        const wheelFR = createWheel(HALF_TRACK, FRONT_AXLE);
        const wheelRL = createWheel(-HALF_TRACK, REAR_AXLE);
        const wheelRR = createWheel(HALF_TRACK, REAR_AXLE);

        let wheelRotation = 0;
        let steeringAngle = 0;
        let wheelSpeed = 0; // rad/s derived from roboclaw speed

        scene.add(robotMarker);

        const RETURN_DELAY = 3000;
        const LERP_SPEED = 3;
        let lastInteraction = 0;
        let userControlling = false;
        let lastViewMode: ViewMode = viewModeRef.current ?? 'third';

        const fpvPosition = new THREE.Vector3();
        const fpvLookTarget = new THREE.Vector3();
        const targetCamPos = new THREE.Vector3();
        let hasPose = false;

        const setViewModeFromLoop = (mode: ViewMode) => {
            viewModeRef.current = mode;
            setViewMode(mode);
        };

        controls.addEventListener('start', () => {
            userControlling = true;
            if (viewModeRef.current === 'fpv') {
                setViewModeFromLoop('third');
            }
        });
        controls.addEventListener('end', () => {
            lastInteraction = performance.now();
            userControlling = false;
        });

        const blockGeometry = new THREE.BoxGeometry(1, 1, 1);
        const blockMaterial = new THREE.MeshStandardMaterial({ vertexColors: true });
        const voxelMesh = new THREE.InstancedMesh(blockGeometry, blockMaterial, MAX_INSTANCES);
        voxelMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        voxelMesh.instanceColor = new THREE.InstancedBufferAttribute(
            new Float32Array(MAX_INSTANCES * 3),
            3,
        );
        voxelMesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
        voxelMesh.count = 0;
        scene.add(voxelMesh);

        const voxelMap = new VoxelMap(MAX_INSTANCES);
        const dummy = new THREE.Object3D();
        let awaitingSnapshot = false;

        const publishSnapshotRequest = () => {
            if (awaitingSnapshot) {
                return;
            }

            try {
                awaitingSnapshot = true;
                nc.publish(VOXELS_REQUEST_SUBJECT, EMPTY_PAYLOAD);
            } catch (error) {
                awaitingSnapshot = false;
                L.error('Failed to request voxel snapshot', error);
            }
        };

        const syncOverlay = () => {
            setVoxelCount(voxelMap.voxelCount);
            setBlockCount(voxelMap.blockCount);
            setLastSeq(voxelMap.lastSeq);
        };

        let poseFrame = 0;
        const poseWatcher = nc.subscribe('rabbit.zed.pose', {
            callback: (_, msg) => {
                const nextPose = Pose.parse(msg?.json());

                const [px, py, pz] = nextPose.translation;
                const [qx, qy, qz, qw] = nextPose.orientation;

                robotMarker.position.set(px, py, pz);
                robotMarker.quaternion.set(qx, qy, qz, qw).normalize();

                fpvPosition.set(px, py, pz);
                const q = new THREE.Quaternion(qx, qy, qz, qw).normalize();
                const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(q).multiplyScalar(2);
                fpvLookTarget.copy(fpvPosition).add(forward);
                hasPose = true;

                if (poseFrame++ % 30 === 0) {
                    setPose(nextPose);
                }
            },
        });

        const deltaSub = nc.subscribe(VOXELS_DELTA_SUBJECT, {
            callback: (_, msg) => {
                try {
                    const parsed = parseVoxelMessage(msg.data);
                    if (parsed.msgType !== MSG_TYPE_DELTA) {
                        return;
                    }

                    if (voxelMap.lastSeq === 0) {
                        publishSnapshotRequest();
                        return;
                    }

                    if (parsed.sequence <= voxelMap.lastSeq) {
                        return;
                    }

                    if (parsed.sequence !== voxelMap.lastSeq + 1) {
                        L.warn('Voxel delta gap detected, requesting snapshot', {
                            expected: voxelMap.lastSeq + 1,
                            received: parsed.sequence,
                        });
                        publishSnapshotRequest();
                        return;
                    }

                    voxelMap.applyDelta(voxelMesh, dummy, parsed);
                    voxelMesh.instanceMatrix.needsUpdate = true;
                    if (voxelMesh.instanceColor != null) {
                        voxelMesh.instanceColor.needsUpdate = true;
                    }
                    syncOverlay();
                } catch (error) {
                    L.error('Failed to apply voxel delta', error);
                }
            },
        });

        const snapshotSub = nc.subscribe(VOXELS_SNAPSHOT_SUBJECT, {
            callback: (_, msg) => {
                try {
                    const parsed = parseVoxelMessage(msg.data);
                    if (parsed.msgType !== MSG_TYPE_SNAPSHOT) {
                        return;
                    }

                    awaitingSnapshot = false;

                    if (parsed.sequence < voxelMap.lastSeq) {
                        return;
                    }

                    voxelMap.applySnapshot(voxelMesh, dummy, parsed);
                    voxelMesh.instanceMatrix.needsUpdate = true;
                    if (voxelMesh.instanceColor != null) {
                        voxelMesh.instanceColor.needsUpdate = true;
                    }
                    syncOverlay();
                } catch (error) {
                    awaitingSnapshot = false;
                    L.error('Failed to apply voxel snapshot', error);
                }
            },
        });

        publishSnapshotRequest();

        const nvbloxSub = nc.subscribe(NVBLOX_HEALTH_SUBJECT, {
            callback: (_, msg) => {
                try {
                    setNvblox(msg.json() as NvbloxHealth);
                } catch {}
            },
        });

        let speedL = 0;
        let speedR = 0;

        const roboclawSub = nc.subscribe('rabbit.roboclaw', {
            callback: (_, msg) => {
                try {
                    const data = msg.json() as { m1: { speed: number; encoder: number }; m2: { speed: number; encoder: number } };
                    speedL = data.m1.speed;
                    speedR = data.m2.speed;
                    wheelSpeed = ((data.m1.speed + data.m2.speed) / 2) * 0.001;
                } catch {}
            },
        });

        const joySub = nc.subscribe('rabbit.cmd.joy', {
            callback: (_, msg) => {
                try {
                    const data = msg.json() as { sticks: { left: { x: number } } };
                    // Map stick [-1, 1] to steering angle (max ~30 degrees)
                    steeringAngle = -(data.sticks.left.x ?? 0) * (Math.PI / 6);
                } catch {}
            },
        });

        let lastFrameTime = performance.now();
        renderer.setAnimationLoop(() => {
            const now = performance.now();
            const dt = (now - lastFrameTime) / 1000;
            lastFrameTime = now;

            const mode = viewModeRef.current;
            const idleMs = now - lastInteraction;
            const modeChanged = mode !== lastViewMode;
            lastViewMode = mode;

            // On mode change, reset idle timer so camera moves immediately
            if (modeChanged) {
                lastInteraction = 0;
            }

            if (hasPose) {
                const t = 1 - Math.exp(-LERP_SPEED * dt);
                const defaultUp = new THREE.Vector3(0, 1, 0);

                if (mode === 'fpv') {
                    camera.up.lerp(defaultUp, t);
                    if (!userControlling && idleMs > RETURN_DELAY) {
                        camera.position.lerp(fpvPosition, t);
                        controls.target.lerp(fpvLookTarget, t);
                    }
                } else if (mode === 'third') {
                    camera.up.lerp(defaultUp, t);
                    // Always keep orbit target on the robot
                    controls.target.lerp(fpvPosition, t);

                    if (!userControlling) {
                        const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(robotMarker.quaternion);
                        targetCamPos.copy(fpvPosition).add(forward.multiplyScalar(-0.8)).setY(fpvPosition.y + 0.5);
                        camera.position.lerp(targetCamPos, t);
                    }
                } else if (mode === 'top') {
                    targetCamPos.set(fpvPosition.x, fpvPosition.y + 2, fpvPosition.z);
                    controls.target.lerp(fpvPosition, t);

                    if (!userControlling && idleMs > RETURN_DELAY) {
                        camera.position.lerp(targetCamPos, t);
                        // Align camera up vector with robot forward so top-down rotates with heading
                        const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(robotMarker.quaternion);
                        forward.y = 0;
                        forward.normalize();
                        camera.up.lerp(forward, t);
                    }
                }
            }

            // Animate wheels
            wheelRotation += wheelSpeed * dt;
            wheelFL.mesh.rotation.x = wheelRotation;
            wheelFR.mesh.rotation.x = wheelRotation;
            wheelRL.mesh.rotation.x = wheelRotation;
            wheelRR.mesh.rotation.x = wheelRotation;

            // Front wheels steer
            wheelFL.pivot.rotation.y = steeringAngle;
            wheelFR.pivot.rotation.y = steeringAngle;

            // Project wheel positions to screen for HUD annotations
            const svg = svgRef.current;
            if (svg) {
                const w = renderer.domElement.clientWidth;
                const h = renderer.domElement.clientHeight;
                svg.setAttribute('viewBox', `0 0 ${w} ${h}`);

                const project = (pivot: THREE.Group) => {
                    const pos = new THREE.Vector3();
                    pivot.getWorldPosition(pos);
                    pos.project(camera);
                    return { x: (pos.x * 0.5 + 0.5) * w, y: (-pos.y * 0.5 + 0.5) * h, behind: pos.z > 1 };
                };

                const fl = project(wheelFL.pivot);
                const fr = project(wheelFR.pivot);
                const rl = project(wheelRL.pivot);
                const rr = project(wheelRR.pivot);

                const steerDeg = (steeringAngle * 180 / Math.PI).toFixed(1);

                const annotations = [
                    { wp: fl, label: `${speedL}`, offset: [-60, -30] as const },
                    { wp: fr, label: `${speedR}`, offset: [60, -30] as const },
                    { wp: rl, label: `${speedL}`, offset: [-60, 30] as const },
                    { wp: rr, label: `${speedR}`, offset: [60, 30] as const },
                ];

                let svgContent = '';
                for (const { wp, label, offset } of annotations) {
                    if (wp.behind) continue;
                    const tx = wp.x + offset[0];
                    const ty = wp.y + offset[1];
                    svgContent += `<line x1="${wp.x}" y1="${wp.y}" x2="${tx}" y2="${ty}" stroke="rgba(0,255,65,0.4)" stroke-width="1"/>`;
                    svgContent += `<circle cx="${wp.x}" cy="${wp.y}" r="2.5" fill="#00ff41" opacity="0.6"/>`;
                    svgContent += `<text x="${tx}" y="${ty - 4}" fill="#00ff41" font-size="10" font-family="monospace" text-anchor="${offset[0] < 0 ? 'end' : 'start'}" opacity="0.85">${label}</text>`;
                }

                // Steering angle label between front wheels
                if (!fl.behind && !fr.behind) {
                    const mx = (fl.x + fr.x) / 2;
                    const my = (fl.y + fr.y) / 2 - 20;
                    svgContent += `<text x="${mx}" y="${my}" fill="#00ff41" font-size="10" font-family="monospace" text-anchor="middle" opacity="0.7">${steerDeg}°</text>`;
                }

                svg.innerHTML = svgContent;
            }

            controls.update();
            renderer.render(scene, camera);
        });

        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                if (entry.target !== canvas) {
                    continue;
                }

                const nextWidth = entry.contentRect.width;
                const nextHeight = entry.contentRect.height;
                renderer.setSize(nextWidth, nextHeight);
                camera.aspect = nextWidth / nextHeight;
                camera.updateProjectionMatrix();
            }
        });
        observer.observe(canvas);

        return () => {
            observer.disconnect();
            renderer.setAnimationLoop(null);
            controls.dispose();
            poseWatcher.unsubscribe();
            deltaSub.unsubscribe();
            snapshotSub.unsubscribe();
            nvbloxSub.unsubscribe();
            roboclawSub.unsubscribe();
            joySub.unsubscribe();
            wheelGeometry.dispose();
            wheelMaterial.dispose();
            blockGeometry.dispose();
            blockMaterial.dispose();
            grid.geometry.dispose();
            gridMaterial.dispose();
            renderer.dispose();
        };
    }, [nc]);

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
            <svg
                ref={svgRef}
                className={css`
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    pointer-events: none;
                `}
            />
            {/* Top-right: view mode */}
            <div
                className={css`
                    position: absolute;
                    top: 8px;
                    right: 8px;
                `}>
                <ui.SegmentedControl segments={VIEW_MODES} value={viewMode} onChange={(id) => setViewMode(id as ViewMode)} />
            </div>

            {/* Bottom-left: combined stats panel */}
            <div
                className={css`
                    position: absolute;
                    bottom: 8px;
                    left: 8px;
                    background: rgba(0, 0, 0, 0.7);
                    border: 1px solid rgba(0, 255, 65, 0.15);
                    padding: 10px 12px;
                    font-size: 11px;
                    font-variant-numeric: tabular-nums;
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                    min-width: 180px;
                `}>
                {/* Perception */}
                <div
                    className={css`
                        display: flex;
                        flex-direction: column;
                        gap: 2px;
                    `}>
                    <OverlayRow label='ALT' value={`${pose?.translation[1].toFixed(2) ?? '—'}m`} />
                    {voxelCount != null && <OverlayRow label='VOXELS' value={voxelCount.toLocaleString()} />}
                    {blockCount != null && <OverlayRow label='BLOCKS' value={blockCount.toLocaleString()} />}
                    <OverlayRow label='SEQ' value={lastSeq.toLocaleString()} />
                </div>

                {/* Nvblox mapper */}
                {nvblox != null && (
                    <div
                        className={css`
                            display: flex;
                            flex-direction: column;
                            gap: 2px;
                            padding-top: 6px;
                            border-top: 1px solid rgba(0, 255, 65, 0.1);
                        `}>
                        <OverlayRow label='RECV' value={`${nvblox.processed_bundle_count}/${nvblox.received_bundle_count}`} />
                        <OverlayRow label='INTEGRATE' value={`${nvblox.last_integration_duration_ms.toFixed(0)}ms`} warn={nvblox.last_integration_duration_ms > 200} />
                        <OverlayRow label='ESDF' value={`${nvblox.last_esdf_update_duration_ms.toFixed(0)}ms`} />
                        <OverlayRow label='ALLOC' value={formatSize(nvblox.allocated_bytes)} />
                        {nvblox.lock_busy_skip_count > 0 && (
                            <OverlayRow label='LOCK SKIP' value={`${nvblox.lock_busy_skip_count}`} warn />
                        )}
                    </div>
                )}

                {/* Legend */}
                <div
                    className={css`
                        display: flex;
                        flex-direction: column;
                        gap: 1px;
                        padding-top: 6px;
                        border-top: 1px solid rgba(0, 255, 65, 0.1);
                        font-size: 10px;
                        opacity: 0.7;
                    `}>
                    <div><span style={{ color: '#00ff66' }}>■</span> FLOOR</div>
                    <div><span style={{ color: '#ff5533' }}>■</span> OBSTACLE</div>
                    <div><span style={{ color: '#505064' }}>■</span> STRUCTURE</div>
                    <div><span style={{ color: '#282844' }}>■</span> BELOW</div>
                </div>
            </div>
        </div>
    );
};

function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}G`;
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)}K`;
    return `${bytes}B`;
}

const OverlayRow: React.FC<{ label: string; value: string; warn?: boolean }> = ({ label, value, warn }) => (
    <div
        className={css`
            display: flex;
            justify-content: space-between;
            gap: 12px;
        `}>
        <span
            className={css`
                opacity: 0.5;
            `}>
            {label}
        </span>
        <span
            className={css`
                color: ${warn ? '#ff5533' : 'inherit'};
            `}>
            {value}
        </span>
    </div>
);

type Pose = z.infer<typeof Pose>;
const Pose = z.object({
    translation: z.tuple([z.number(), z.number(), z.number()]),
    orientation: z.tuple([z.number(), z.number(), z.number(), z.number()]),
});

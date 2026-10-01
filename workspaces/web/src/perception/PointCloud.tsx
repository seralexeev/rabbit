import { css } from '@emotion/css';
import React from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import z from 'zod';

import { useNats, useWatchKV } from '../app/NatsProvider.tsx';
import { L } from '../terminal/LogProvider.tsx';
import { ui } from '../ui/index.ts';

// --- Constants ---

const NAV_COSTMAP_SUBJECT = 'rabbit.nav.local.costmap';
const PERCEPTION_HEALTH_SUBJECT = 'rabbit.health.perception';

const COSTMAP_UNKNOWN = 0;
const COSTMAP_TRAVERSABLE = 1;
const COSTMAP_CAUTION = 2;
const COSTMAP_BLOCKED = 3;

const MAX_WALL_INSTANCES = 20_000;
const WALL_HEIGHT = 0.40;


const VIEW_MODES = [
    { id: 'fpv', label: 'FPV' },
    { id: 'third', label: '3RD' },
    { id: 'top', label: 'TOP' },
] as const;

type ViewMode = (typeof VIEW_MODES)[number]['id'];

// --- Types ---

type CostmapMessage = {
    frame_number: number;
    timestamp: number;
    resolution: number;
    width: number;
    height: number;
    origin_x: number;
    origin_z: number;
    cells: number[];
    counts?: { unknown: number; traversable: number; caution: number; blocked: number };
};

type PerceptionHealth = {
    received_count: number;
    processed_count: number;
    last_process_ms: number;
    last_points_count: number;
    last_obstacle_count: number;
    publish_count: number;
};

// --- Component ---

export const PointCloud: React.FC = () => {
    const { nc } = useNats();
    const ref = React.useRef<HTMLCanvasElement | null>(null);
    const svgRef = React.useRef<SVGSVGElement | null>(null);
    const [pose, setPose] = React.useState<Pose | null>(null);
    const [storedViewMode, setStoredViewMode] = useWatchKV<ViewMode>({
        key: 'rabbit.perception.view_mode',
        parse: (data) => {
            const val = data.json() as string;
            return VIEW_MODES.some((m) => m.id === val) ? (val as ViewMode) : 'third';
        },
    });
    const viewMode = storedViewMode ?? 'third';
    const viewModeRef = React.useRef<ViewMode>(viewMode);
    const [health, setHealth] = React.useState<PerceptionHealth | null>(null);
    const [costmapStats, setCostmapStats] = React.useState<CostmapMessage['counts'] | null>(null);

    const setViewMode = (mode: ViewMode) => {
        viewModeRef.current = mode;
        setStoredViewMode(() => mode);
    };

    React.useEffect(() => {
        viewModeRef.current = viewMode;
    }, [viewMode]);

    React.useLayoutEffect(() => {
        const canvas = ref.current;
        if (canvas == null) return;

        const { width, height } = canvas.getBoundingClientRect();

        // --- Renderer ---
        const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.setClearColor(0x111118);
        renderer.setSize(width, height);

        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x111118, 0.06);

        // --- Lights ---
        scene.add(new THREE.AmbientLight(0xffffff, 0.5));
        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(3, 8, 5);
        scene.add(dirLight);
        const fillLight = new THREE.DirectionalLight(0x4488ff, 0.3);
        fillLight.position.set(-3, 4, -5);
        scene.add(fillLight);

        // --- Ground grid (shader) ---
        const gridMaterial = new THREE.ShaderMaterial({
            transparent: true,
            depthWrite: false,
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
                    vec2 gridMajor = abs(fract(vWorldPos * 0.25 - 0.5) - 0.5);
                    vec2 lineMajor = fwidth(vWorldPos * 0.25);
                    vec2 gM = smoothstep(lineMajor * 0.5, lineMajor * 1.5, gridMajor);
                    float majorLine = 1.0 - min(gM.x, gM.y);
                    float a = max(gridLine * 0.08, majorLine * 0.2);
                    float dist = length(vWorldPos);
                    a *= 1.0 - smoothstep(uFade * 0.3, uFade, dist);
                    if (a < 0.005) discard;
                    gl_FragColor = vec4(uColor, a);
                }
            `,
        });
        const grid = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), gridMaterial);
        grid.rotation.x = -Math.PI / 2;
        grid.position.y = -0.001;
        grid.renderOrder = -2;
        scene.add(grid);

        // --- Camera ---
        const camera = new THREE.PerspectiveCamera(60, width / height, 0.05, 100);
        camera.position.set(0, 3, 5);

        const controls = new OrbitControls(camera, canvas);
        controls.enableDamping = true;
        controls.dampingFactor = 0.1;
        controls.target.set(0, 0.5, 0);

        // --- Robot marker ---
        const robotMarker = new THREE.Group();
        const robotBody = new THREE.Mesh(
            new THREE.BoxGeometry(0.15, 0.06, 0.30),
            new THREE.MeshStandardMaterial({ color: 0xff3333 }),
        );
        robotMarker.add(robotBody);

        const WHEEL_RADIUS = 0.04;
        const WHEEL_WIDTH = 0.02;
        const HALF_TRACK = 0.1;
        const FRONT_AXLE = -0.12;
        const REAR_AXLE = 0.12;

        const wheelGeometry = new THREE.CylinderGeometry(WHEEL_RADIUS, WHEEL_RADIUS, WHEEL_WIDTH, 12);
        wheelGeometry.rotateZ(Math.PI / 2);
        const wheelMaterial = new THREE.MeshStandardMaterial({ color: 0x333333 });

        const createWheel = (x: number, z: number) => {
            const pivot = new THREE.Group();
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
        let wheelSpeed = 0;

        scene.add(robotMarker);

        // --- Occupancy map: DataTexture on a single plane ---
        // Much more efficient than instanced meshes: one draw call for the entire floor
        const GRID_SIZE = 200; // must match Python OccupancyGrid.GRID_SIZE
        const texData = new Uint8Array(GRID_SIZE * GRID_SIZE * 4); // RGBA
        const floorTexture = new THREE.DataTexture(texData, GRID_SIZE, GRID_SIZE, THREE.RGBAFormat);
        floorTexture.minFilter = THREE.NearestFilter;
        floorTexture.magFilter = THREE.NearestFilter;
        floorTexture.wrapS = THREE.ClampToEdgeWrapping;
        floorTexture.wrapT = THREE.ClampToEdgeWrapping;

        const floorMaterial = new THREE.ShaderMaterial({
            transparent: false,
            uniforms: {
                uMap: { value: floorTexture },
            },
            vertexShader: `
                varying vec2 vUv;
                void main() {
                    vUv = uv;
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                }
            `,
            fragmentShader: `
                uniform sampler2D uMap;
                varying vec2 vUv;
                void main() {
                    vec4 c = texture2D(uMap, vUv);
                    if (c.a < 0.01) discard;
                    gl_FragColor = vec4(c.rgb, 1.0);
                }
            `,
        });

        const floorPlane = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), floorMaterial);
        floorPlane.rotation.x = -Math.PI / 2;
        floorPlane.position.y = 0.002;
        floorPlane.renderOrder = -1;
        scene.add(floorPlane);

        // --- Walls: instanced boxes ---
        const wallGeom = new THREE.BoxGeometry(1, 1, 1);
        const wallMaterial = new THREE.MeshStandardMaterial({
            color: 0xff4444,
            emissive: 0x661111,
            emissiveIntensity: 0.6,
            roughness: 0.5,
            metalness: 0.0,
            fog: false,
        });
        const wallMesh = new THREE.InstancedMesh(wallGeom, wallMaterial, MAX_WALL_INSTANCES);
        wallMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        wallMesh.renderOrder = 1;
        wallMesh.count = 0;
        scene.add(wallMesh);

        const dummy = new THREE.Object3D();

        const updateCostmap = (msg: CostmapMessage) => {
            const { resolution, width: w, height: h, origin_x, origin_z, cells } = msg;
            const worldSize = w * resolution;

            // Update floor plane transform to match grid world position
            floorPlane.position.x = origin_x + worldSize * 0.5;
            floorPlane.position.z = origin_z + worldSize * 0.5;
            floorPlane.scale.set(worldSize, worldSize, 1);

            // Fill texture data — encode cell colors into RGBA
            let wallSlot = 0;

            for (let row = 0; row < h; row++) {
                for (let col = 0; col < w; col++) {
                    const cell = cells[row * w + col]!;
                    // DataTexture row 0 = bottom; plane rotated -PI/2 maps v=0 to +Z.
                    // Grid row 0 = min Z, so flip rows to match.
                    const texRow = h - 1 - row;
                    const texIdx = (texRow * w + col) * 4;

                    if (cell === COSTMAP_UNKNOWN) {
                        texData[texIdx] = 0;
                        texData[texIdx + 1] = 0;
                        texData[texIdx + 2] = 0;
                        texData[texIdx + 3] = 0;
                    } else if (cell === COSTMAP_TRAVERSABLE) {
                        texData[texIdx] = 34;    // 0x22
                        texData[texIdx + 1] = 204; // 0xcc
                        texData[texIdx + 2] = 85;  // 0x55
                        texData[texIdx + 3] = 140;
                    } else if (cell === COSTMAP_CAUTION) {
                        texData[texIdx] = 238;   // 0xee
                        texData[texIdx + 1] = 170; // 0xaa
                        texData[texIdx + 2] = 0;
                        texData[texIdx + 3] = 160;
                    } else if (cell === COSTMAP_BLOCKED) {
                        // No floor color — walls are 3D blocks only
                        texData[texIdx] = 0;
                        texData[texIdx + 1] = 0;
                        texData[texIdx + 2] = 0;
                        texData[texIdx + 3] = 0;
                        if (wallSlot < MAX_WALL_INSTANCES) {
                            const wx = origin_x + (col + 0.5) * resolution;
                            const wz = origin_z + (row + 0.5) * resolution;
                            dummy.position.set(wx, WALL_HEIGHT * 0.5, wz);
                            dummy.scale.set(resolution, WALL_HEIGHT, resolution);
                            dummy.updateMatrix();
                            wallMesh.setMatrixAt(wallSlot, dummy.matrix);
                            wallSlot++;
                        }
                    }
                }
            }

            floorTexture.needsUpdate = true;

            wallMesh.count = wallSlot;
            wallMesh.instanceMatrix.needsUpdate = true;

            setCostmapStats(msg.counts ?? null);
        };

        // --- Camera follow ---
        const RETURN_DELAY = 3000;
        const LERP_SPEED = 3;
        let lastInteraction = 0;
        let userControlling = false;
        let lastViewMode: ViewMode = viewModeRef.current ?? 'third';

        const fpvPosition = new THREE.Vector3();
        const fpvLookTarget = new THREE.Vector3();
        const targetCamPos = new THREE.Vector3();
        let hasPose = false;

        controls.addEventListener('start', () => {
            userControlling = true;
            if (viewModeRef.current === 'fpv') {
                viewModeRef.current = 'third';
                setViewMode('third');
            }
        });
        controls.addEventListener('end', () => {
            lastInteraction = performance.now();
            userControlling = false;
        });

        // --- Subscriptions ---
        let poseFrame = 0;
        const poseSub = nc.subscribe('rabbit.zed.pose', {
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

                if (poseFrame++ % 30 === 0) setPose(nextPose);
            },
        });

        const costmapSub = nc.subscribe(NAV_COSTMAP_SUBJECT, {
            callback: (_, msg) => {
                try {
                    updateCostmap(msg.json() as CostmapMessage);
                } catch (error) {
                    L.error('Failed to update costmap', error);
                }
            },
        });

        const healthSub = nc.subscribe(PERCEPTION_HEALTH_SUBJECT, {
            callback: (_, msg) => {
                try { setHealth(msg.json() as PerceptionHealth); } catch {}
            },
        });

        let encoderL = 0;
        let encoderR = 0;

        const roboclawSub = nc.subscribe('rabbit.roboclaw', {
            callback: (_, msg) => {
                try {
                    const data = msg.json() as { m1: { speed: number; encoder: number }; m2: { speed: number; encoder: number } };
                    wheelSpeed = ((data.m1.speed + data.m2.speed) / 2) * 0.001;
                    encoderL = data.m1.encoder;
                    encoderR = data.m2.encoder;
                } catch {}
            },
        });

        const joySub = nc.subscribe('rabbit.cmd.joy', {
            callback: (_, msg) => {
                try {
                    const data = msg.json() as { sticks: { left: { x: number } } };
                    steeringAngle = -(data.sticks.left.x ?? 0) * (Math.PI / 6);
                } catch {}
            },
        });

        // --- Render loop ---
        let lastFrameTime = performance.now();
        renderer.setAnimationLoop(() => {
            const now = performance.now();
            const dt = (now - lastFrameTime) / 1000;
            lastFrameTime = now;

            const mode = viewModeRef.current;
            const idleMs = now - lastInteraction;
            const modeChanged = mode !== lastViewMode;
            lastViewMode = mode;
            if (modeChanged) lastInteraction = 0;

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
                        const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(robotMarker.quaternion);
                        forward.y = 0;
                        forward.normalize();
                        camera.up.lerp(forward, t);
                    }
                }
            }

            // Wheels
            wheelRotation += wheelSpeed * dt;
            wheelFL.mesh.rotation.x = wheelRotation;
            wheelFR.mesh.rotation.x = wheelRotation;
            wheelRL.mesh.rotation.x = wheelRotation;
            wheelRR.mesh.rotation.x = wheelRotation;
            wheelFL.pivot.rotation.y = steeringAngle;
            wheelFR.pivot.rotation.y = steeringAngle;

            // Wheel HUD
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
                const steerDeg = ((steeringAngle * 180) / Math.PI).toFixed(1);

                const annotations = [
                    { wp: fl, label: `${encoderL}`, offset: [-60, -30] as const },
                    { wp: fr, label: `${encoderR}`, offset: [60, -30] as const },
                    { wp: rl, label: `${encoderL}`, offset: [-60, 30] as const },
                    { wp: rr, label: `${encoderR}`, offset: [60, 30] as const },
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

        // --- Resize ---
        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                if (entry.target !== canvas) continue;
                const w = entry.contentRect.width;
                const h = entry.contentRect.height;
                renderer.setSize(w, h);
                camera.aspect = w / h;
                camera.updateProjectionMatrix();
            }
        });
        observer.observe(canvas);

        // --- Cleanup ---
        return () => {
            observer.disconnect();
            renderer.setAnimationLoop(null);
            controls.dispose();
            poseSub.unsubscribe();
            costmapSub.unsubscribe();
            healthSub.unsubscribe();
            roboclawSub.unsubscribe();
            joySub.unsubscribe();
            floorTexture.dispose();
            floorMaterial.dispose();
            floorPlane.geometry.dispose();
            wallGeom.dispose();
            wallMaterial.dispose();
            wheelGeometry.dispose();
            wheelMaterial.dispose();
            grid.geometry.dispose();
            gridMaterial.dispose();
            renderer.dispose();
        };
    }, [nc]);

    return (
        <div className={css`width: 100% !important; height: 100% !important; position: relative;`}>
            <canvas ref={ref} className={css`width: 100% !important; height: 100% !important;`} />
            <svg
                ref={svgRef}
                className={css`position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;`}
            />

            {/* View mode */}
            <div className={css`position: absolute; top: 8px; right: 8px;`}>
                <ui.SegmentedControl segments={VIEW_MODES} value={viewMode} onChange={(id) => setViewMode(id as ViewMode)} />
            </div>

            {/* Stats */}
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
                <div className={css`display: flex; flex-direction: column; gap: 2px;`}>
                    <OverlayRow label="ALT" value={`${pose?.translation[1].toFixed(2) ?? '—'}m`} />
                </div>

                {/* Perception */}
                {health != null && (
                    <div className={css`display: flex; flex-direction: column; gap: 2px; padding-top: 6px; border-top: 1px solid rgba(0, 255, 65, 0.1);`}>
                        <OverlayRow label="RECV" value={`${health.processed_count}/${health.received_count}`} />
                        <OverlayRow label="PROCESS" value={`${health.last_process_ms}ms`} warn={health.last_process_ms > 200} />
                        <OverlayRow label="POINTS" value={`${health.last_points_count}`} />
                        <OverlayRow label="OBSTACLES" value={`${health.last_obstacle_count}`} />
                    </div>
                )}

                {/* Costmap */}
                {costmapStats != null && (
                    <div className={css`display: flex; flex-direction: column; gap: 2px; padding-top: 6px; border-top: 1px solid rgba(0, 255, 65, 0.1);`}>
                        <OverlayRow label="FREE" value={costmapStats.traversable.toLocaleString()} />
                        <OverlayRow label="CAUTION" value={costmapStats.caution.toLocaleString()} />
                        <OverlayRow label="BLOCKED" value={costmapStats.blocked.toLocaleString()} />
                    </div>
                )}

                {/* Legend */}
                <div className={css`display: flex; flex-direction: column; gap: 1px; padding-top: 6px; border-top: 1px solid rgba(0, 255, 65, 0.1); font-size: 10px; opacity: 0.7;`}>
                    <div><span style={{ color: '#22cc55' }}>■</span> FREE</div>
                    <div><span style={{ color: '#eeaa00' }}>■</span> CAUTION</div>
                    <div><span style={{ color: '#cc3333' }}>■</span> WALL</div>
                </div>
            </div>
        </div>
    );
};

// --- Small components ---

const OverlayRow: React.FC<{ label: string; value: string; warn?: boolean }> = ({ label, value, warn }) => (
    <div className={css`display: flex; justify-content: space-between; gap: 12px;`}>
        <span className={css`opacity: 0.5;`}>{label}</span>
        <span className={css`color: ${warn ? '#ff5533' : 'inherit'};`}>{value}</span>
    </div>
);

type Pose = z.infer<typeof Pose>;
const Pose = z.object({
    translation: z.tuple([z.number(), z.number(), z.number()]),
    orientation: z.tuple([z.number(), z.number(), z.number(), z.number()]),
});

import * as THREE from 'three';

import { HUD_COLOR } from '../hud/Hud.ts';
import { FLOOR_DEPTH_BIAS } from './GroundFx.ts';
import type { Scan } from './Telemetry.ts';
import { type ArcPose, CAMERA_TO_REAR_AXLE, FOOTPRINT, curvatureForSteer, sweepPose } from './drive.ts';

const FRONT = FOOTPRINT.front;
const REAR = FOOTPRINT.rear;
const HALF_WIDTH = FOOTPRINT.halfWidth;
const MARGIN = 0.04;
const LENGTH = 1.2;
const SAMPLES = 64;
const FREE_STEP = 0.02;
const MAX_SCAN_POINTS = 128;
const LIFT = 0.01;
const CURVATURE_RATE = 14;
const REBUILD_EPSILON = 0.002;
const UNKNOWN_FREE = 1e3;
const AMBER = 0xffb547;
const ALERT = 0xff5a4a;

export type SteerFxFrame = {
    origin: THREE.Vector3;
    yaw: number;
    steer: number | null;
    direction: 1 | -1;
    emphasis: number;
    scan: Scan | null;
    scanVersion: number;
    dt: number;
};

export type SteerFx = {
    group: THREE.Group;
    update: (frame: SteerFxFrame) => void;
    dispose: () => void;
};

const corridorMaterial = () =>
    new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        uniforms: {
            uColor: { value: new THREE.Color(HUD_COLOR) },
            uWarn: { value: new THREE.Color(AMBER) },
            uAlert: { value: new THREE.Color(ALERT) },
            uFree: { value: UNKNOWN_FREE },
            uEmphasis: { value: 1 },
        },
        vertexShader: `
            attribute float aTravel;
            attribute float aSide;
            varying float vTravel;
            varying float vSide;
            void main() {
                vTravel = aTravel;
                vSide = aSide;
                vec4 view = modelViewMatrix * vec4(position, 1.0);
                view.xyz -= normalize(view.xyz) * ${FLOOR_DEPTH_BIAS.toFixed(3)};
                gl_Position = projectionMatrix * view;
            }
        `,
        fragmentShader: `
            uniform vec3 uColor;
            uniform vec3 uWarn;
            uniform vec3 uAlert;
            uniform float uFree;
            uniform float uEmphasis;
            varying float vTravel;
            varying float vSide;
            const float LENGTH = ${LENGTH.toFixed(3)};
            float line(float d, float w) {
                return 1.0 - smoothstep(w, w + fwidth(d) * 1.5, abs(d));
            }
            void main() {
                float side = abs(vSide);
                float edge = line(1.0 - side, 0.0);
                float v = (vTravel + side * 0.07) / 0.16;
                float cell = abs(fract(v + 0.5) - 0.5);
                float chevron = (1.0 - smoothstep(0.06, 0.06 + fwidth(v) * 1.5, cell)) * step(side, 0.55) * step(0.0, vTravel);
                float ahead = smoothstep(-0.05, 0.05, vTravel);
                float fade = 1.0 - smoothstep(LENGTH * 0.5, LENGTH, vTravel);
                float near = 1.0 - smoothstep(0.3, 0.6, uFree);
                float blocked = step(uFree, vTravel);
                float bar = line(vTravel - uFree, 0.008) * step(uFree, LENGTH);
                vec3 stroke = mix(mix(uColor, uWarn, near), uAlert, max(blocked, bar));
                stroke = mix(stroke, vec3(1.0), bar * 0.35);
                float strokes = max(max(edge * 0.9, chevron * 0.5 * ahead) * mix(1.0, 0.8, blocked), bar);
                float lane = 0.55 * mix(0.5, 1.0, ahead);
                float alpha = strokes + lane * (1.0 - strokes);
                vec3 color = mix(stroke * 0.1, stroke, strokes / max(alpha, 1e-4));
                alpha *= fade * uEmphasis;
                if (alpha < 0.003) discard;
                gl_FragColor = vec4(color, alpha);
            }
        `,
    });

export const createSteerFx = (): SteerFx => {
    const group = new THREE.Group();
    const positions = new Float32Array(SAMPLES * 2 * 3);
    const travel = new Float32Array(SAMPLES * 2);
    const sides = new Float32Array(SAMPLES * 2);
    const indices: number[] = [];
    for (let i = 0; i < SAMPLES; i++) {
        sides[i * 2] = -1;
        sides[i * 2 + 1] = 1;
        if (i < SAMPLES - 1) {
            const a = i * 2;
            indices.push(a, a + 2, a + 1, a + 1, a + 2, a + 3);
        }
    }
    const geometry = new THREE.BufferGeometry();
    const positionAttr = new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage);
    const travelAttr = new THREE.BufferAttribute(travel, 1).setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('position', positionAttr);
    geometry.setAttribute('aTravel', travelAttr);
    geometry.setAttribute('aSide', new THREE.BufferAttribute(sides, 1));
    geometry.setIndex(indices);
    const material = corridorMaterial();
    const mesh = new THREE.Mesh(geometry, material);
    mesh.frustumCulled = false;
    mesh.renderOrder = 1;
    mesh.visible = false;
    group.add(mesh);

    const scanPoints = new Float32Array(MAX_SCAN_POINTS * 2);
    const pose: ArcPose = { along: 0, across: 0, theta: 0 };
    let curvature = 0;
    let builtCurvature = Number.NaN;
    let builtDirection = 0;
    let freeScan = -1;
    let freeCurvature = Number.NaN;

    const build = (k: number, direction: 1 | -1) => {
        const lead = direction > 0 ? FRONT : REAR;
        const trail = direction > 0 ? REAR : FRONT;
        const bend = Math.abs(k);
        const extra =
            (lead * lead * bend) / (Math.sqrt((1 + HALF_WIDTH * bend) ** 2 + (lead * k) ** 2) + 1 + HALF_WIDTH * bend);
        const left = HALF_WIDTH + (k > 0 ? extra : 0);
        const right = HALF_WIDTH + (k < 0 ? extra : 0);
        const span = LENGTH + lead + trail;
        for (let i = 0; i < SAMPLES; i++) {
            const u = -trail + (span * i) / (SAMPLES - 1);
            const { along, across, theta } = sweepPose(u > 0 ? k : 0, direction * u, pose);
            const rx = Math.cos(theta);
            const rz = Math.sin(theta);
            const a = i * 6;
            positions[a] = across - left * rx;
            positions[a + 1] = 0;
            positions[a + 2] = -along - left * rz;
            positions[a + 3] = across + right * rx;
            positions[a + 4] = 0;
            positions[a + 5] = -along + right * rz;
            travel[i * 2] = u - lead;
            travel[i * 2 + 1] = u - lead;
        }
        positionAttr.needsUpdate = true;
        travelAttr.needsUpdate = true;
        builtCurvature = k;
        builtDirection = direction;
    };

    const freeDistance = (k: number, scan: Scan) => {
        if (scan.blind) return 0;
        let count = 0;
        for (let i = 0; i < scan.ranges.length && count < MAX_SCAN_POINTS; i++) {
            const range = scan.ranges[i];
            if (range == null) continue;
            const angle = THREE.MathUtils.degToRad(scan.angle_min_deg + (i + 0.5) * scan.angle_step_deg);
            scanPoints[count * 2] = range * Math.cos(angle) + CAMERA_TO_REAR_AXLE;
            scanPoints[count * 2 + 1] = range * Math.sin(angle);
            count++;
        }
        for (let d = 0; d <= LENGTH + 1e-9; d += FREE_STEP) {
            const { along: px, across: py, theta } = sweepPose(k, d, pose);
            const cos = Math.cos(theta);
            const sin = Math.sin(theta);
            for (let j = 0; j < count; j++) {
                const dx = scanPoints[j * 2]! - px;
                const dy = scanPoints[j * 2 + 1]! - py;
                const along = dx * cos + dy * sin;
                const across = -dx * sin + dy * cos;
                if (along <= FRONT + MARGIN && along >= -REAR - MARGIN && Math.abs(across) <= HALF_WIDTH + MARGIN) return d;
            }
        }
        return UNKNOWN_FREE;
    };

    const update = (frame: SteerFxFrame) => {
        mesh.visible = frame.steer != null;
        if (frame.steer == null) return;
        const target = curvatureForSteer(frame.steer);
        curvature += (target - curvature) * (1 - Math.exp(-CURVATURE_RATE * frame.dt));
        if (frame.direction !== builtDirection || Math.abs(curvature - builtCurvature) > REBUILD_EPSILON)
            build(curvature, frame.direction);

        const scan = frame.direction > 0 ? frame.scan : null;
        const scanVersion = scan == null ? -1 : frame.scanVersion;
        if (scanVersion !== freeScan || target !== freeCurvature) {
            freeScan = scanVersion;
            freeCurvature = target;
            material.uniforms['uFree']!.value = scan == null ? UNKNOWN_FREE : freeDistance(target, scan);
        }
        material.uniforms['uEmphasis']!.value = frame.emphasis;
        mesh.position.set(frame.origin.x, frame.origin.y + LIFT, frame.origin.z);
        mesh.rotation.y = frame.yaw;
    };

    return {
        group,
        update,
        dispose: () => {
            geometry.dispose();
            material.dispose();
        },
    };
};

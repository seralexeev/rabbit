import * as THREE from 'three';

import { HUD_COLOR } from '../hud/Hud.ts';

const GRID_SIZE = 40;
const GRID_SNAP = 4;
const RETICLE_SIZE = 0.56;
const TRAIL_POINTS = 600;
const TRAIL_STEP = 0.04;
const TRAIL_RESET_DISTANCE = 1.5;
const TRAIL_LIFT = 0.004;

export type GroundFx = {
    group: THREE.Group;
    update: (time: number, ground: THREE.Vector3, track: THREE.Vector3, azimuth: number) => void;
    distance: () => number;
    dispose: () => void;
};

const gridMaterial = () =>
    new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        uniforms: {
            uColor: { value: new THREE.Color(HUD_COLOR) },
            uCenter: { value: new THREE.Vector2() },
            uFade: { value: 9.0 },
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
            uniform vec2 uCenter;
            uniform float uFade;
            varying vec2 vWorldPos;
            float lines(vec2 p, float scale) {
                vec2 q = p * scale;
                vec2 g = abs(fract(q - 0.5) - 0.5) / fwidth(q);
                return 1.0 - min(min(g.x, g.y), 1.0);
            }
            void main() {
                float minor = lines(vWorldPos, 1.0);
                float major = lines(vWorldPos, 0.25);
                float a = max(minor * 0.07, major * 0.16);
                float dist = length(vWorldPos - uCenter);
                a *= 1.0 - smoothstep(uFade * 0.25, uFade, dist);
                if (a < 0.004) discard;
                gl_FragColor = vec4(uColor, a);
            }
        `,
    });

const reticleMaterial = () =>
    new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        uniforms: {
            uColor: { value: new THREE.Color(HUD_COLOR) },
            uTime: { value: 0 },
        },
        vertexShader: `
            varying vec2 vUv;
            void main() {
                vUv = uv;
                gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }
        `,
        fragmentShader: `
            uniform vec3 uColor;
            uniform float uTime;
            varying vec2 vUv;
            const float TAU = 6.2831853;
            float band(float d, float w) {
                return 1.0 - smoothstep(w, w + fwidth(d) * 1.5, abs(d));
            }
            void main() {
                vec2 p = (vUv - 0.5) * 2.0;
                float r = length(p);
                float a = atan(p.x, p.y);
                float outer = band(r - 0.94, 0.006);
                float dashes = band(r - 0.82, 0.014) * step(0.45, fract((a / TAU) * 48.0 + uTime * 0.12));
                float inner = band(r - 0.58, 0.004);
                float cardinal = abs(fract(a / (TAU * 0.25) + 0.5) - 0.5) * TAU * 0.25 * r;
                float ticks = band(cardinal, 0.008) * step(0.86, r) * step(r, 1.0);
                float chevron = band(abs(p.x) * 0.9 + p.y - 0.76, 0.012) * step(abs(p.x), 0.15) * step(0.5, p.y);
                float sweep = pow(fract((a / TAU) - uTime * 0.18), 10.0) * step(r, 0.82) * 0.22;
                float pulse = 0.7 + 0.3 * sin(uTime * 2.2);
                float alpha = outer * 0.55 + dashes * 0.45 * pulse + inner * 0.35 + ticks * 0.8 + chevron * 0.9 + sweep;
                alpha *= 1.0 - smoothstep(0.97, 1.0, r);
                if (alpha < 0.003) discard;
                gl_FragColor = vec4(uColor * alpha, alpha);
            }
        `,
    });

export const createGroundFx = (): GroundFx => {
    const group = new THREE.Group();

    const gridMat = gridMaterial();
    const gridGeo = new THREE.PlaneGeometry(GRID_SIZE, GRID_SIZE).rotateX(-Math.PI / 2);
    const grid = new THREE.Mesh(gridGeo, gridMat);
    grid.renderOrder = -2;
    grid.frustumCulled = false;
    group.add(grid);

    const reticleMat = reticleMaterial();
    const reticleGeo = new THREE.PlaneGeometry(RETICLE_SIZE, RETICLE_SIZE).rotateX(-Math.PI / 2);
    const reticle = new THREE.Mesh(reticleGeo, reticleMat);
    reticle.renderOrder = -1;
    group.add(reticle);

    const positions = new Float32Array(TRAIL_POINTS * 3);
    const colors = new Float32Array(TRAIL_POINTS * 4);
    const color = new THREE.Color(HUD_COLOR);
    for (let i = 0; i < TRAIL_POINTS; i++) {
        colors[i * 4] = color.r;
        colors[i * 4 + 1] = color.g;
        colors[i * 4 + 2] = color.b;
    }
    const trailGeo = new THREE.BufferGeometry();
    const positionAttr = new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage);
    const colorAttr = new THREE.BufferAttribute(colors, 4).setUsage(THREE.DynamicDrawUsage);
    trailGeo.setAttribute('position', positionAttr);
    trailGeo.setAttribute('color', colorAttr);
    trailGeo.setDrawRange(0, 0);
    const trailMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false });
    const trail = new THREE.Line(trailGeo, trailMat);
    trail.frustumCulled = false;
    trail.renderOrder = -1;
    group.add(trail);

    let count = 0;
    let travelled = 0;
    const last = new THREE.Vector3();

    const push = (point: THREE.Vector3) => {
        if (count === TRAIL_POINTS) {
            positions.copyWithin(0, 3);
        } else {
            count++;
        }
        const i = (count - 1) * 3;
        positions[i] = point.x;
        positions[i + 1] = point.y + TRAIL_LIFT;
        positions[i + 2] = point.z;
        for (let j = 0; j < count; j++) {
            colors[j * 4 + 3] = ((j + 1) / count) ** 1.6 * 0.85;
        }
        positionAttr.needsUpdate = true;
        colorAttr.needsUpdate = true;
        trailGeo.setDrawRange(0, count);
        last.copy(point);
    };

    const update: GroundFx['update'] = (time, ground, track, azimuth) => {
        grid.position.set(
            Math.round(ground.x / GRID_SNAP) * GRID_SNAP,
            ground.y - 0.001,
            Math.round(ground.z / GRID_SNAP) * GRID_SNAP,
        );
        gridMat.uniforms['uCenter']!.value.set(ground.x, ground.z);

        reticle.position.copy(ground).y += 0.002;
        reticle.rotation.y = azimuth;
        reticleMat.uniforms['uTime']!.value = time;

        if (count === 0) {
            push(track);
            return;
        }
        const step = Math.hypot(track.x - last.x, track.z - last.z);
        if (step > TRAIL_RESET_DISTANCE) {
            count = 0;
            push(track);
        } else if (step >= TRAIL_STEP) {
            travelled += step;
            push(track);
        }
    };

    return {
        group,
        update,
        distance: () => travelled,
        dispose: () => {
            gridGeo.dispose();
            gridMat.dispose();
            reticleGeo.dispose();
            reticleMat.dispose();
            trailGeo.dispose();
            trailMat.dispose();
        },
    };
};

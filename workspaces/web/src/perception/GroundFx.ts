import * as THREE from 'three';

import { HUD_COLOR } from '../hud/Hud.ts';

const GRID_SIZE = 40;
const GRID_SNAP = 4;
const TRAIL_POINTS = 600;
const TRAIL_STEP = 0.04;
const TRAIL_RESET_DISTANCE = 1.5;
const TRAIL_LIFT = 0.004;
export const FLOOR_DEPTH_BIAS = 0.04;

export type GroundFx = {
    group: THREE.Group;
    update: (ground: THREE.Vector3, track: THREE.Vector3, headingDeg: number) => void;
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

const COMPASS_SIZE = 1.0;
const COMPASS_TEXTURE = 512;
const RING_RADIUS = 0.34;
const LETTER_RADIUS = 0.44;
const CARDINALS = [
    ['N', 0],
    ['E', 90],
    ['S', 180],
    ['W', 270],
] as const;

const drawLetters = () => {
    const canvas = document.createElement('canvas');
    canvas.width = COMPASS_TEXTURE;
    canvas.height = COMPASS_TEXTURE;
    const ctx = canvas.getContext('2d')!;
    const scale = COMPASS_TEXTURE / COMPASS_SIZE;
    ctx.translate(COMPASS_TEXTURE / 2, COMPASS_TEXTURE / 2);
    ctx.scale(scale, scale);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const [label, deg] of CARDINALS) {
        ctx.save();
        ctx.rotate((deg * Math.PI) / 180);
        ctx.translate(0, -LETTER_RADIUS);
        ctx.globalAlpha = label === 'N' ? 1 : 0.7;
        ctx.font = `700 ${label === 'N' ? 0.07 : 0.06}px "JetBrains Mono", monospace`;
        ctx.fillText(label, 0, 0);
        ctx.restore();
    }
    return canvas;
};

const compassMaterial = (letters: THREE.Texture) =>
    new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        uniforms: {
            uColor: { value: new THREE.Color(HUD_COLOR) },
            uLetters: { value: letters },
            uHeading: { value: 0 },
        },
        vertexShader: `
            varying vec2 vUv;
            void main() {
                vUv = uv;
                vec4 view = modelViewMatrix * vec4(position, 1.0);
                view.xyz -= normalize(view.xyz) * ${FLOOR_DEPTH_BIAS.toFixed(3)};
                gl_Position = projectionMatrix * view;
            }
        `,
        fragmentShader: `
            uniform vec3 uColor;
            uniform sampler2D uLetters;
            uniform float uHeading;
            varying vec2 vUv;
            const float HALF = ${(COMPASS_SIZE / 2).toFixed(4)};
            const float RING = ${RING_RADIUS.toFixed(4)};
            float pixel;
            float stroke(float d, float halfWidth) {
                float w = max(halfWidth, pixel * 0.6);
                return clamp((w - abs(d)) / pixel + 0.5, 0.0, 1.0) * min(1.0, halfWidth / w * 1.5);
            }
            float inside(float d) {
                return clamp(d / pixel + 0.5, 0.0, 1.0);
            }
            void main() {
                vec2 p = (vUv - 0.5) * 2.0 * HALF;
                pixel = length(fwidth(p)) * 0.7;
                float r = length(p);

                float deg = degrees(atan(p.x, p.y));
                float index = floor(deg / 5.0 + 0.5);
                float arc = radians(deg - index * 5.0) * r;
                float step90 = 1.0 - step(0.5, abs(mod(index, 18.0)));
                float step45 = 1.0 - step(0.5, abs(mod(index, 9.0)));
                float step15 = 1.0 - step(0.5, abs(mod(index, 3.0)));
                float len = step90 > 0.5 ? 0.05 : step45 > 0.5 ? 0.036 : step15 > 0.5 ? 0.024 : 0.012;
                float weight = step90 > 0.5 ? 0.95 : step45 > 0.5 ? 0.7 : step15 > 0.5 ? 0.5 : 0.3;
                float width = step90 > 0.5 ? 0.003 : 0.0018;
                float tick = stroke(arc, width) * inside(RING - r) * inside(r - RING + len) * weight;

                float ring = stroke(r - RING, 0.0022) * 0.6 + stroke(r - RING + 0.065, 0.001) * 0.2;
                float letters = texture2D(uLetters, vUv).a * 0.85;

                float s = sin(uHeading);
                float c = cos(uHeading);
                vec2 q = vec2(p.x * c - p.y * s, p.x * s + p.y * c);
                float off = abs(atan(q.x, q.y));
                float glow = stroke(r - RING, 0.003) * (1.0 - smoothstep(0.06, 0.16, off));
                float tip = RING + 0.006;
                float depth = 0.04;
                float marker = inside((q.y - tip) / depth * 0.024 - abs(q.x)) * inside(q.y - tip) * inside(tip + depth - q.y);
                float lubber = stroke(q.x, 0.0015) * inside(q.y - RING + 0.065) * inside(RING - q.y) * 0.7;

                float alpha = max(max(tick, ring), max(letters, max(glow, max(marker, lubber))));
                if (alpha < 0.003) discard;
                gl_FragColor = vec4(uColor, alpha);
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

    const letters = new THREE.CanvasTexture(drawLetters());
    letters.anisotropy = 8;
    const compassMat = compassMaterial(letters);
    const compassGeo = new THREE.PlaneGeometry(COMPASS_SIZE, COMPASS_SIZE).rotateX(-Math.PI / 2);
    const compass = new THREE.Mesh(compassGeo, compassMat);
    compass.renderOrder = 1;
    group.add(compass);

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

    const update: GroundFx['update'] = (ground, track, headingDeg) => {
        grid.position.set(
            Math.round(ground.x / GRID_SNAP) * GRID_SNAP,
            ground.y - 0.001,
            Math.round(ground.z / GRID_SNAP) * GRID_SNAP,
        );
        gridMat.uniforms['uCenter']!.value.set(ground.x, ground.z);

        compass.position.copy(ground).y += 0.002;
        compassMat.uniforms['uHeading']!.value = THREE.MathUtils.degToRad(headingDeg);

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
            compassGeo.dispose();
            compassMat.dispose();
            letters.dispose();
            trailGeo.dispose();
            trailMat.dispose();
        },
    };
};

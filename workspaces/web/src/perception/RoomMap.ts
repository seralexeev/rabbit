import * as THREE from 'three';

const CHUNK_HEADER_BYTES = 12;
const GROUP_SIZE = 16;
const REBUILD_BUDGET_MS = 3;
const NEAR_M = 0.3;
const FAR_M = 2;
const LINE_ALPHA = 0.5;
const FACE_ALPHA = 0.06;

export type RoomMap = {
    group: THREE.Group;
    apply: (session: string, payload: Uint8Array) => void;
    setRobot: (position: THREE.Vector3) => void;
    flush: () => void;
    dispose: () => void;
};

const vertexShader = `
    out vec3 vWorld;
    out vec3 vBary;
    void main() {
        int corner = gl_VertexID % 3;
        vBary = vec3(corner == 0, corner == 1, corner == 2);
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        gl_Position = projectionMatrix * viewMatrix * world;
    }
`;

const fragmentShader = `
    uniform vec3 uRobot;
    uniform float uNear;
    uniform float uFar;
    uniform float uLineAlpha;
    uniform float uFaceAlpha;
    in vec3 vWorld;
    in vec3 vBary;
    out vec4 outColor;
    const vec3 RED = vec3(1.0, 0.29, 0.23);
    const vec3 AMBER = vec3(1.0, 0.71, 0.28);
    const vec3 GREEN = vec3(0.24, 1.0, 0.48);
    void main() {
        float edge = min(min(vBary.x, vBary.y), vBary.z);
        float line = 1.0 - smoothstep(0.0, fwidth(edge) * 1.2, edge);
        float t = clamp((distance(vWorld, uRobot) - uNear) / (uFar - uNear), 0.0, 1.0);
        vec3 color = t < 0.5 ? mix(RED, AMBER, t * 2.0) : mix(AMBER, GREEN, (t - 0.5) * 2.0);
        float alpha = max(line * uLineAlpha, uFaceAlpha);
        outColor = vec4(color * (0.35 + 0.65 * line), alpha);
    }
`;

export const createRoomMap = (): RoomMap => {
    const chunks = new Map<number, Float32Array>();
    const groups = new Map<number, THREE.Mesh>();
    const group = new THREE.Group();
    const material = new THREE.ShaderMaterial({
        glslVersion: THREE.GLSL3,
        vertexShader,
        fragmentShader,
        transparent: true,
        side: THREE.DoubleSide,
        uniforms: {
            uRobot: { value: new THREE.Vector3() },
            uNear: { value: NEAR_M },
            uFar: { value: FAR_M },
            uLineAlpha: { value: LINE_ALPHA },
            uFaceAlpha: { value: FACE_ALPHA },
        },
    });

    let session: string | null = null;
    const dirty = new Set<number>();

    const removeGroup = (key: number) => {
        const mesh = groups.get(key);
        if (mesh == null) return;
        group.remove(mesh);
        mesh.geometry.dispose();
        groups.delete(key);
    };

    const clear = () => {
        for (const key of [...groups.keys()]) removeGroup(key);
        chunks.clear();
        dirty.clear();
    };

    const rebuild = (key: number) => {
        const members: number[] = [];
        let length = 0;
        for (let index = key * GROUP_SIZE; index < (key + 1) * GROUP_SIZE; index++) {
            const positions = chunks.get(index);
            if (positions == null) continue;
            members.push(index);
            length += positions.length;
        }
        if (length === 0) {
            removeGroup(key);
            return;
        }
        const merged = new Float32Array(length);
        let offset = 0;
        for (const index of members) {
            const positions = chunks.get(index)!;
            merged.set(positions, offset);
            chunks.set(index, merged.subarray(offset, offset + positions.length));
            offset += positions.length;
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(merged, 3));
        geometry.computeBoundingSphere();
        const mesh = groups.get(key);
        if (mesh == null) {
            const created = new THREE.Mesh(geometry, material);
            created.matrixAutoUpdate = false;
            groups.set(key, created);
            group.add(created);
        } else {
            mesh.geometry.dispose();
            mesh.geometry = geometry;
        }
    };

    const apply = (nextSession: string, payload: Uint8Array) => {
        if (nextSession !== session) {
            session = nextSession;
            clear();
        }

        const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
        let offset = 0;
        while (offset + CHUNK_HEADER_BYTES <= payload.byteLength) {
            const index = view.getUint32(offset, true);
            const vertexCount = view.getUint32(offset + 4, true);
            const triangleCount = view.getUint32(offset + 8, true);
            const start = offset;
            offset += CHUNK_HEADER_BYTES;
            const vertices = offset;
            offset += vertexCount * 6;
            const triangles = offset;
            offset += triangleCount * 6;
            offset += (4 - ((offset - start) % 4)) % 4;
            if (offset > payload.byteLength) break;

            dirty.add(Math.floor(index / GROUP_SIZE));
            if (vertexCount === 0 || triangleCount === 0) {
                chunks.delete(index);
                continue;
            }

            const positions = new Float32Array(triangleCount * 9);
            for (let t = 0; t < triangleCount * 3; t++) {
                const vertex = Math.min(view.getUint16(triangles + t * 2, true), vertexCount - 1);
                const source = vertices + vertex * 6;
                positions[t * 3] = view.getInt16(source, true) / 1000;
                positions[t * 3 + 1] = view.getInt16(source + 2, true) / 1000;
                positions[t * 3 + 2] = view.getInt16(source + 4, true) / 1000;
            }
            chunks.set(index, positions);
        }
    };

    const flush = () => {
        const start = performance.now();
        for (const key of dirty) {
            dirty.delete(key);
            rebuild(key);
            if (performance.now() - start > REBUILD_BUDGET_MS) return;
        }
    };

    return {
        group,
        apply,
        flush,
        setRobot: (position) => {
            material.uniforms['uRobot']!.value.copy(position);
        },
        dispose: () => {
            clear();
            material.dispose();
        },
    };
};

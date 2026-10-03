import * as THREE from 'three';

import type { FloorPlan } from './FloorPlan.ts';
import { cellKey, voxelGeometry } from './voxelMesh.ts';

export type MapStyle = 'surface' | 'voxel';

const CHUNK_HEADER_BYTES = 24;
const GROUP_SIZE = 16;
const REBUILD_BUDGET_MS = 3;
const FOG_DENSITY = 0.08;

export type RoomMap = {
    group: THREE.Group;
    apply: (session: string, payload: Uint8Array) => void;
    reset: () => void;
    setRobot: (position: THREE.Vector3) => void;
    setStyle: (style: MapStyle) => void;
    setCut: (height: number) => void;
    flush: () => void;
    dispose: () => void;
};

type Chunk = { positions: Float32Array; indices: Uint16Array; cells: number[] };

const uniformsGlsl = `
    uniform vec3 uRobot;
    uniform float uCut;
    uniform vec3 uFogColor;
    uniform float uFogDensity;
    const vec3 GLOW = vec3(0.4, 0.95, 1.0);
    const vec3 WARN = vec3(1.0, 0.55, 0.22);

    float obstacleTint(vec3 world) {
        float near = 1.0 - smoothstep(0.35, 1.3, distance(world.xz, uRobot.xz));
        return near * step(0.04, world.y) * (1.0 - step(0.45, world.y));
    }

    vec3 fogged(vec3 color, vec3 world) {
        float fog = 1.0 - exp(-pow(uFogDensity * distance(cameraPosition, world), 2.0));
        return mix(color, uFogColor, fog);
    }
`;

const surfaceVertex = `
    out vec3 vWorld;
    out vec3 vNormal;
    void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        vNormal = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * viewMatrix * world;
    }
`;

const surfaceFragment = `
    ${uniformsGlsl}
    const vec3 FLOOR = vec3(0.02, 0.07, 0.09);
    const vec3 LOW = vec3(0.04, 0.17, 0.22);
    const vec3 HIGH = vec3(0.16, 0.38, 0.46);
    const vec3 LIGHT = vec3(0.37, 0.86, 0.35);
    in vec3 vWorld;
    in vec3 vNormal;
    out vec4 outColor;
    void main() {
        if (vWorld.y > uCut) discard;
        vec3 normal = normalize(vNormal) * (gl_FrontFacing ? 1.0 : -1.0);
        float h = vWorld.y;
        vec3 view = normalize(cameraPosition - vWorld);
        float floorness = smoothstep(0.8, 0.95, abs(normal.y)) * (1.0 - smoothstep(0.06, 0.16, h));
        vec3 base = mix(mix(LOW, HIGH, smoothstep(0.0, 2.0, h)), FLOOR, floorness);
        float diffuse = 0.55 + 0.45 * max(dot(normal, LIGHT), 0.0);
        float rim = pow(1.0 - abs(dot(normal, view)), 2.5);
        vec3 color = base * diffuse + GLOW * rim * 0.55 * (1.0 - floorness);

        float level = h * 4.0;
        float contour = (1.0 - min(abs(fract(level - 0.5) - 0.5) / fwidth(level), 1.0)) * (1.0 - abs(normal.y));
        vec2 cell = vWorld.xz * 2.0;
        vec2 grid = abs(fract(cell - 0.5) - 0.5) / fwidth(cell);
        float gridLine = (1.0 - min(min(grid.x, grid.y), 1.0)) * floorness;
        color += GLOW * (contour * 0.45 + gridLine * 0.22);
        color = mix(color, WARN, obstacleTint(vWorld) * 0.55);
        color += GLOW * (1.0 - smoothstep(0.0, 0.035, uCut - h)) * 0.7;
        outColor = vec4(fogged(color, vWorld), 1.0);
    }
`;

const voxelVertex = `
    uniform float uCut;
    in float aOcclusion;
    in vec2 aFace;
    in vec3 aCell;
    out vec3 vWorld;
    out vec3 vNormal;
    out float vOcclusion;
    out vec2 vFace;
    out vec3 vCell;
    void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        vNormal = normal;
        vOcclusion = aOcclusion;
        vFace = aFace;
        vCell = aCell;
        gl_Position = aCell.y > uCut ? vec4(2.0, 2.0, 2.0, 1.0) : projectionMatrix * viewMatrix * world;
    }
`;

const voxelFragment = `
    ${uniformsGlsl}
    const vec3 FLOOR = vec3(0.05, 0.16, 0.2);
    const vec3 LOW = vec3(0.1, 0.36, 0.44);
    const vec3 HIGH = vec3(0.42, 0.78, 0.86);
    in vec3 vWorld;
    in vec3 vNormal;
    in float vOcclusion;
    in vec2 vFace;
    in vec3 vCell;
    out vec4 outColor;
    void main() {
        float h = vCell.y;
        float top = step(0.5, vNormal.y);
        float bottom = step(0.5, -vNormal.y);
        vec3 base = mix(LOW, HIGH, smoothstep(0.0, 1.8, h));
        base = mix(base, FLOOR, 1.0 - smoothstep(0.05, 0.12, h));
        base *= 0.9 + 0.2 * fract(sin(dot(vCell, vec3(12.9898, 78.233, 37.719))) * 43758.5453);
        float face = top > 0.5 ? 1.12 : bottom > 0.5 ? 0.5 : 0.74 + 0.1 * vNormal.x + 0.05 * vNormal.z;
        vec3 color = base * face * (0.42 + 0.193 * vOcclusion);

        vec2 border = min(vFace, 1.0 - vFace);
        float edge = min(border.x, border.y);
        color *= 1.0 - 0.16 * (1.0 - smoothstep(0.0, 0.05 + fwidth(edge) * 1.5, edge));
        color = mix(color, WARN * face, obstacleTint(vCell) * 0.5);
        color += GLOW * top * (1.0 - smoothstep(0.0, 0.08, uCut - h)) * 0.45;
        outColor = vec4(fogged(color, vWorld), 1.0);
    }
`;

const createMaterial = (
    vertexShader: string,
    fragmentShader: string,
    uniforms: Record<string, THREE.IUniform>,
    side: THREE.Side,
) =>
    new THREE.ShaderMaterial({
        glslVersion: THREE.GLSL3,
        vertexShader,
        fragmentShader,
        side,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 4,
        uniforms,
    });

const surfaceGeometry = (members: Chunk[]) => {
    let vertexCount = 0;
    let indexCount = 0;
    for (const chunk of members) {
        vertexCount += chunk.positions.length / 3;
        indexCount += chunk.indices.length;
    }
    const positions = new Float32Array(vertexCount * 3);
    const indices = vertexCount > 65535 ? new Uint32Array(indexCount) : new Uint16Array(indexCount);
    let vertexOffset = 0;
    let indexOffset = 0;
    for (const chunk of members) {
        positions.set(chunk.positions, vertexOffset * 3);
        for (let i = 0; i < chunk.indices.length; i++) indices[indexOffset + i] = chunk.indices[i]! + vertexOffset;
        vertexOffset += chunk.positions.length / 3;
        indexOffset += chunk.indices.length;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    return geometry;
};

const chunkCells = (positions: Float32Array, indices: Uint16Array) => {
    const cells = new Set<number>();
    for (let i = 0; i < positions.length; i += 3) cells.add(cellKey(positions[i]!, positions[i + 1]!, positions[i + 2]!));
    for (let t = 0; t < indices.length; t += 3) {
        let x = 0;
        let y = 0;
        let z = 0;
        for (let k = 0; k < 3; k++) {
            const vertex = indices[t + k]! * 3;
            x += positions[vertex]!;
            y += positions[vertex + 1]!;
            z += positions[vertex + 2]!;
        }
        cells.add(cellKey(x / 3, y / 3, z / 3));
    }
    return [...cells];
};

export const createRoomMap = (floorPlan: Pick<FloorPlan, 'reset' | 'chunk'>, fogColor: THREE.Color): RoomMap => {
    const chunks = new Map<number, Chunk>();
    const groups = new Map<number, THREE.Mesh>();
    const occupancy = new Map<number, number>();
    const group = new THREE.Group();
    const uniforms = {
        uRobot: { value: new THREE.Vector3() },
        uCut: { value: 2.2 },
        uFogColor: { value: fogColor },
        uFogDensity: { value: FOG_DENSITY },
    };
    const surfaceMaterial = createMaterial(surfaceVertex, surfaceFragment, uniforms, THREE.DoubleSide);
    const voxelMaterial = createMaterial(voxelVertex, voxelFragment, uniforms, THREE.FrontSide);
    const occupied = (key: number) => occupancy.has(key);

    let session: string | null = null;
    let retired: string | null = null;
    let style: MapStyle = 'voxel';
    const dirty = new Set<number>();

    const occupy = (cells: number[], delta: 1 | -1) => {
        for (const key of cells) {
            const count = (occupancy.get(key) ?? 0) + delta;
            if (count > 0) occupancy.set(key, count);
            else occupancy.delete(key);
        }
    };

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
        occupancy.clear();
        dirty.clear();
    };

    const rebuild = (key: number) => {
        const members: Chunk[] = [];
        for (let index = key * GROUP_SIZE; index < (key + 1) * GROUP_SIZE; index++) {
            const chunk = chunks.get(index);
            if (chunk != null) members.push(chunk);
        }
        removeGroup(key);
        if (members.length === 0) return;
        let mesh: THREE.Mesh;
        if (style === 'surface') {
            mesh = new THREE.Mesh(surfaceGeometry(members), surfaceMaterial);
        } else {
            const cells = new Set<number>();
            for (const chunk of members) for (const cell of chunk.cells) cells.add(cell);
            mesh = new THREE.Mesh(voxelGeometry(cells, occupied), voxelMaterial);
        }
        mesh.matrixAutoUpdate = false;
        groups.set(key, mesh);
        group.add(mesh);
    };

    const apply = (nextSession: string, payload: Uint8Array) => {
        if (nextSession === retired) return;
        if (nextSession !== session) {
            session = nextSession;
            clear();
            floorPlan.reset();
        }

        const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
        let offset = 0;
        while (offset + CHUNK_HEADER_BYTES <= payload.byteLength) {
            const index = view.getUint32(offset, true);
            const vertexCount = view.getUint32(offset + 4, true);
            const triangleCount = view.getUint32(offset + 8, true);
            const originX = view.getFloat32(offset + 12, true);
            const originY = view.getFloat32(offset + 16, true);
            const originZ = view.getFloat32(offset + 20, true);
            const start = offset;
            offset += CHUNK_HEADER_BYTES;
            const vertices = offset;
            offset += vertexCount * 6;
            const triangles = offset;
            offset += triangleCount * 6;
            offset += (4 - ((offset - start) % 4)) % 4;
            if (offset > payload.byteLength) break;

            dirty.add(Math.floor(index / GROUP_SIZE));
            const previous = chunks.get(index);
            if (previous != null) occupy(previous.cells, -1);
            if (vertexCount === 0 || triangleCount === 0) {
                chunks.delete(index);
                floorPlan.chunk(index, null);
                continue;
            }

            const positions = new Float32Array(vertexCount * 3);
            for (let v = 0; v < vertexCount; v++) {
                positions[v * 3] = originX + view.getInt16(vertices + v * 6, true) / 1000;
                positions[v * 3 + 1] = originY + view.getInt16(vertices + v * 6 + 2, true) / 1000;
                positions[v * 3 + 2] = originZ + view.getInt16(vertices + v * 6 + 4, true) / 1000;
            }
            const indices = new Uint16Array(triangleCount * 3);
            const soup = new Float32Array(triangleCount * 9);
            for (let t = 0; t < triangleCount * 3; t++) {
                const vertex = Math.min(view.getUint16(triangles + t * 2, true), vertexCount - 1);
                indices[t] = vertex;
                soup[t * 3] = positions[vertex * 3]!;
                soup[t * 3 + 1] = positions[vertex * 3 + 1]!;
                soup[t * 3 + 2] = positions[vertex * 3 + 2]!;
            }
            const cells = chunkCells(positions, indices);
            occupy(cells, 1);
            chunks.set(index, { positions, indices, cells });
            floorPlan.chunk(index, soup);
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
        reset: () => {
            retired = session;
            session = null;
            clear();
            floorPlan.reset();
        },
        flush,
        setRobot: (position) => {
            uniforms.uRobot.value.copy(position);
        },
        setStyle: (next) => {
            if (next === style) return;
            style = next;
            for (const index of chunks.keys()) dirty.add(Math.floor(index / GROUP_SIZE));
        },
        setCut: (height) => {
            uniforms.uCut.value = height;
        },
        dispose: () => {
            clear();
            surfaceMaterial.dispose();
            voxelMaterial.dispose();
        },
    };
};

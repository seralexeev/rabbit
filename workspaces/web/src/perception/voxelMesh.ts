import * as THREE from 'three';

export const VOXEL_M = 0.05;

const BIAS = 2 ** 15;
const Y_STRIDE = 2 ** 16;
const X_STRIDE = 2 ** 32;

export const cellKey = (x: number, y: number, z: number) =>
    (Math.floor(x / VOXEL_M) + BIAS) * X_STRIDE +
    (Math.floor(y / VOXEL_M + 0.5) + BIAS) * Y_STRIDE +
    Math.floor(z / VOXEL_M) +
    BIAS;

const offset = (dx: number, dy: number, dz: number) => dx * X_STRIDE + dy * Y_STRIDE + dz;

const cellCenter = (key: number, out: number[]) => {
    const x = Math.floor(key / X_STRIDE);
    const y = Math.floor((key - x * X_STRIDE) / Y_STRIDE);
    const z = key - x * X_STRIDE - y * Y_STRIDE;
    out[0] = (x - BIAS + 0.5) * VOXEL_M;
    out[1] = (y - BIAS - 0.5) * VOXEL_M;
    out[2] = (z - BIAS + 0.5) * VOXEL_M;
};

type Axis = [number, number, number];
type Face = { normal: Axis; u: Axis; v: Axis };

const AXES: Axis[] = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
];

const FACES: Face[] = AXES.flatMap((axis, i) => {
    const u = AXES[(i + 1) % 3]!;
    const v = AXES[(i + 2) % 3]!;
    return [
        { normal: axis, u, v },
        { normal: [-axis[0], -axis[1], -axis[2]] as Axis, u: v, v: u },
    ];
});

const CORNERS: [number, number][] = [
    [-1, -1],
    [1, -1],
    [1, 1],
    [-1, 1],
];

const UVS: [number, number][] = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
];

export const voxelGeometry = (cells: Iterable<number>, occupied: (key: number) => boolean) => {
    const positions: number[] = [];
    const normals: number[] = [];
    const occlusion: number[] = [];
    const uvs: number[] = [];
    const centers: number[] = [];
    const indices: number[] = [];
    const center = [0, 0, 0];
    const half = VOXEL_M / 2;

    for (const cell of cells) {
        cellCenter(cell, center);
        for (const { normal, u, v } of FACES) {
            const out = offset(...normal);
            if (occupied(cell + out)) continue;
            const base = positions.length / 3;
            const ao: number[] = [];
            for (let c = 0; c < 4; c++) {
                const [su, sv] = CORNERS[c]!;
                const side1 = occupied(cell + out + offset(u[0] * su, u[1] * su, u[2] * su)) ? 1 : 0;
                const side2 = occupied(cell + out + offset(v[0] * sv, v[1] * sv, v[2] * sv)) ? 1 : 0;
                const corner = occupied(
                    cell + out + offset(u[0] * su + v[0] * sv, u[1] * su + v[1] * sv, u[2] * su + v[2] * sv),
                )
                    ? 1
                    : 0;
                ao.push(side1 && side2 ? 0 : 3 - side1 - side2 - corner);
                for (let k = 0; k < 3; k++) {
                    positions.push(center[k]! + half * (normal[k]! + su * u[k]! + sv * v[k]!));
                    normals.push(normal[k]!);
                    centers.push(center[k]!);
                }
                occlusion.push(ao[c]!);
                uvs.push(...UVS[c]!);
            }
            if (ao[0]! + ao[2]! >= ao[1]! + ao[3]!) indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
            else indices.push(base + 1, base + 2, base + 3, base + 1, base + 3, base);
        }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
    geometry.setAttribute('aOcclusion', new THREE.Float32BufferAttribute(occlusion, 1));
    geometry.setAttribute('aFace', new THREE.Float32BufferAttribute(uvs, 2));
    geometry.setAttribute('aCell', new THREE.Float32BufferAttribute(centers, 3));
    geometry.setIndex(positions.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(indices, 1) : new THREE.Uint16BufferAttribute(indices, 1));
    geometry.computeBoundingSphere();
    return geometry;
};

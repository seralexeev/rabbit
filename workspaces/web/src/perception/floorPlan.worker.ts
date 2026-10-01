/// <reference lib="webworker" />
import { CELL_M, type FloorPlanRequest, type FloorPlanTile, TILE_CELLS } from './floorPlanProtocol.ts';

const FLOOR_MAX_Y = 0.04;
const OBSTACLE_MIN_Y = 0.04;
const OBSTACLE_MAX_Y = 0.45;
const HORIZONTAL_NORMAL_Y = 0.9;
const TILE_AREA = TILE_CELLS * TILE_CELLS;
const CELL_BIAS = 2 ** 20;
const CELL_SPAN = 2 ** 21;
const TILE_BIAS = 2 ** 15;
const TILE_SPAN = 2 ** 16;
const FLOOR_RGBA = [98, 232, 255, 60] as const;
const OBSTACLE_RGBA = [214, 246, 255, 235] as const;

type Tile = { floor: Uint16Array; obstacle: Uint16Array };
type Contribution = { floor: Float64Array; obstacle: Float64Array };

const scope = self as unknown as DedicatedWorkerGlobalScope;
const tiles = new Map<number, Tile>();
const chunks = new Map<number, Contribution>();
const dirty = new Set<number>();

const tileKey = (tx: number, tz: number) => (tx + TILE_BIAS) * TILE_SPAN + (tz + TILE_BIAS);

const tileAt = (key: number) => {
    let tile = tiles.get(key);
    if (tile == null) {
        tile = { floor: new Uint16Array(TILE_AREA), obstacle: new Uint16Array(TILE_AREA) };
        tiles.set(key, tile);
    }
    return tile;
};

const count = (cells: Float64Array, layer: keyof Tile, delta: 1 | -1) => {
    for (const key of cells) {
        const cx = Math.floor(key / CELL_SPAN) - CELL_BIAS;
        const cz = (key % CELL_SPAN) - CELL_BIAS;
        const tx = Math.floor(cx / TILE_CELLS);
        const tz = Math.floor(cz / TILE_CELLS);
        const tk = tileKey(tx, tz);
        const cell = (cz - tz * TILE_CELLS) * TILE_CELLS + (cx - tx * TILE_CELLS);
        const values = tileAt(tk)[layer];
        values[cell] = Math.max(0, values[cell]! + delta);
        dirty.add(tk);
    }
};

const markCell = (out: Set<number>, x: number, z: number) => {
    out.add((Math.floor(x / CELL_M) + CELL_BIAS) * CELL_SPAN + (Math.floor(z / CELL_M) + CELL_BIAS));
};

const polygonX = new Float64Array(8);
const polygonY = new Float64Array(8);
const polygonZ = new Float64Array(8);
const clippedX = new Float64Array(8);
const clippedY = new Float64Array(8);
const clippedZ = new Float64Array(8);

const rasterize = (out: Set<number>, xs: Float64Array, zs: Float64Array, n: number) => {
    let minZ = Infinity;
    let maxZ = -Infinity;
    for (let i = 0; i < n; i++) {
        const x0 = xs[i]!;
        const z0 = zs[i]!;
        const x1 = xs[(i + 1) % n]!;
        const z1 = zs[(i + 1) % n]!;
        const steps = Math.max(1, Math.ceil(Math.hypot(x1 - x0, z1 - z0) / (CELL_M * 0.5)));
        for (let s = 0; s <= steps; s++) markCell(out, x0 + ((x1 - x0) * s) / steps, z0 + ((z1 - z0) * s) / steps);
        minZ = Math.min(minZ, z0);
        maxZ = Math.max(maxZ, z0);
    }
    for (let row = Math.ceil(minZ / CELL_M - 0.5); (row + 0.5) * CELL_M <= maxZ; row++) {
        const z = (row + 0.5) * CELL_M;
        let left = Infinity;
        let right = -Infinity;
        for (let i = 0; i < n; i++) {
            const x0 = xs[i]!;
            const z0 = zs[i]!;
            const x1 = xs[(i + 1) % n]!;
            const z1 = zs[(i + 1) % n]!;
            if ((z0 <= z && z1 > z) || (z1 <= z && z0 > z)) {
                const x = x0 + ((z - z0) / (z1 - z0)) * (x1 - x0);
                left = Math.min(left, x);
                right = Math.max(right, x);
            }
        }
        for (let col = Math.ceil(left / CELL_M - 0.5); (col + 0.5) * CELL_M <= right; col++)
            markCell(out, (col + 0.5) * CELL_M, z);
    }
};

const clipSlab = (n: number, low: number, high: number) => {
    let count = n;
    for (const [bound, keepAbove] of [
        [low, true],
        [high, false],
    ] as const) {
        let m = 0;
        for (let i = 0; i < count; i++) {
            const j = (i + 1) % count;
            const yi = polygonY[i]!;
            const yj = polygonY[j]!;
            const inI = keepAbove ? yi >= bound : yi <= bound;
            const inJ = keepAbove ? yj >= bound : yj <= bound;
            if (inI) {
                clippedX[m] = polygonX[i]!;
                clippedY[m] = yi;
                clippedZ[m++] = polygonZ[i]!;
            }
            if (inI !== inJ) {
                const t = (bound - yi) / (yj - yi);
                clippedX[m] = polygonX[i]! + (polygonX[j]! - polygonX[i]!) * t;
                clippedY[m] = bound;
                clippedZ[m++] = polygonZ[i]! + (polygonZ[j]! - polygonZ[i]!) * t;
            }
        }
        polygonX.set(clippedX.subarray(0, m));
        polygonY.set(clippedY.subarray(0, m));
        polygonZ.set(clippedZ.subarray(0, m));
        count = m;
        if (count < 3) return count;
    }
    return count;
};

const classify = (positions: Float32Array) => {
    const floor = new Set<number>();
    const obstacle = new Set<number>();
    for (let t = 0; t + 9 <= positions.length; t += 9) {
        const ax = positions[t]!;
        const ay = positions[t + 1]!;
        const az = positions[t + 2]!;
        const bx = positions[t + 3]!;
        const by = positions[t + 4]!;
        const bz = positions[t + 5]!;
        const cx = positions[t + 6]!;
        const cy = positions[t + 7]!;
        const cz = positions[t + 8]!;
        const minY = Math.min(ay, by, cy);
        const maxY = Math.max(ay, by, cy);
        const ux = bx - ax;
        const uy = by - ay;
        const uz = bz - az;
        const vx = cx - ax;
        const vy = cy - ay;
        const vz = cz - az;
        const nx = uy * vz - uz * vy;
        const ny = uz * vx - ux * vz;
        const nz = ux * vy - uy * vx;
        const length = Math.hypot(nx, ny, nz);
        polygonX[0] = ax;
        polygonY[0] = ay;
        polygonZ[0] = az;
        polygonX[1] = bx;
        polygonY[1] = by;
        polygonZ[1] = bz;
        polygonX[2] = cx;
        polygonY[2] = cy;
        polygonZ[2] = cz;
        if (maxY < FLOOR_MAX_Y && length > 0 && Math.abs(ny) / length > HORIZONTAL_NORMAL_Y) {
            rasterize(floor, polygonX, polygonZ, 3);
        } else if (maxY > OBSTACLE_MIN_Y && minY < OBSTACLE_MAX_Y) {
            const n = clipSlab(3, OBSTACLE_MIN_Y, OBSTACLE_MAX_Y);
            if (n >= 3) rasterize(obstacle, polygonX, polygonZ, n);
        }
    }
    return { floor: Float64Array.from(floor), obstacle: Float64Array.from(obstacle) };
};

const remove = (index: number) => {
    const previous = chunks.get(index);
    if (previous == null) return;
    count(previous.floor, 'floor', -1);
    count(previous.obstacle, 'obstacle', -1);
    chunks.delete(index);
};

const render = async () => {
    const out: FloorPlanTile[] = [];
    for (const key of dirty) {
        const tile = tiles.get(key);
        const tx = Math.floor(key / TILE_SPAN) - TILE_BIAS;
        const tz = (key % TILE_SPAN) - TILE_BIAS;
        if (tile == null) {
            out.push({ key, tx, tz, bitmap: null });
            continue;
        }
        const pixels = new Uint8ClampedArray(TILE_AREA * 4);
        let used = false;
        for (let i = 0; i < TILE_AREA; i++) {
            const color = tile.obstacle[i]! > 0 ? OBSTACLE_RGBA : tile.floor[i]! > 0 ? FLOOR_RGBA : null;
            if (color == null) continue;
            used = true;
            pixels.set(color, i * 4);
        }
        if (!used) {
            tiles.delete(key);
            out.push({ key, tx, tz, bitmap: null });
            continue;
        }
        out.push({ key, tx, tz, bitmap: await createImageBitmap(new ImageData(pixels, TILE_CELLS, TILE_CELLS)) });
    }
    dirty.clear();
    return out;
};

let queue = Promise.resolve();

scope.onmessage = (event: MessageEvent<FloorPlanRequest>) => {
    const request = event.data;
    queue = queue.then(async () => {
        if (request.type === 'reset') {
            for (const key of tiles.keys()) dirty.add(key);
            tiles.clear();
            chunks.clear();
        } else {
            for (const chunk of request.chunks) {
                remove(chunk.index);
                if (chunk.positions == null) continue;
                const cells = classify(chunk.positions);
                count(cells.floor, 'floor', 1);
                count(cells.obstacle, 'obstacle', 1);
                chunks.set(chunk.index, cells);
            }
        }
        const updates = await render();
        if (updates.length === 0) return;
        scope.postMessage(
            updates,
            updates.flatMap((tile) => (tile.bitmap == null ? [] : [tile.bitmap])),
        );
    });
};

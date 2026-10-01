import { L } from '../log.ts';
import { CELL_M, type FloorPlanChunk, type FloorPlanRequest, type FloorPlanTile, TILE_CELLS } from './floorPlanProtocol.ts';

const GROW_TILES = 2;

type Bounds = { tx: number; tz: number; columns: number; rows: number };

export type FloorPlanRaster = { canvas: OffscreenCanvas; x: number; z: number; width: number; height: number };

export type FloorPlan = {
    raster: () => FloorPlanRaster | null;
    version: () => number;
    reset: () => void;
    chunk: (index: number, positions: Float32Array | null) => void;
    start: () => () => void;
};

const contains = (outer: Bounds, inner: Bounds) =>
    inner.tx >= outer.tx &&
    inner.tz >= outer.tz &&
    inner.tx + inner.columns <= outer.tx + outer.columns &&
    inner.tz + inner.rows <= outer.tz + outer.rows;

const grow = (bounds: Bounds | null, needed: Bounds): Bounds => {
    const left = Math.min(bounds?.tx ?? Infinity, needed.tx - GROW_TILES);
    const top = Math.min(bounds?.tz ?? Infinity, needed.tz - GROW_TILES);
    const right = Math.max(bounds == null ? -Infinity : bounds.tx + bounds.columns, needed.tx + needed.columns + GROW_TILES);
    const bottom = Math.max(bounds == null ? -Infinity : bounds.tz + bounds.rows, needed.tz + needed.rows + GROW_TILES);
    return { tx: left, tz: top, columns: right - left, rows: bottom - top };
};

export const createFloorPlan = (): FloorPlan => {
    let worker: Worker | null = null;
    let version = 0;
    let pending: FloorPlanChunk[] = [];
    let transfer: ArrayBuffer[] = [];
    let scheduled = false;
    const present = new Set<number>();
    let bounds: Bounds | null = null;
    let raster: FloorPlanRaster | null = null;

    const send = (request: FloorPlanRequest, buffers: ArrayBuffer[] = []) => worker?.postMessage(request, buffers);

    const flush = () => {
        scheduled = false;
        if (pending.length === 0) return;
        send({ type: 'chunks', chunks: pending }, transfer);
        pending = [];
        transfer = [];
    };

    const fit = (needed: Bounds) => {
        if (raster != null && bounds != null && contains(bounds, needed)) return;
        const next = grow(bounds, needed);
        const canvas = new OffscreenCanvas(next.columns * TILE_CELLS, next.rows * TILE_CELLS);
        if (raster != null && bounds != null)
            canvas
                .getContext('2d')!
                .drawImage(raster.canvas, (bounds.tx - next.tx) * TILE_CELLS, (bounds.tz - next.tz) * TILE_CELLS);
        bounds = next;
        raster = {
            canvas,
            x: next.tx * TILE_CELLS * CELL_M,
            z: next.tz * TILE_CELLS * CELL_M,
            width: next.columns * TILE_CELLS * CELL_M,
            height: next.rows * TILE_CELLS * CELL_M,
        };
    };

    const receive = (event: MessageEvent<FloorPlanTile[]>) => {
        let minX = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxZ = -Infinity;
        for (const tile of event.data) {
            if (tile.bitmap == null) continue;
            minX = Math.min(minX, tile.tx);
            minZ = Math.min(minZ, tile.tz);
            maxX = Math.max(maxX, tile.tx);
            maxZ = Math.max(maxZ, tile.tz);
        }
        if (Number.isFinite(minX)) fit({ tx: minX, tz: minZ, columns: maxX - minX + 1, rows: maxZ - minZ + 1 });
        const context = raster?.canvas.getContext('2d');
        for (const tile of event.data) {
            if (context != null && bounds != null && (tile.bitmap != null || present.has(tile.key))) {
                const px = (tile.tx - bounds.tx) * TILE_CELLS;
                const py = (tile.tz - bounds.tz) * TILE_CELLS;
                context.clearRect(px, py, TILE_CELLS, TILE_CELLS);
                if (tile.bitmap != null) context.drawImage(tile.bitmap, px, py);
            }
            tile.bitmap?.close();
            if (tile.bitmap == null) present.delete(tile.key);
            else present.add(tile.key);
        }
        version++;
    };

    const clear = () => {
        present.clear();
        bounds = null;
        raster = null;
        version++;
    };

    return {
        raster: () => (present.size === 0 ? null : raster),
        version: () => version,
        reset: () => {
            pending = [];
            transfer = [];
            send({ type: 'reset' });
        },
        chunk: (index, positions) => {
            if (worker == null) return;
            const copy = positions?.slice() ?? null;
            pending.push({ index, positions: copy });
            if (copy != null) transfer.push(copy.buffer);
            if (scheduled) return;
            scheduled = true;
            queueMicrotask(flush);
        },
        start: () => {
            const created = new Worker(new URL('./floorPlan.worker.ts', import.meta.url), { type: 'module' });
            created.onmessage = receive;
            created.onerror = (error) => L.error('Floor plan worker failed', error);
            worker = created;
            return () => {
                created.terminate();
                if (worker === created) worker = null;
                pending = [];
                transfer = [];
                clear();
            };
        },
    };
};

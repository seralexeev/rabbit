export const CELL_M = 0.05;
export const TILE_CELLS = 64;

export type FloorPlanChunk = { index: number; positions: Float32Array | null };

export type FloorPlanRequest = { type: 'reset' } | { type: 'chunks'; chunks: FloorPlanChunk[] };

export type FloorPlanTile = { key: number; tx: number; tz: number; bitmap: ImageBitmap | null };

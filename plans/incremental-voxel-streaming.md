# Incremental Voxel Streaming Architecture

## Context

The current nvblox pipeline serializes **all** ~48K surface voxels (~710KB) every 10s and pushes the full blob through NATS Object Store. This causes:
- NATS timeouts (Object Store `put()` requires JetStream round-trips that stall when GPU blocks the event loop)
- 17GB total NATS I/O — mostly wasted re-sending unchanged voxels
- Full InstancedMesh rebuild on every update in the browser
- Won't scale beyond a single room (~200-500K voxels for a house)

**Goal:** Block-level incremental deltas over regular NATS pub/sub. Only send what changed. Client maintains its own voxel map.

---

## Hardware Constraints (Jetson Orin Nano)

| Resource | Total | Used | Available |
|----------|-------|------|-----------|
| RAM (unified) | 7.4GB | 4.3GB | ~3GB |
| GPU mem (nvblox) | — | ~470MB | limited |
| CPU | 6 cores | ZED saturates 2 | 4 cores |
| Power | — | 9W | — |
| NATS max_payload | 64MB | — | — |
| NATS WS | compressed + TLS | — | — |

**Key rule:** No solution that doubles memory on the Jetson side.

---

## Architecture Overview

```
nvblox (Jetson)                    NATS                    Browser
┌──────────────────┐          ┌──────────┐          ┌──────────────────┐
│ TSDF mapper      │          │          │          │ VoxelMap         │
│                  │ delta    │ pub/sub  │  WS+TLS  │ (Map<blockKey,   │
│ Block diff engine├─────────>│ .delta   ├─────────>│  slotIndices[]>) │
│                  │ ~5-30KB  │          │          │                  │
│                  │ snapshot │          │          │ InstancedMesh    │
│                  ├─────────>│ .snapshot├─────────>│ (pre-allocated   │
│                  │ ~2MB/60s │          │          │  256K instances) │
│                  │          │          │ request  │                  │
│                  │<─────────┤ .request │<─────────┤ (on connect/gap) │
└──────────────────┘          └──────────┘          └──────────────────┘
```

**Three NATS subjects (regular pub/sub, NOT Object Store):**
- `rabbit.nvblox.voxels.delta` — block-level diffs every 2s
- `rabbit.nvblox.voxels.snapshot` — full state, every 60s or on request
- `rabbit.nvblox.voxels.request` — client requests a snapshot

---

## Binary Protocol

### Delta Message (sent every ~2s)

```
Byte   Size    Field
0      1       msg_type = 0x01
1      4       sequence (u32 LE, monotonic)
5      4       voxel_size (f32 LE)
9      4       num_remove_blocks (u32 LE)
13     4       num_upsert_blocks (u32 LE)
17     R*12    remove_blocks: int32[3] per block (block indices to delete)
...    ...     upsert_blocks: for each block:
                 block_index: int32[3]  (12 bytes)
                 num_voxels: u16 LE     (2 bytes)
                 voxels[]: (f32[3] pos + u8[3] color) * num_voxels  (15 bytes each)
```

**Block-level granularity:** When a block changes, the client replaces ALL voxels in that block. This avoids per-voxel tracking on the backend (saves memory).

### Snapshot Message (recovery, every 60s)

```
Byte   Size    Field
0      1       msg_type = 0x02
1      4       sequence (u32 LE)
5      4       num_voxels (u32 LE)
9      4       voxel_size (f32 LE)
13     N*15    voxels[]: f32[3] pos + u8[3] color
```

### LZ4 Compression

Entire payload is LZ4-compressed. Client decompresses first, then reads type byte. `lz4js` already in web `package.json`. Expected compression: 2-4x on voxel data.

---

## Backend Changes — `nvblox.py`

### New State

```python
self._prev_block_set: set[tuple[int,int,int]] = set()
self._prev_block_sigs: dict[tuple[int,int,int], int] = {}  # CRC32 per block
self._sequence: int = 0
```

Memory cost: ~440KB at 10K blocks. Negligible.

### Block Diffing Algorithm (`_extract_voxel_delta`)

Runs in `run_in_executor` with `_mapper_lock`:

1. `get_all_blocks()` → iterate blocks, extract surface voxels per block
2. For each block: compute CRC32 of surface voxel positions (quantized to avoid float noise)
3. Compare block index set: `added = current - prev`, `removed = prev - current`
4. Compare CRC32 for common blocks: `changed = {b for b in common if sig[b] != prev_sig[b]}`
5. Upsert blocks = added + changed (with their voxels, height-colored)
6. Remove blocks = removed
7. Update `_prev_block_set` and `_prev_block_sigs`
8. Serialize to delta format, LZ4 compress

### Publishing

```python
async def publish_voxel_delta(self):
    result = await loop.run_in_executor(None, self._extract_voxel_delta)
    if result and (result has upserts or removes):
        self._sequence += 1
        await self.nc.publish("rabbit.nvblox.voxels.delta", payload,
                              headers={"seq": str(self._sequence)})
```

### Snapshot Support

- `_build_full_snapshot()`: extracts all surface voxels (same as current), serializes as snapshot format
- `publish_full_snapshot()`: periodic (60s), publishes on `.snapshot` subject
- `on_snapshot_request(msg)`: triggered by client request, publishes snapshot

### Interval Changes

- Delta: every **2s** (was 10s) — deltas are small
- Snapshot: every **60s** — recovery only
- `process_frame`: every **0.1s** (unchanged)

---

## Frontend Changes — `PointCloud.tsx`

### VoxelMap Class

```typescript
class VoxelMap {
    private blockSlots = new Map<string, number[]>();  // "x,y,z" -> slot indices
    private freeSlots: number[] = [];
    private nextSlot = 0;
    lastSeq = 0;

    allocSlot(): number;           // pop freeSlots or nextSlot++
    freeBlockSlots(key: string);   // free all slots for a block, set scale=0
    get activeCount(): number;     // max allocated slot + 1 (for mesh.count)
}
```

### Pre-allocated InstancedMesh

```typescript
const MAX_INSTANCES = 262144; // 256K — ~20MB GPU memory
const voxelMesh = new THREE.InstancedMesh(blockGeometry, blockMaterial, MAX_INSTANCES);
voxelMesh.count = 0; // render nothing initially
scene.add(voxelMesh);
```

All unused instances hidden (never rendered because `mesh.count` is kept tight).

### Subscriptions (replace Object Store watcher)

```
nc.subscribe('rabbit.nvblox.voxels.delta', callback)
nc.subscribe('rabbit.nvblox.voxels.snapshot', callback)
nc.publish('rabbit.nvblox.voxels.request', ...)  // on mount
```

### Sequence Gap Detection

If `received_seq != lastSeq + 1` and `lastSeq != 0`: request full snapshot, skip delta.

### Remove

- `useObjectStoreSubscribe` import and usage
- `readStream()` helper (no longer needed)
- `parseVoxelBuffer()` (replaced by new parsers)

---

## Files to Modify

| File | Changes |
|------|---------|
| `workspaces/rabbit/src/node/nvblox.py` | Block diffing, delta/snapshot serialization, switch to `nc.publish()` |
| `workspaces/web/src/perception/PointCloud.tsx` | VoxelMap class, delta/snapshot parsers, pre-allocated InstancedMesh, NATS pub/sub subscriptions |

No changes needed to `node.py`, `NatsProvider.tsx`, or NATS config.

---

## Size Estimates

| Scenario | Current | New (delta) | New (snapshot) |
|----------|---------|-------------|----------------|
| Static scene | 710KB/10s | 0 bytes (no changes) | 710KB/60s |
| Robot moving | 710KB/10s | ~5-30KB/2s | 710KB/60s |
| Full room (200K voxels) | 3MB/10s | ~10-50KB/2s | 3MB/60s |
| Full house (500K voxels) | 7.5MB/10s (would timeout) | ~20-100KB/2s | 7.5MB/60s |

Network I/O reduction: **~50-100x** for typical operation.

---

## Verification

1. Start robot, let it map for 30s
2. Check nvblox logs: should show `delta upserts=X removes=Y` with small numbers after initial burst
3. Browser should show voxels appearing incrementally
4. Orbit camera, wait — voxels should persist (client-side state)
5. Refresh browser — should get full snapshot on connect, then deltas
6. Move robot to new area — new blocks appear as green/red/gray
7. Check NATS dashboard: network I/O should be dramatically lower
8. Monitor `docker stats` — nvblox memory should not increase significantly

# Room map with ZED SDK spatial mapping (superseded by nvblox)

Date: 2026-10-01, 09:22–21:41 UTC. Replaced on 2026-10-02 by nvblox (`2026-10-02-nvblox.md`).

## Goal

"A full model of the room": a persistent map that survives restarts, streams to the HUD and feeds exploration.

## What was done

1. **ZED SDK 5.2.3 → 5.5.0** (`docker/Dockerfile.zed`, base image `stereolabs/zed:5.5.0-tools-devel-jetson-jp6.1.0`; `src/pyzed/sl.pyi` regenerated from the 5.5 wheel). 5.5 adds `compute_preference` and a cheaper GEN_3 `grab()` on Jetson.
2. **Old pipeline removed.** The August 2025 nvblox_torch node, its Dockerfile, the torch 2.3.0 / torchvision 0.18 wheels, the depth "sensor bundle" (about 10 MB/s on the bus), `node/perception.py` and `lib/occupancy.py` were deleted. Mapping moved into `zed.py` using the SDK's spatial mapping, with GEN_3 tracking and area memory (`room.area`) for relocalization after restarts.
3. **Wire format** (`lib/spatial_map.py`): `rabbit.map.chunks` sends only changed chunks; `rabbit.map.snapshot` (request/reply) returns all of them. First a coloured fused point cloud (9 bytes per point), then from 11:12 UTC a triangle mesh: int16 millimetre vertices + uint16 indices. At 21:38 UTC the header became `<IIIfff` with a float32 per-chunk origin, because a pose runaway to z = −138 m overflowed int16 millimetres (±32 m) and the map rendered as garbage (`02bbd54`). Decoders live in three places and change together: `lib/spatial_map.py`, `web/src/perception/RoomMap.ts`, Forge `src/streams.ts`.
4. **Memory.** `rabbit-zed` reached 5.4 GB RSS of 7.4 GB. A per-feature probe (HD720, 30 fps):

   | Tracking | Area memory | Mapping | RSS |
   |---|---|---|---|
   | GEN_3 | on | on | 2958 MB |
   | GEN_3 | off | on | 2500 MB |
   | GEN_1 | on | on | 2493 MB |
   | GEN_3 | on | off | 888 MB |

   Spatial mapping alone was about 2 GB. Settings changed to 5 cm resolution, 4 m range, `max_memory_usage = 1024`, `use_chunk_only`: stable at 3.05–3.2 GB.
5. **Quality tuning** (12:10–12:34 UTC), measured with a static 30 s harness on the robot:

   | Config | Triangles | Floor std | Below floor | Components |
   |---|---|---|---|---|
   | defaults (confidence 95 / texture 100) | 22264 | 20.5 mm | 8.25 % | 130 |
   | + mesh filter MEDIUM | 9793 | 18.3 mm | 0.02 % | 1 |
   | confidence 50 / texture 90, range 4, stability 4, filter LOW (chosen) | 19359 | 14.4 mm | 0.51 % | 2 |

   `depth_maximum_distance = 3.5` put 13–16 % of points below the floor and was not used.
6. **Dead end: strict depth confidence.** With confidence 50 / texture 90 the camera discarded 80–90 % of depth in front of a white textureless wall in dim light. The obstacle scan reported `blind`, nav refused to drive and exploration found no reachable frontiers. The thresholds went back to 95/100, and the blindness check moved from the image centre to the floor strip 0.33–0.75 m ahead. Exploration then drove 6.02 m in 46 s, at the cost of a noisier map (floor std 27 mm, 906 components). The same depth feeds the map and obstacle sensing, so map cleanliness and obstacle density compete.
7. **Dead end: mesh filter.** `Mesh.filter` costs 0.25–0.64 s on a small map and 2 s at about 150k triangles. It held the GIL, froze the camera loop (pose fell to 6.6/s, capture gaps up to 2.5 s) and, because filtering changed every chunk, the whole map was resent every 3 s (870 KB/s, 85 % of the traffic). It was removed from the live loop; map work got an adaptive interval capped at 5 % of the time (`MAP_WORK_BUDGET`); map traffic fell about 10×.
8. **Persistence.** Only `room.area` was saved, so each deploy cleared the HUD map. From `02bbd54` the encoded chunks were saved to `room.chunks` and loaded as a base layer after relocalization. Mapping waits for relocalization; nothing is saved before relocalizing; zero-confidence poses are not published.
9. **Static re-meshing.** Standing still, the SDK rebuilt nearly every chunk (926 of 4947 chunks resent byte-identical in one sample); the request interval while static went to 15 s.

## Why it was replaced

On 2026-10-02 the research and benchmarks showed: ZED spatial mapping holds about 2 GB of RAM, never corrects its mesh after loop closures, never forgets, and stops integrating at `max_memory_usage`. nvblox gave a fuller map in about 200 MB. See `2026-10-02-nvblox.md`.

## Commits

`ac133e3` (first commit of all of this), `02bbd54` (origin per chunk, mesh persistence), Forge `61b25e5` (decoder).

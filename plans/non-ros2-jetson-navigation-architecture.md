# Non-ROS2 Jetson Navigation Architecture

## Purpose

Define a practical, high-performance perception and navigation architecture for this repo on an NVIDIA Jetson Orin Nano, using the existing Python + NATS stack and `nvblox_torch`, with no ROS2 dependency.

This plan is optimized for:

- Jetson Orin Nano unified memory constraints
- ZED + nvblox co-residency on one device
- low-latency manual navigation
- future autonomous pathfinding
- stable operation in a house-scale environment

---

## What The Repo Has Today

Current relevant nodes and infrastructure:

- `rabbit-zed`: camera, depth, and pose publishing
- `rabbit-nvblox`: TSDF integration and voxel streaming
- `rabbit-roboclaw`: motor control
- `rabbit-steering`: steering control
- `nats`: system message bus

Important current characteristics:

- `rabbit-zed` publishes `frame`, `depth`, and `pose` as separate streams
- `rabbit-nvblox` integrates the latest available values opportunistically
- the web app consumes voxel deltas/snapshots for visualization
- there is no dedicated traversability, ESDF, or planner node yet

Main structural gap:

- the current mapping pipeline is still visualization-first, not navigation-first

---

## Design Principles

### 1. Single Ownership Of Expensive Resources

On Orin Nano, the GPU and unified memory are the scarce resources. Expensive operations must have clear ownership:

- one capture actor owns ZED device access
- one mapper actor owns `Mapper` mutation
- one planner actor owns navigation graph/state

Avoid multiple independent loops touching the same mutable state.

### 2. Multi-Rate Pipeline

Not every product needs the camera rate.

Recommended steady-state rates:

- capture bundle creation: `15-30 Hz`
- local depth integration: `10-15 Hz`
- color integration: `2-5 Hz` or disabled for nav mode
- local ESDF update: `3-5 Hz`
- local traversability update: `3-5 Hz`
- planner replanning: `2-10 Hz` depending on mode
- voxel UI deltas: `1-2 Hz`
- full snapshots: `30-60 s`

### 3. Local Map + Global Map

One map cannot serve every purpose efficiently.

- local map: high resolution, small radius, collision and local planning
- global map: coarse resolution, large radius, route planning and exploration

### 4. Navigation Uses ESDF And Traversability

Surface voxels are for rendering and operator understanding.

Navigation should rely on:

- ESDF clearance
- footprint inflation
- floor continuity
- overhead clearance
- obstacle persistence / decay

### 5. NATS Is The Control Plane, Not Necessarily The Sensor Fast Path

NATS remains the right system bus for:

- commands
- state
- planner goals
- health
- UI updates
- snapshots and deltas

For large local sensor payloads on the same Jetson, a direct local IPC fast path is preferred.

---

## Target Node Topology

### `rabbit-zed-capture`

Responsibility:

- owns the ZED camera
- produces synchronized frame bundles
- publishes low-rate operator video
- publishes camera intrinsics and diagnostics

Outputs:

- `rabbit.sensor.bundle.local`
- `rabbit.zed.pose`
- `rabbit.zed.frame.preview`
- `rabbit.zed.intrinsics`
- `rabbit.zed.health`

Notes:

- do one capture pass per frame
- bundle `frame_number`, `timestamp`, `pose`, `depth`, and optional `rgb`
- stop publishing raw image/depth/pose as unrelated streams for mapper consumption

### `rabbit-map-local`

Responsibility:

- owns the local high-resolution `nvblox` mapper
- integrates synchronized bundles
- updates local ESDF
- emits semantic voxel deltas for UI
- provides local map queries for navigation

Recommended config:

- integrator: `TSDF`
- resolution: `0.05 m`
- radius: robot-centered rolling window, roughly `8-12 m`
- color integration: disabled by default in nav mode

Outputs:

- `rabbit.map.local.voxels.delta`
- `rabbit.map.local.voxels.snapshot`
- `rabbit.map.local.esdf.meta`
- `rabbit.map.local.stats`

Services:

- `rabbit.map.local.snapshot.request`
- `rabbit.map.local.query.esdf`
- `rabbit.map.local.query.tsdf`

### `rabbit-map-global`

Responsibility:

- maintains a larger, coarser world representation
- supports global routing and future exploration

Recommended config:

- integrator: coarse `TSDF` or `occupancy`
- resolution: `0.10-0.15 m`
- large radius or semi-persistent workspace
- decay enabled for dynamic clutter if occupancy is used

Outputs:

- `rabbit.map.global.traversability.delta`
- `rabbit.map.global.snapshot`
- `rabbit.map.global.stats`

### Traversability (module inside `rabbit-map-local`)

Traversability derivation runs as a module inside the local map node, not a separate container. On Orin Nano each container costs ~45-50MB baseline RAM, and traversability is tightly coupled to the ESDF output — a separate node adds latency and memory overhead for no scaling benefit.

Responsibility:

- derives planner-friendly cost layers from local ESDF and TSDF
- converts ESDF and surface structure into 2.5D traversability
- applies footprint inflation and safety margins

Derived layers:

- traversable floor mask
- obstacle mask
- inflated obstacle mask
- overhead-clearance mask
- slope / roughness penalty
- unknown-space penalty

Outputs (published by `rabbit-map-local`):

- `rabbit.nav.local.costmap`
- `rabbit.nav.clearance`

The global costmap is derived inside `rabbit-map-global` using the same traversability module.

### `rabbit-planner`

Responsibility:

- goal management
- global route planning
- local reactive replanning
- trajectory validity checks

Planner split:

- global planner: A* or D* Lite on coarse global grid
- local planner: A* / lattice / hybrid A* on local traversability + clearance

Outputs:

- `rabbit.nav.plan.global`
- `rabbit.nav.plan.local`
- `rabbit.nav.status`

Services:

- `rabbit.nav.goal.set`
- `rabbit.nav.goal.cancel`
- `rabbit.nav.plan.request`

### `rabbit-safety`

Responsibility:

- final arbitration before motion commands hit actuators
- stop on stale pose/map/planner state
- enforce emergency stop and manual override

Inputs:

- teleop command
- planner command
- system health
- obstacle clearance

Outputs:

- `rabbit.motion.cmd.safe`
- `rabbit.safety.status`

### `rabbit-motion-gateway`

Responsibility:

- translates safe motion commands into steering + motor commands
- owns command smoothing and actuator rate limits

Inputs:

- `rabbit.motion.cmd.safe`

Outputs:

- actuator commands to `roboclaw` and steering node

---

## Transport Strategy

### Sensor Fast Path

Phase 1 default: publish one bundled NATS subject instead of separate `depth`, `rgb`, and `pose`:

- `rabbit.sensor.bundle`

Bundle contains:

- `frame_number`
- `timestamp_ns`
- `pose`
- `depth_u16_lz4`
- optional `rgb_jpeg` or raw RGB if needed
- width/height metadata

This is sufficient for current throughput. Compressed depth is ~600KB per frame, well within NATS localhost performance. The bundle eliminates frame/pose desync without added complexity.

Phase 5 optimization: if profiling shows NATS localhost overhead is a bottleneck at higher frame rates, move to Unix domain socket or shared-memory ring buffer between `rabbit-zed-capture` and `rabbit-map-local`. Do not build this until measured latency or CPU overhead demands it.

### Control Plane

Keep NATS for:

- goals
- config
- snapshots/deltas
- planner status
- health and diagnostics
- operator UI

This keeps the system debuggable and composable without ROS2.

---

## Data Contracts

### Frame Bundle

One synchronized bundle should be the atomic input to mapping.

Fields:

- `frame_number: u32`
- `timestamp_ns: u64`
- `pose_translation: f32[3]`
- `pose_orientation_xyzw: f32[4]`
- `depth_width: u16`
- `depth_height: u16`
- `depth_encoding: DEPTH_MM_U16_LZ4`
- `depth_payload`
- optional `rgb_encoding`
- optional `rgb_payload`

Rules:

- mapper stores the latest bundle atomically and processes at its own rate (latest-value pattern, same as current `latest_depth`/`latest_rgb` but bundled — no queue needed)
- mapper never integrates mismatched pose/depth pairs (guaranteed by bundling)
- if the mapper is busy when a new bundle arrives, the old unprocessed bundle is silently replaced
- dropped bundle count is tracked and published in health metrics
- UI video path is decoupled from mapping path

### Map Products

#### Local Voxel Stream

Keep the current block-delta approach, but scope it explicitly as a UI/debug product.

Use:

- `block index + local voxel coords + semantic kind`

Do not use streamed UI voxels as the primary planner substrate.

#### ESDF Query Service

Provide batched request/reply or local API for:

- `N x (x, y, z [, radius]) -> distance`

This becomes the primitive for collision checking and local planning.

#### Traversability Grid

Provide a dense or sparse 2.5D planner view:

- origin
- resolution
- width/height
- occupancy / traversability / clearance arrays

Recommended resolutions:

- local costmap: `0.05-0.10 m`
- global costmap: `0.10-0.20 m`

---

## Mapping Structure For Orin Nano

### Local Map

Best default:

- `0.05 m` TSDF
- rolling robot-centered window
- ESDF updated incrementally
- depth-only by default

This is the highest-value map for:

- manual assisted driving
- collision prevention
- local pathfinding

### Global Map

Best default:

- `0.10-0.15 m` occupancy or TSDF
- lower update rate
- large area persistence

This is the highest-value map for:

- room-to-room routing
- revisit memory
- operator overview

**Memory budget warning:** Running two nvblox Mapper instances (local 0.05m + global 0.10m) on 8GB unified RAM is tight. Current usage: nvblox ~470MB, ZED ~477MB, NATS ~68MB, OS ~1GB. A second mapper could add 200-300MB, leaving <1.5GB headroom with no margin for growth.

Preferred approach for Phase 3: start with a **lightweight Python occupancy grid** (pure numpy, no nvblox) for the global map. Downsample the local TSDF surface voxels into a coarse 2D/2.5D grid at 0.10-0.15m resolution. This costs ~10-50MB depending on area coverage, and avoids a second GPU mapper. Only introduce a second nvblox mapper if the numpy approach proves insufficient for global planning quality.

### Decay And Dynamic Obstacles

For a real home environment, add dynamic handling:

- persistent static layer
- decaying dynamic obstacle layer

Use map decay for recently observed obstacles that may move:

- people
- chairs
- doors
- clutter

Do not let short-lived obstacles permanently poison the global plan.

---

## Traversability Model

Use a navigation model richer than height coloring.

For each planner cell, derive:

- floor existence
- floor continuity
- obstacle occupancy
- obstacle clearance from ESDF
- overhead clearance
- unknownness
- roughness / step height if derivable

A simple first version can classify cells as:

- traversable
- traversable with penalty
- blocked
- unknown

Then apply inflation for robot footprint and stopping margin.

---

## Manual Navigation Architecture

Manual driving should still use the navigation stack.

Recommended flow:

- operator issues desired twist or target point
- safety layer checks local ESDF / traversability
- unsafe commands are clamped, slowed, or rejected
- motion gateway sends rate-limited actuator commands

This gives:

- assisted teleop
- collision-aware manual driving
- a clean upgrade path to autonomy

---

## Planner Recommendation

### Global Planner

Use A* on a coarse 2D grid. At the robot's speed (<1 m/s) and replanning rate (2-10 Hz), A* with full replanning is fast enough on grids up to ~500x500 cells. Incremental algorithms like D* Lite add complexity without measurable benefit at this scale.

State space:

- 2D grid plus optional heading penalty

Inputs:

- global traversability grid
- unknown-space penalty

### Local Planner

Use A* on the local costmap for the first implementation.

If the robot's turning radius or kinematic constraints cause A* grid paths to be infeasible, upgrade to hybrid A* or a lattice planner. Do not preemptively build kinematic planning until straight A* proves insufficient.

Inputs:

- local traversability
- ESDF clearance
- current pose
- target waypoint

Outputs:

- short horizon path
- target twist / curvature / speed command

---

## Node-Level Improvements To Existing Code

### `rabbit-zed`

Current issues:

- separate interval publishers create implicit desynchronization
- repeated compression/publication work competes with capture loop

Recommended refactor:

- one capture loop creates `FrameBundle`
- one bounded producer queue feeds mapping
- optional preview publisher runs independently at lower rate

### `rabbit-nvblox`

Current strengths:

- compact incremental voxel streaming
- correct move away from full Object Store rebuilds

Current issues:

- latest-value integration instead of bundle-based integration
- color integration tied to every frame
- full active block scan for every delta extraction
- planner products not yet first-class

Recommended refactor:

- convert to a long-lived mapper worker consuming bundles
- split local and global maps
- make ESDF updates explicit and periodic
- add query API for planner use
- add traversability export node or module

### `RabbitNode`

Current issues:

- generic interval scheduling is too weak for high-rate sensor pipelines
- no standard backpressure metrics
- no queue observability

Recommended additions:

- bounded queue helper with drop policy
- service helper for NATS request/reply
- structured health heartbeat
- standard metrics hooks

---

## System-Wide Improvements

### 1. Health And Backpressure

Every critical node should publish:

- queue depth
- processing latency
- dropped bundle count
- last successful update timestamp
- GPU/CPU memory summary if available

Subjects:

- `rabbit.health.zed`
- `rabbit.health.map_local`
- `rabbit.health.map_global`
- `rabbit.health.planner`
- `rabbit.health.safety`

### 2. Recording And Replay

Add a recorder for:

- frame bundles
- planner goals
- actuator commands
- key health/diagnostic streams

This is essential for deterministic debugging without ROS bags.

Format: a simple binary log file per recording session. Each entry is:

- `timestamp_ns: u64`
- `subject_length: u16`
- `subject: utf8[subject_length]`
- `headers_length: u32` (0 if no headers)
- `headers: msgpack or json[headers_length]`
- `payload_length: u32`
- `payload: bytes[payload_length]`

This is essentially a NATS message journal. A replay tool reads the file and re-publishes messages at original or accelerated rate. No external dependencies (no protobuf, no rosbag). Can be implemented as a `rabbit-recorder` node that subscribes to configurable subject patterns.

### 3. Config Service

Centralize runtime config in KV / request-reply:

- mapper resolutions
- update rates
- decay settings
- planner penalties
- safety margins

### 4. Monitoring

Re-enable the commented monitoring stack when needed:

- NATS exporter
- telegraf
- Grafana

On Jetson, also record:

- `tegrastats`
- thermal throttling
- GPU utilization
- RAM / swap pressure

### 5. Runtime Profiles

Create explicit operating modes:

- `mapping`
- `manual_nav`
- `autonomy`
- `low_power`

Each mode changes:

- color integration on/off
- ESDF update rate
- UI stream rate
- preview video quality
- planner cadence

---

## Concrete NATS Subject Layout

### Sensor / Perception

- `rabbit.sensor.bundle`
- `rabbit.zed.frame.preview`
- `rabbit.zed.intrinsics`
- `rabbit.zed.health`

### Map

- `rabbit.map.local.voxels.delta`
- `rabbit.map.local.voxels.snapshot`
- `rabbit.map.local.snapshot.request`
- `rabbit.map.local.stats`
- `rabbit.map.global.snapshot`
- `rabbit.map.global.stats`

### Navigation

- `rabbit.nav.local.costmap` (published by `rabbit-map-local`)
- `rabbit.nav.local.clearance` (published by `rabbit-map-local`)
- `rabbit.nav.global.costmap` (published by `rabbit-map-global`)
- `rabbit.nav.goal.set`
- `rabbit.nav.goal.cancel`
- `rabbit.nav.plan.global`
- `rabbit.nav.plan.local`
- `rabbit.nav.status`

### Safety / Motion

- `rabbit.motion.cmd.manual`
- `rabbit.motion.cmd.auto`
- `rabbit.motion.cmd.safe`
- `rabbit.safety.status`

### Health

- `rabbit.health.zed`
- `rabbit.health.map_local`
- `rabbit.health.map_global`
- `rabbit.health.planner`
- `rabbit.health.safety`

---

## Rollout Plan

### Phase 1: Synchronize The Input

- replace separate mapper subscriptions with one synchronized frame bundle
- introduce bounded queue and one mapper worker
- keep current local TSDF and voxel stream

Success criteria:

- no mixed-frame pose/depth integration
- stable mapping latency
- measurable dropped-bundle stats

### Phase 2: Navigation-Ready Local Map

- add explicit local ESDF updates
- add ESDF query API
- add traversability derivation
- keep UI voxel stream as debug layer

Success criteria:

- collision checks can query clearance in real time
- assisted teleop can veto unsafe commands

### Phase 3: Global Memory

- add global coarse map
- derive global costmap
- add A* global planner

Success criteria:

- robot can route through multi-room environment

### Phase 4: Local Planning

- add local planner against local traversability + ESDF
- add safety arbitration
- integrate with motion gateway

Success criteria:

- local obstacle avoidance works without operator micromanagement

### Phase 5: Performance Hardening

- move sensor fast path to local IPC if needed
- add dirty-region extraction
- add decay layers
- add replay + monitoring

Success criteria:

- sustained operation on Orin Nano without memory creep or transport stalls

---

## Recommended First Implementation Choices

If we want the best payoff for the least risk, start with these concrete defaults:

- local mapper only at first
- `0.05 m` TSDF, rolling window
- ESDF update at `3 Hz`
- depth integration at `10 Hz`
- color integration disabled in nav mode
- traversability as a 2.5D local costmap
- A* local planner first
- NATS for control, bundled sensor subject for simplicity

This gets you:

- safer manual driving
- a real planner substrate
- a clear architecture that stays within Orin Nano limits

---

## Non-Goals

This architecture intentionally avoids:

- ROS2 topics/services/actions
- large mesh-centric planning
- house-scale high-resolution TSDF everywhere
- planner dependence on UI voxel rendering

---

## Bottom Line

The best structure for this repo on Orin Nano is:

- synchronized sensor bundle input
- single-writer mapper worker
- local high-res TSDF + ESDF
- coarse global map
- traversability and safety as first-class nodes
- NATS as orchestration layer
- optional local IPC for high-rate sensor data

That gives the project a clean path from visualization to manual navigation to real pathfinding, without ROS2 and without overloading the Jetson.

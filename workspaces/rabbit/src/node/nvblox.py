import asyncio
import json
import struct
import threading
import zlib
from typing import Optional

import cv2
import lz4.frame
import numpy as np
import torch
from lib.model import (
    SENSOR_BUNDLE_SUBJECT,
    CameraIntrinsics,
    Pose,
    SensorBundle,
    deserialize_sensor_bundle,
)
from lib.node import RabbitNode
from nats.aio.msg import Msg
from nvblox_torch.constants import constants
from nvblox_torch.indexing import NUM_VOXELS_PER_SIDE
from nvblox_torch.mapper import Mapper, QueryType
from nvblox_torch.mapper_params import MapperParams, ProjectiveIntegratorParams
from nvblox_torch.projective_integrator_types import ProjectiveIntegratorType


def quaternion_to_rotation_matrix(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def pose_to_transformation_matrix(translation, orientation):
    T = np.eye(4, dtype=np.float32)
    T[:3, :3] = quaternion_to_rotation_matrix(orientation)
    T[:3, 3] = translation

    # nvblox back-projects using OpenCV camera convention (X-right, Y-down, Z-forward).
    # ZED RIGHT_HANDED_Y_UP poses use OpenGL convention (X-right, Y-up, Z-backward).
    # Multiply on the right to convert from OpenCV camera space to OpenGL camera space
    # before the world transform: negate Y and Z axes.
    opencv_to_opengl = np.diag([1.0, -1.0, -1.0, 1.0]).astype(np.float32)
    return T @ opencv_to_opengl


MSG_TYPE_DELTA = 0x01
MSG_TYPE_SNAPSHOT = 0x02

LEGACY_VOXELS_DELTA_SUBJECT = "rabbit.nvblox.voxels.delta"
LEGACY_VOXELS_SNAPSHOT_SUBJECT = "rabbit.nvblox.voxels.snapshot"
LEGACY_VOXELS_REQUEST_SUBJECT = "rabbit.nvblox.voxels.request"
LOCAL_VOXELS_DELTA_SUBJECT = "rabbit.map.local.voxels.delta"
LOCAL_VOXELS_SNAPSHOT_SUBJECT = "rabbit.map.local.voxels.snapshot"
LOCAL_VOXELS_REQUEST_SUBJECT = "rabbit.map.local.snapshot.request"
MAP_LOCAL_STATS_SUBJECT = "rabbit.map.local.stats"
MAP_LOCAL_HEALTH_SUBJECT = "rabbit.health.map_local"
MAP_LOCAL_ESDF_META_SUBJECT = "rabbit.map.local.esdf.meta"
NAV_LOCAL_COSTMAP_SUBJECT = "rabbit.nav.local.costmap"
NAV_LOCAL_CLEARANCE_SUBJECT = "rabbit.nav.local.clearance"
MAP_LOCAL_QUERY_ESDF_SUBJECT = "rabbit.map.local.query.esdf"

VOXELS_DELTA_SUBJECTS = (
    LEGACY_VOXELS_DELTA_SUBJECT,
    LOCAL_VOXELS_DELTA_SUBJECT,
)
VOXELS_SNAPSHOT_SUBJECTS = (
    LEGACY_VOXELS_SNAPSHOT_SUBJECT,
    LOCAL_VOXELS_SNAPSHOT_SUBJECT,
)

VOXEL_KIND_FLOOR = 0
VOXEL_KIND_OBSTACLE = 1
VOXEL_KIND_STRUCTURE = 2
VOXEL_KIND_BELOW = 3

COSTMAP_UNKNOWN = 0
COSTMAP_TRAVERSABLE = 1
COSTMAP_CAUTION = 2
COSTMAP_BLOCKED = 3


def serialize_delta(
    sequence: int,
    voxel_size: float,
    remove_blocks: list[tuple[int, int, int]],
    upsert_blocks: list[tuple[tuple[int, int, int], np.ndarray]],
) -> bytes:
    payload = bytearray(
        struct.pack(
            "<BIfII",
            MSG_TYPE_DELTA,
            sequence,
            voxel_size,
            len(remove_blocks),
            len(upsert_blocks),
        )
    )

    for block_index in remove_blocks:
        payload.extend(struct.pack("<iii", *block_index))

    for block_index, voxels in upsert_blocks:
        payload.extend(struct.pack("<iiiH", *block_index, len(voxels)))
        payload.extend(voxels.tobytes())

    return lz4.frame.compress(bytes(payload))


def serialize_snapshot(
    sequence: int,
    voxel_size: float,
    blocks: list[tuple[tuple[int, int, int], np.ndarray]],
) -> bytes:
    payload = bytearray(
        struct.pack(
            "<BIfI",
            MSG_TYPE_SNAPSHOT,
            sequence,
            voxel_size,
            len(blocks),
        )
    )

    for block_index, voxels in blocks:
        payload.extend(struct.pack("<iiiH", *block_index, len(voxels)))
        payload.extend(voxels.tobytes())

    return lz4.frame.compress(bytes(payload))


class Node(RabbitNode):
    MIN_DEPTH = 0.1
    MAX_DEPTH = 10.0
    VOXEL_SIZE = 0.05
    MAX_INTEGRATION_DISTANCE = 5.0
    SURFACE_THRESHOLD_FACTOR = 2.0
    MIN_WEIGHT = 0.1
    PROCESS_INTERVAL_S = 0.1
    DELTA_INTERVAL_S = 2.0
    SNAPSHOT_INTERVAL_S = 60.0
    ESDF_INTERVAL_S = 1.0 / 3.0
    TRAVERSABILITY_INTERVAL_S = 1.0
    ENABLE_COLOR_INTEGRATION = False
    COSTMAP_RESOLUTION_M = 0.10
    COSTMAP_WIDTH_CELLS = 80
    COSTMAP_HEIGHT_CELLS = 80
    ROBOT_FOOTPRINT_RADIUS_M = 0.25
    ROBOT_CLEARANCE_HEIGHT_M = 0.45
    TRAVERSABILITY_QUERY_HEIGHT_M = 0.15
    CLEARANCE_SAFE_MARGIN_M = 0.10

    def __init__(self):
        super().__init__("nvblox")

        self.mapper: Optional[Mapper] = None
        self.color_intrinsics: Optional[torch.Tensor] = None
        self.depth_intrinsics: Optional[torch.Tensor] = None
        self._latest_bundle: Optional[SensorBundle] = None
        self._mapper_lock = threading.Lock()
        self._publish_lock = asyncio.Lock()
        self._prev_block_set: set[tuple[int, int, int]] = set()
        self._prev_block_sigs: dict[tuple[int, int, int], int] = {}
        self._sequence = 0
        self._received_bundle_count = 0
        self._replaced_bundle_count = 0
        self._processed_bundle_count = 0
        self._lock_busy_skip_count = 0
        self._last_processed_frame = -1
        self._last_processed_timestamp = 0
        self._last_integration_duration_ms = 0.0
        self._esdf_update_count = 0
        self._last_esdf_update_duration_ms = 0.0
        self._last_total_voxels = 0
        self._last_floor_voxels = 0
        self._last_obstacle_voxels = 0
        self._last_delta_bytes = 0
        self._last_snapshot_bytes = 0
        self._last_delta_upserts = 0
        self._last_delta_removes = 0
        self._last_snapshot_blocks = 0
        self._last_num_blocks = 0
        self._last_allocated_bytes = 0
        self._last_robot_translation = (0.0, 0.0, 0.0)
        self._esdf_query_count = 0
        self._esdf_query_error_count = 0
        self._last_esdf_query_duration_ms = 0.0
        self._traversability_publish_count = 0
        self._last_traversability_duration_ms = 0.0
        self._last_costmap_bytes = 0
        self._last_clearance_bytes = 0

        projective_integrator_params = ProjectiveIntegratorParams()
        projective_integrator_params.projective_integrator_max_integration_distance_m = (
            self.MAX_INTEGRATION_DISTANCE
        )

        mapper_params = MapperParams()
        mapper_params.set_projective_integrator_params(projective_integrator_params)

        self.mapper = Mapper(
            voxel_sizes_m=self.VOXEL_SIZE,
            integrator_types=ProjectiveIntegratorType.TSDF,
            mapper_parameters=mapper_params,
        )

    async def init(self):
        await self.load_camera_intrinsics()
        await self.nc.subscribe(SENSOR_BUNDLE_SUBJECT, cb=self.on_sensor_bundle)
        await self.nc.subscribe(
            LEGACY_VOXELS_REQUEST_SUBJECT, cb=self.on_snapshot_request
        )
        await self.nc.subscribe(
            LOCAL_VOXELS_REQUEST_SUBJECT, cb=self.on_snapshot_request
        )
        await self.nc.subscribe(MAP_LOCAL_QUERY_ESDF_SUBJECT, cb=self.on_esdf_query)

        self.set_interval(
            self.process_latest_bundle, self.PROCESS_INTERVAL_S, max_parallel=1
        )
        self.set_interval(
            self.update_local_esdf, self.ESDF_INTERVAL_S, max_parallel=1
        )
        self.set_interval(
            self.publish_local_traversability,
            self.TRAVERSABILITY_INTERVAL_S,
            max_parallel=1,
        )
        self.set_interval(
            self.publish_voxel_delta, self.DELTA_INTERVAL_S, max_parallel=1
        )
        self.set_interval(
            self.publish_full_snapshot, self.SNAPSHOT_INTERVAL_S, max_parallel=1
        )
        self.set_interval(self.publish_map_stats, 1, max_parallel=1)
        self.set_interval(self.publish_health, 1, max_parallel=1)

    # Depth frame resolution (from ZED node headers)
    DEPTH_W = 640
    DEPTH_H = 480

    async def load_camera_intrinsics(self):
        entry = await self.kv.get("rabbit.zed.intrinsics")
        if entry.value is None:
            raise KeyError("Camera intrinsics not found in KeyValue store")

        intrinsics = CameraIntrinsics.model_validate_json(entry.value)

        # Color intrinsics — matches the full-resolution RGB frame
        self.color_intrinsics = torch.tensor(
            [
                [intrinsics.fx, 0, intrinsics.cx],
                [0, intrinsics.fy, intrinsics.cy],
                [0, 0, 1],
            ],
            dtype=torch.float32,
        )

        # Depth intrinsics — scaled for the lower-resolution depth frame
        sx = self.DEPTH_W / intrinsics.width
        sy = self.DEPTH_H / intrinsics.height
        self.depth_intrinsics = torch.tensor(
            [
                [intrinsics.fx * sx, 0, intrinsics.cx * sx],
                [0, intrinsics.fy * sy, intrinsics.cy * sy],
                [0, 0, 1],
            ],
            dtype=torch.float32,
        )

        self.logger.info(
            f"Loaded intrinsics: color={intrinsics.width}x{intrinsics.height} "
            f"depth={self.DEPTH_W}x{self.DEPTH_H} "
            f"fx={intrinsics.fx:.1f} fy={intrinsics.fy:.1f}"
        )

    async def on_sensor_bundle(self, msg: Msg):
        bundle = deserialize_sensor_bundle(msg.data)
        self._received_bundle_count += 1
        if self._latest_bundle is not None:
            self._replaced_bundle_count += 1
        self._latest_bundle = bundle

    def _decode_depth_image(self, bundle: SensorBundle) -> np.ndarray:
        raw = lz4.frame.decompress(bundle.depth_payload)
        depth_u16 = np.frombuffer(raw, dtype=np.uint16).reshape(
            bundle.depth_height, bundle.depth_width
        )
        depth_image = depth_u16.astype(np.float32) * 0.001
        valid_mask = (depth_image > self.MIN_DEPTH) & (depth_image < self.MAX_DEPTH)
        depth_image[~valid_mask] = 0.0
        return depth_image

    def _decode_rgb_image(self, bundle: SensorBundle) -> Optional[np.ndarray]:
        if not bundle.rgb_payload:
            return None
        nparr = np.frombuffer(bundle.rgb_payload, np.uint8)
        rgb_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if rgb_image is None:
            return None
        return cv2.cvtColor(rgb_image, cv2.COLOR_BGR2RGB)

    async def process_latest_bundle(self):
        bundle = self._latest_bundle
        if (
            bundle is None
            or self.mapper is None
            or self.depth_intrinsics is None
            or self.color_intrinsics is None
        ):
            return

        if not self._mapper_lock.acquire(blocking=False):
            self._lock_busy_skip_count += 1
            return

        self._latest_bundle = None
        loop = asyncio.get_running_loop()
        started = loop.time()

        try:
            pose_matrix = pose_to_transformation_matrix(
                bundle.translation, bundle.orientation
            )
            pose_tensor = torch.from_numpy(pose_matrix).float()

            depth_image = self._decode_depth_image(bundle)
            depth_tensor = torch.from_numpy(depth_image).float().cuda()
            self.mapper.add_depth_frame(depth_tensor, pose_tensor, self.depth_intrinsics)

            if self.ENABLE_COLOR_INTEGRATION and bundle.rgb_payload:
                rgb_image = self._decode_rgb_image(bundle)
                if rgb_image is not None:
                    rgb_tensor = torch.from_numpy(rgb_image).cuda()
                    self.mapper.add_color_frame(
                        rgb_tensor, pose_tensor, self.color_intrinsics
                    )

            self._processed_bundle_count += 1
            self._last_processed_frame = bundle.frame_number
            self._last_processed_timestamp = bundle.timestamp
            self._last_robot_translation = bundle.translation
            self._last_integration_duration_ms = (loop.time() - started) * 1000.0
        finally:
            self._mapper_lock.release()

    def _read_layer_stats(self) -> Optional[tuple[int, int]]:
        if not self._mapper_lock.acquire(blocking=False):
            return None

        try:
            tsdf_layer = self.mapper.tsdf_layer_view()
            return tsdf_layer.num_blocks(), tsdf_layer.num_allocated_bytes()
        finally:
            self._mapper_lock.release()

    async def publish_map_stats(self):
        if not self.mapper:
            return

        loop = asyncio.get_running_loop()
        layer_stats = await loop.run_in_executor(None, self._read_layer_stats)
        if layer_stats is not None:
            self._last_num_blocks, self._last_allocated_bytes = layer_stats

        payload = json.dumps(
            {
                "sequence": self._sequence,
                "last_processed_frame": self._last_processed_frame,
                "last_processed_timestamp": self._last_processed_timestamp,
                "num_blocks": self._last_num_blocks,
                "allocated_bytes": self._last_allocated_bytes,
                "total_voxels": self._last_total_voxels,
                "floor_voxels": self._last_floor_voxels,
                "obstacle_voxels": self._last_obstacle_voxels,
                "last_delta_bytes": self._last_delta_bytes,
                "last_snapshot_bytes": self._last_snapshot_bytes,
                "last_delta_upserts": self._last_delta_upserts,
                "last_delta_removes": self._last_delta_removes,
                "last_snapshot_blocks": self._last_snapshot_blocks,
                "esdf_updates": self._esdf_update_count,
                "esdf_queries": self._esdf_query_count,
                "traversability_publishes": self._traversability_publish_count,
                "last_costmap_bytes": self._last_costmap_bytes,
                "last_clearance_bytes": self._last_clearance_bytes,
            }
        ).encode()
        await self.nc.publish(MAP_LOCAL_STATS_SUBJECT, payload)

    async def publish_health(self):
        payload = json.dumps(
            {
                "received_bundle_count": self._received_bundle_count,
                "replaced_bundle_count": self._replaced_bundle_count,
                "processed_bundle_count": self._processed_bundle_count,
                "lock_busy_skip_count": self._lock_busy_skip_count,
                "last_processed_frame": self._last_processed_frame,
                "last_integration_duration_ms": self._last_integration_duration_ms,
                "last_esdf_update_duration_ms": self._last_esdf_update_duration_ms,
                "esdf_update_count": self._esdf_update_count,
                "esdf_query_count": self._esdf_query_count,
                "esdf_query_error_count": self._esdf_query_error_count,
                "last_esdf_query_duration_ms": self._last_esdf_query_duration_ms,
                "traversability_publish_count": self._traversability_publish_count,
                "last_traversability_duration_ms": self._last_traversability_duration_ms,
                "num_blocks": self._last_num_blocks,
                "allocated_bytes": self._last_allocated_bytes,
            }
        ).encode()
        await self.nc.publish(MAP_LOCAL_HEALTH_SUBJECT, payload)

    def _update_esdf_locked(self) -> bool:
        if not self._mapper_lock.acquire(blocking=False):
            return False

        try:
            self.mapper.update_esdf()
            return True
        finally:
            self._mapper_lock.release()

    async def update_local_esdf(self):
        if not self.mapper:
            return

        loop = asyncio.get_running_loop()
        started = loop.time()
        updated = await loop.run_in_executor(None, self._update_esdf_locked)
        if not updated:
            return

        self._esdf_update_count += 1
        self._last_esdf_update_duration_ms = (loop.time() - started) * 1000.0
        payload = json.dumps(
            {
                "update_count": self._esdf_update_count,
                "last_processed_frame": self._last_processed_frame,
                "last_update_duration_ms": self._last_esdf_update_duration_ms,
                "voxel_size": self.VOXEL_SIZE,
            }
        ).encode()
        await self.nc.publish(MAP_LOCAL_ESDF_META_SUBJECT, payload)

    def _query_esdf_sync(self, points: np.ndarray) -> np.ndarray:
        with self._mapper_lock:
            query_tensor = torch.from_numpy(points).float().cuda()
            distances = self.mapper.query_layer(QueryType.ESDF, query_tensor)
            return distances.detach().cpu().numpy().reshape(-1)

    async def on_esdf_query(self, msg: Msg):
        if not msg.reply:
            return

        loop = asyncio.get_running_loop()
        started = loop.time()

        try:
            request = json.loads(msg.data.decode())
            raw_points = request.get("points")
            if not isinstance(raw_points, list) or len(raw_points) == 0:
                raise ValueError("Request must contain a non-empty 'points' array")

            points = np.asarray(raw_points, dtype=np.float32)
            if points.ndim != 2 or points.shape[1] not in (3, 4):
                raise ValueError("Each point must have 3 or 4 float values")

            distances = await loop.run_in_executor(None, self._query_esdf_sync, points)
            self._esdf_query_count += len(points)
            self._last_esdf_query_duration_ms = (loop.time() - started) * 1000.0

            payload = json.dumps(
                {
                    "frame_number": self._last_processed_frame,
                    "timestamp": self._last_processed_timestamp,
                    "voxel_size": self.VOXEL_SIZE,
                    "unknown_distance": constants.esdf_unknown_distance(),
                    "distances": distances.tolist(),
                }
            ).encode()
        except Exception as exc:
            self._esdf_query_error_count += 1
            payload = json.dumps({"error": str(exc)}).encode()

        await self.nc.publish(msg.reply, payload)

    def _build_local_traversability_sync(
        self,
    ) -> Optional[tuple[dict[str, object], np.ndarray, np.ndarray]]:
        if not self._mapper_lock.acquire(blocking=False):
            return None

        try:
            tsdf_layer = self.mapper.tsdf_layer_view()
            tsdf_blocks, indices = tsdf_layer.get_all_blocks()
            voxel_size = tsdf_layer.voxel_size()
            block_size = voxel_size * NUM_VOXELS_PER_SIDE
            surface_threshold = self.SURFACE_THRESHOLD_FACTOR * voxel_size
            unknown_distance = float(constants.esdf_unknown_distance())

            width = self.COSTMAP_WIDTH_CELLS
            height = self.COSTMAP_HEIGHT_CELLS
            resolution = self.COSTMAP_RESOLUTION_M
            robot_x, robot_y, robot_z = self._last_robot_translation
            origin_x = float(robot_x - (width * resolution) * 0.5)
            origin_z = float(robot_z - (height * resolution) * 0.5)
            max_x = origin_x + width * resolution
            max_z = origin_z + height * resolution

            floor_observed = np.zeros((height, width), dtype=bool)
            surface_blocked = np.zeros((height, width), dtype=bool)

            for tsdf_block, block_index in zip(tsdf_blocks, indices):
                block_coords = block_index.to(device="cpu").tolist()
                block_x, block_y, block_z = (int(v) for v in block_coords)
                block_min_x = block_x * block_size
                block_max_x = block_min_x + block_size
                block_min_y = block_y * block_size
                block_max_y = block_min_y + block_size
                block_min_z = block_z * block_size
                block_max_z = block_min_z + block_size

                if (
                    block_max_x <= origin_x
                    or block_min_x >= max_x
                    or block_max_z <= origin_z
                    or block_min_z >= max_z
                    or block_max_y <= self.FLOOR_MIN
                    or block_min_y >= self.ROBOT_CLEARANCE_HEIGHT_M + voxel_size
                ):
                    continue

                tsdf_values = tsdf_block[..., 0]
                weights = tsdf_block[..., 1]
                surface_mask = (torch.abs(tsdf_values) < surface_threshold) & (
                    weights > self.MIN_WEIGHT
                )
                if not torch.any(surface_mask):
                    continue

                local_indices = (
                    surface_mask.nonzero(as_tuple=False)
                    .to(device="cpu", dtype=torch.uint8)
                    .numpy()
                )
                if len(local_indices) == 0:
                    continue

                kinds, heights = self._classify_voxel_kinds(
                    block_y, local_indices[:, 1], voxel_size
                )
                world_x = (
                    (
                        block_x * NUM_VOXELS_PER_SIDE
                        + local_indices[:, 0].astype(np.float32)
                        + 0.5
                    )
                    * voxel_size
                )
                world_z = (
                    (
                        block_z * NUM_VOXELS_PER_SIDE
                        + local_indices[:, 2].astype(np.float32)
                        + 0.5
                    )
                    * voxel_size
                )
                cell_x = np.floor((world_x - origin_x) / resolution).astype(np.int32)
                cell_z = np.floor((world_z - origin_z) / resolution).astype(np.int32)
                in_bounds = (
                    (cell_x >= 0)
                    & (cell_x < width)
                    & (cell_z >= 0)
                    & (cell_z < height)
                )
                if not np.any(in_bounds):
                    continue

                cell_x = cell_x[in_bounds]
                cell_z = cell_z[in_bounds]
                kinds = kinds[in_bounds]
                heights = heights[in_bounds]

                floor_mask = kinds == VOXEL_KIND_FLOOR
                if np.any(floor_mask):
                    floor_observed[cell_z[floor_mask], cell_x[floor_mask]] = True

                blocked_mask = (kinds == VOXEL_KIND_OBSTACLE) | (
                    (kinds == VOXEL_KIND_STRUCTURE)
                    & (heights <= self.ROBOT_CLEARANCE_HEIGHT_M)
                )
                if np.any(blocked_mask):
                    surface_blocked[cell_z[blocked_mask], cell_x[blocked_mask]] = True

            centers_x = origin_x + (np.arange(width, dtype=np.float32) + 0.5) * resolution
            centers_z = origin_z + (np.arange(height, dtype=np.float32) + 0.5) * resolution
            grid_x, grid_z = np.meshgrid(centers_x, centers_z, indexing="xy")
            query_points = np.stack(
                [
                    grid_x.reshape(-1),
                    np.full(
                        width * height,
                        self.TRAVERSABILITY_QUERY_HEIGHT_M,
                        dtype=np.float32,
                    ),
                    grid_z.reshape(-1),
                    np.full(
                        width * height,
                        self.ROBOT_FOOTPRINT_RADIUS_M,
                        dtype=np.float32,
                    ),
                ],
                axis=1,
            )
            query_tensor = torch.from_numpy(query_points).float().cuda()
            clearances = (
                self.mapper.query_layer(QueryType.ESDF, query_tensor)
                .detach()
                .cpu()
                .numpy()
                .reshape(height, width)
            )

            unknown_mask = np.isclose(clearances, unknown_distance)
            negative_clearance_mask = (~unknown_mask) & (clearances < 0.0)
            known_floor_mask = floor_observed & ~unknown_mask & ~surface_blocked
            caution_mask = known_floor_mask & (
                clearances < self.CLEARANCE_SAFE_MARGIN_M
            )
            traversable_mask = known_floor_mask & ~caution_mask

            costmap = np.full((height, width), COSTMAP_UNKNOWN, dtype=np.uint8)
            costmap[traversable_mask] = COSTMAP_TRAVERSABLE
            costmap[caution_mask] = COSTMAP_CAUTION
            costmap[surface_blocked | negative_clearance_mask] = COSTMAP_BLOCKED

            metadata = {
                "frame_number": self._last_processed_frame,
                "timestamp": self._last_processed_timestamp,
                "voxel_size": float(voxel_size),
                "unknown_distance": unknown_distance,
                "resolution": resolution,
                "width": width,
                "height": height,
                "origin_x": origin_x,
                "origin_z": origin_z,
                "robot_translation": [float(robot_x), float(robot_y), float(robot_z)],
                "robot_radius": self.ROBOT_FOOTPRINT_RADIUS_M,
                "query_height": self.TRAVERSABILITY_QUERY_HEIGHT_M,
                "clearance_margin": self.CLEARANCE_SAFE_MARGIN_M,
                "cell_order": "row_major",
                "grid_axes": {"x": "columns", "z": "rows"},
                "counts": {
                    "unknown": int(np.count_nonzero(costmap == COSTMAP_UNKNOWN)),
                    "traversable": int(
                        np.count_nonzero(costmap == COSTMAP_TRAVERSABLE)
                    ),
                    "caution": int(np.count_nonzero(costmap == COSTMAP_CAUTION)),
                    "blocked": int(np.count_nonzero(costmap == COSTMAP_BLOCKED)),
                    "floor_observed": int(np.count_nonzero(floor_observed)),
                    "surface_blocked": int(np.count_nonzero(surface_blocked)),
                },
            }
            return metadata, costmap, clearances.astype(np.float32, copy=False)
        finally:
            self._mapper_lock.release()

    async def publish_local_traversability(self):
        if self.mapper is None or self._last_processed_frame < 0:
            return

        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await loop.run_in_executor(
            None, self._build_local_traversability_sync
        )
        if result is None:
            return

        metadata, costmap, clearances = result
        rounded_clearances = np.round(clearances, 3)

        costmap_payload = json.dumps(
            {
                **metadata,
                "encoding": "flat_u8",
                "cells": costmap.reshape(-1).tolist(),
            }
        ).encode()
        clearance_payload = json.dumps(
            {
                **metadata,
                "encoding": "flat_f32",
                "values": rounded_clearances.reshape(-1).tolist(),
            }
        ).encode()

        await self.nc.publish(NAV_LOCAL_COSTMAP_SUBJECT, costmap_payload)
        await self.nc.publish(NAV_LOCAL_CLEARANCE_SUBJECT, clearance_payload)

        self._traversability_publish_count += 1
        self._last_traversability_duration_ms = (loop.time() - started) * 1000.0
        self._last_costmap_bytes = len(costmap_payload)
        self._last_clearance_bytes = len(clearance_payload)

    # Navigability height thresholds (meters, Y-up coordinate system)
    FLOOR_MIN = -0.05  # slightly below floor to catch surface
    FLOOR_MAX = 0.20  # top of navigable floor band
    OBSTACLE_MAX = 0.50  # anything between FLOOR_MAX and this is a low obstacle
    # Above OBSTACLE_MAX = structure (walls, ceiling)

    def _classify_voxel_kinds(
        self, block_y: int, local_y_indices: np.ndarray, voxel_size: float
    ) -> tuple[np.ndarray, np.ndarray]:
        heights = (
            (
                block_y * NUM_VOXELS_PER_SIDE
                + local_y_indices.astype(np.float32)
                + 0.5
            )
            * voxel_size
        )
        kinds = np.full(len(local_y_indices), VOXEL_KIND_STRUCTURE, dtype=np.uint8)

        floor_mask = (heights >= self.FLOOR_MIN) & (heights < self.FLOOR_MAX)
        obstacle_mask = (heights >= self.FLOOR_MAX) & (heights < self.OBSTACLE_MAX)
        below_mask = heights < self.FLOOR_MIN

        kinds[floor_mask] = VOXEL_KIND_FLOOR
        kinds[obstacle_mask] = VOXEL_KIND_OBSTACLE
        kinds[below_mask] = VOXEL_KIND_BELOW
        return kinds, heights

    def _collect_surface_blocks(
        self, *, changed_only: bool
    ) -> tuple[
        float,
        list[tuple[tuple[int, int, int], np.ndarray]],
        set[tuple[int, int, int]],
        dict[tuple[int, int, int], int],
        dict[str, float],
    ]:
        """Extract compact block payloads. Runs in a thread to avoid blocking asyncio."""
        upsert_blocks: list[tuple[tuple[int, int, int], np.ndarray]] = []
        current_block_set: set[tuple[int, int, int]] = set()
        current_block_sigs: dict[tuple[int, int, int], int] = {}
        total_voxels = 0
        kind_counts = np.zeros(4, dtype=np.int64)
        y_min = float("inf")
        y_max = float("-inf")

        with self._mapper_lock:
            tsdf_layer = self.mapper.tsdf_layer_view()
            tsdf_blocks, indices = tsdf_layer.get_all_blocks()
            voxel_size = tsdf_layer.voxel_size()
            surface_threshold = self.SURFACE_THRESHOLD_FACTOR * voxel_size
            for tsdf_block, block_index in zip(tsdf_blocks, indices):
                tsdf_values = tsdf_block[..., 0]
                weights = tsdf_block[..., 1]
                surface_mask = (torch.abs(tsdf_values) < surface_threshold) & (
                    weights > self.MIN_WEIGHT
                )

                if not torch.any(surface_mask):
                    continue

                block_key = tuple(int(v) for v in block_index.to(device="cpu").tolist())
                current_block_set.add(block_key)

                local_indices = (
                    surface_mask.nonzero(as_tuple=False)
                    .to(device="cpu", dtype=torch.uint8)
                    .numpy()
                )
                kinds, heights = self._classify_voxel_kinds(
                    block_key[1], local_indices[:, 1], voxel_size
                )

                voxels = np.empty((len(local_indices), 4), dtype=np.uint8)
                voxels[:, :3] = local_indices
                voxels[:, 3] = kinds

                block_sig = zlib.crc32(voxels)
                current_block_sigs[block_key] = block_sig
                total_voxels += len(voxels)
                kind_counts += np.bincount(kinds, minlength=4)
                y_min = min(y_min, float(heights.min()))
                y_max = max(y_max, float(heights.max()))

                if not changed_only or self._prev_block_sigs.get(block_key) != block_sig:
                    upsert_blocks.append((block_key, voxels))

        upsert_blocks.sort(key=lambda item: item[0])
        stats = {
            "total_voxels": total_voxels,
            "floor_voxels": int(kind_counts[VOXEL_KIND_FLOOR]),
            "obstacle_voxels": int(kind_counts[VOXEL_KIND_OBSTACLE]),
            "structure_voxels": int(kind_counts[VOXEL_KIND_STRUCTURE]),
            "below_voxels": int(kind_counts[VOXEL_KIND_BELOW]),
            "y_min": 0.0 if y_min == float("inf") else y_min,
            "y_max": 0.0 if y_max == float("-inf") else y_max,
        }
        return voxel_size, upsert_blocks, current_block_set, current_block_sigs, stats

    def _extract_voxel_delta(self):
        voxel_size, upsert_blocks, current_block_set, current_block_sigs, stats = (
            self._collect_surface_blocks(changed_only=True)
        )
        remove_blocks = sorted(self._prev_block_set - current_block_set)
        self._prev_block_set = current_block_set
        self._prev_block_sigs = current_block_sigs

        if not upsert_blocks and not remove_blocks:
            return None

        return voxel_size, remove_blocks, upsert_blocks, stats

    def _build_full_snapshot(self):
        voxel_size, blocks, _, _, stats = self._collect_surface_blocks(changed_only=False)
        return voxel_size, blocks, stats

    async def _publish_to_subjects(self, subjects: tuple[str, ...], payload: bytes):
        for subject in subjects:
            await self.nc.publish(subject, payload)

    async def publish_voxel_delta(self):
        if not self.mapper:
            return

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._extract_voxel_delta)

        if result is None:
            return

        voxel_size, remove_blocks, upsert_blocks, stats = result

        async with self._publish_lock:
            self._sequence += 1
            payload = serialize_delta(
                self._sequence, voxel_size, remove_blocks, upsert_blocks
            )
            await self._publish_to_subjects(VOXELS_DELTA_SUBJECTS, payload)

        self._last_total_voxels = stats["total_voxels"]
        self._last_floor_voxels = stats["floor_voxels"]
        self._last_obstacle_voxels = stats["obstacle_voxels"]
        self._last_delta_bytes = len(payload)
        self._last_delta_upserts = len(upsert_blocks)
        self._last_delta_removes = len(remove_blocks)

        self.logger.info(
            f"Published delta seq={self._sequence} "
            f"upserts={len(upsert_blocks)} removes={len(remove_blocks)} "
            f"voxels={stats['total_voxels']} floor={stats['floor_voxels']} "
            f"obs={stats['obstacle_voxels']} "
            f"Y=[{stats['y_min']:.2f}, {stats['y_max']:.2f}] "
            f"bytes={len(payload)}"
        )

    async def _publish_snapshot(self, reason: str):
        if not self.mapper:
            return

        loop = asyncio.get_running_loop()
        voxel_size, blocks, stats = await loop.run_in_executor(
            None, self._build_full_snapshot
        )

        async with self._publish_lock:
            self._sequence += 1
            payload = serialize_snapshot(self._sequence, voxel_size, blocks)
            await self._publish_to_subjects(VOXELS_SNAPSHOT_SUBJECTS, payload)

        self._last_total_voxels = stats["total_voxels"]
        self._last_floor_voxels = stats["floor_voxels"]
        self._last_obstacle_voxels = stats["obstacle_voxels"]
        self._last_snapshot_bytes = len(payload)
        self._last_snapshot_blocks = len(blocks)

        self.logger.info(
            f"Published snapshot seq={self._sequence} reason={reason} "
            f"blocks={len(blocks)} voxels={stats['total_voxels']} "
            f"floor={stats['floor_voxels']} obs={stats['obstacle_voxels']} "
            f"Y=[{stats['y_min']:.2f}, {stats['y_max']:.2f}] "
            f"bytes={len(payload)}"
        )

    async def publish_full_snapshot(self):
        await self._publish_snapshot("interval")

    async def on_snapshot_request(self, _: Msg):
        await self._publish_snapshot("request")


if __name__ == "__main__":
    Node().run_node()

import asyncio
import json

import lz4.frame
import numpy as np
from lib.model import (
    SENSOR_BUNDLE_SUBJECT,
    CameraIntrinsics,
    SensorBundle,
    deserialize_sensor_bundle,
)
from lib.node import RabbitNode
from lib.occupancy import (
    COSTMAP_BLOCKED,
    COSTMAP_CAUTION,
    COSTMAP_TRAVERSABLE,
    COSTMAP_UNKNOWN,
    OccupancyGrid,
)
from nats.aio.msg import Msg

NAV_LOCAL_COSTMAP_SUBJECT = "rabbit.nav.local.costmap"
HEALTH_SUBJECT = "rabbit.health.perception"


def quaternion_to_rotation_matrix(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float32,
    )


class Node(RabbitNode):
    PROCESS_INTERVAL_S = 0.1  # 10 Hz
    PUBLISH_INTERVAL_S = 0.5  # 2 Hz
    MIN_DEPTH = 0.3
    MAX_DEPTH = 5.0
    DEPTH_W = 640
    DEPTH_H = 480
    SUBSAMPLE = 8  # every 8th pixel → 80x60 = 4800 points

    def __init__(self):
        super().__init__("perception")

        self.grid = OccupancyGrid()
        self._latest_bundle: SensorBundle | None = None
        self._intrinsics: CameraIntrinsics | None = None
        self._rays_x: np.ndarray | None = None
        self._rays_y: np.ndarray | None = None

        # Metrics
        self._received_count = 0
        self._processed_count = 0
        self._replaced_count = 0
        self._last_frame = -1
        self._last_timestamp = 0
        self._last_process_ms = 0.0
        self._last_points_count = 0
        self._last_obstacle_count = 0
        self._publish_count = 0

    async def init(self):
        await self._load_intrinsics()
        await self.nc.subscribe(SENSOR_BUNDLE_SUBJECT, cb=self._on_bundle)

        self.set_interval(self._process, self.PROCESS_INTERVAL_S, max_parallel=1)
        self.set_interval(self._publish_costmap, self.PUBLISH_INTERVAL_S, max_parallel=1)
        self.set_interval(self._publish_health, 1, max_parallel=1)

    async def _load_intrinsics(self):
        entry = await self.kv.get("rabbit.zed.intrinsics")
        if entry.value is None:
            raise KeyError("Camera intrinsics not found")

        intr = CameraIntrinsics.model_validate_json(entry.value)
        self._intrinsics = intr

        # Scale intrinsics to depth resolution
        sx = self.DEPTH_W / intr.width
        sy = self.DEPTH_H / intr.height
        fx = intr.fx * sx
        fy = intr.fy * sy
        cx = intr.cx * sx
        cy = intr.cy * sy

        # Pixel coordinates at subsampled positions
        u = np.arange(0, self.DEPTH_W, self.SUBSAMPLE, dtype=np.float32)
        v = np.arange(0, self.DEPTH_H, self.SUBSAMPLE, dtype=np.float32)
        uu, vv = np.meshgrid(u, v)

        # Normalized ray directions per pixel
        self._rays_x = ((uu - cx) / fx).ravel()  # (N,)
        self._rays_y = ((vv - cy) / fy).ravel()  # (N,)

        sub_h = len(v)
        sub_w = len(u)
        self.logger.info(
            f"Intrinsics: {intr.width}x{intr.height} → "
            f"depth {self.DEPTH_W}x{self.DEPTH_H} → "
            f"subsampled {sub_w}x{sub_h} = {sub_w * sub_h} pixels"
        )

    async def _on_bundle(self, msg: Msg):
        bundle = deserialize_sensor_bundle(msg.data)
        self._received_count += 1
        if self._latest_bundle is not None:
            self._replaced_count += 1
        self._latest_bundle = bundle

    async def _process(self):
        bundle = self._latest_bundle
        if bundle is None or self._rays_x is None:
            return
        self._latest_bundle = None

        loop = asyncio.get_running_loop()
        started = loop.time()

        points, n_obstacle = await loop.run_in_executor(
            None, self._compute_and_update, bundle
        )

        self._processed_count += 1
        self._last_frame = bundle.frame_number
        self._last_timestamp = bundle.timestamp
        self._last_process_ms = (loop.time() - started) * 1000.0
        self._last_points_count = points
        self._last_obstacle_count = n_obstacle

        if self._processed_count <= 3 or self._processed_count % 30 == 0:
            self.logger.info(
                f"frame={bundle.frame_number} "
                f"points={points} obstacles={n_obstacle} "
                f"process={self._last_process_ms:.0f}ms"
            )

    def _compute_and_update(self, bundle: SensorBundle) -> tuple[int, int]:
        """Decode depth → back-project → transform → update grid. Returns (total_points, obstacle_points)."""
        # Decode depth
        raw = lz4.frame.decompress(bundle.depth_payload)
        depth_full = np.frombuffer(raw, dtype=np.uint16).reshape(
            bundle.depth_height, bundle.depth_width
        )

        # Subsample and convert to meters
        depth_sub = depth_full[:: self.SUBSAMPLE, :: self.SUBSAMPLE].ravel()
        depth_m = depth_sub.astype(np.float32) * 0.001

        # Valid depth mask
        valid = (depth_m > self.MIN_DEPTH) & (depth_m < self.MAX_DEPTH)
        if not np.any(valid):
            return 0, 0

        d = depth_m[valid]
        rx = self._rays_x[valid]
        ry = self._rays_y[valid]

        # Back-project to camera frame (OpenCV convention: X-right, Y-down, Z-forward)
        cam_x = rx * d
        cam_y = ry * d
        cam_z = d

        # Convert to OpenGL camera frame (what ZED RIGHT_HANDED_Y_UP uses):
        # OpenGL: X-right, Y-up, Z-backward
        # From OpenCV: negate Y and Z
        pts_cam = np.stack([cam_x, -cam_y, -cam_z], axis=-1)  # (N, 3)

        # Transform to world frame
        R = quaternion_to_rotation_matrix(bundle.orientation)
        t = np.array(bundle.translation, dtype=np.float32)
        pts_world = (R @ pts_cam.T).T + t  # (N, 3)

        total_points = len(pts_world)

        # Update occupancy grid (height filtering happens inside)
        robot_x = bundle.translation[0]
        robot_z = bundle.translation[2]
        self.grid.update(robot_x, robot_z, pts_world)

        # Count obstacles for logging
        y = pts_world[:, 1]
        n_obstacle = int(
            np.sum((y > self.grid.FLOOR_MIN) & (y < self.grid.ROBOT_HEIGHT))
        )

        return total_points, n_obstacle

    async def _publish_costmap(self):
        if self._last_frame < 0:
            return

        loop = asyncio.get_running_loop()
        costmap = await loop.run_in_executor(None, self.grid.get_costmap)

        grid = self.grid
        payload = json.dumps(
            {
                "frame_number": self._last_frame,
                "timestamp": self._last_timestamp,
                "resolution": grid.CELL_SIZE,
                "width": grid.GRID_SIZE,
                "height": grid.GRID_SIZE,
                "origin_x": grid.origin_x,
                "origin_z": grid.origin_z,
                "encoding": "flat_u8",
                "cells": costmap.ravel().tolist(),
                "counts": {
                    "unknown": int(np.count_nonzero(costmap == COSTMAP_UNKNOWN)),
                    "traversable": int(
                        np.count_nonzero(costmap == COSTMAP_TRAVERSABLE)
                    ),
                    "caution": int(np.count_nonzero(costmap == COSTMAP_CAUTION)),
                    "blocked": int(np.count_nonzero(costmap == COSTMAP_BLOCKED)),
                },
            }
        ).encode()

        await self.nc.publish(NAV_LOCAL_COSTMAP_SUBJECT, payload)
        self._publish_count += 1

    async def _publish_health(self):
        payload = json.dumps(
            {
                "received_count": self._received_count,
                "replaced_count": self._replaced_count,
                "processed_count": self._processed_count,
                "last_frame": self._last_frame,
                "last_process_ms": round(self._last_process_ms, 1),
                "last_points_count": self._last_points_count,
                "last_obstacle_count": self._last_obstacle_count,
                "publish_count": self._publish_count,
                "grid_origin_x": round(self.grid.origin_x, 2),
                "grid_origin_z": round(self.grid.origin_z, 2),
            }
        ).encode()
        await self.nc.publish(HEALTH_SUBJECT, payload)


if __name__ == "__main__":
    Node().run_node()

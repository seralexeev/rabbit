import json
from typing import Optional, List, Dict, Any

import cv2
import numpy as np
import torch
from lib.model import CameraIntrinsics, Pose
from lib.node import RabbitNode
from nats.aio.msg import Msg
from nats.js.kv import KeyValue
from nvblox_torch.indexing import get_voxel_center_grids
from nvblox_torch.mapper import Mapper
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
    return T


class Node(RabbitNode):
    # Constants
    MIN_DEPTH = 0.1
    MAX_DEPTH = 10.0
    VOXEL_SIZE = 0.05
    MAX_INTEGRATION_DISTANCE = 5.0
    SURFACE_THRESHOLD_MULTIPLIER = 2.0
    MIN_WEIGHT_THRESHOLD = 0.1

    def __init__(self):
        super().__init__("nvblox")

        self.mapper: Optional[Mapper] = None
        self.intrinsics_matrix: Optional[torch.Tensor] = None
        self.latest_depth: Optional[np.ndarray] = None
        self.latest_rgb: Optional[np.ndarray] = None
        self.latest_pose: Optional[Pose] = None
        self.processing = False

        # Initialize mapper
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
        await self.nc.subscribe("rabbit.zed.frame", cb=self.on_rgb_frame)
        await self.nc.subscribe("rabbit.zed.depth", cb=self.on_depth_frame)
        await self.watch_kv("rabbit.zed.pose", self.on_pose_update)

        self.set_interval(self.update_and_publish_map, 5)
        self.set_interval(self.process_frame, 0.1)

    async def load_camera_intrinsics(self):
        entry = await self.kv.get("rabbit.zed.intrinsics")
        if entry.value is None:
            raise KeyError("Camera intrinsics not found in KeyValue store")

        intrinsics = CameraIntrinsics.model_validate_json(entry.value)
        self.intrinsics_matrix = torch.tensor(
            [
                [intrinsics.fx, 0, intrinsics.cx],
                [0, intrinsics.fy, intrinsics.cy],
                [0, 0, 1],
            ],
            dtype=torch.float32,
        )

        self.logger.info(f"Loaded camera intrinsics: {intrinsics}")

    async def on_rgb_frame(self, msg: Msg):
        nparr = np.frombuffer(msg.data, np.uint8)
        rgb_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        self.latest_rgb = cv2.cvtColor(rgb_image, cv2.COLOR_BGR2RGB)

    async def on_depth_frame(self, msg: Msg):
        headers = msg.headers or {}
        depth_scale = float(headers.get("depth_scale", 0.001))
        nparr = np.frombuffer(msg.data, np.uint8)
        depth_image = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
        depth_image = depth_image.astype(np.float32) * depth_scale
        depth_image = np.nan_to_num(depth_image, nan=0.0)

        # Apply depth filtering
        valid_mask = (depth_image > self.MIN_DEPTH) & (depth_image < self.MAX_DEPTH)
        depth_image[~valid_mask] = 0.0

        self.latest_depth = depth_image

    async def on_pose_update(self, entry: KeyValue.Entry):
        if entry.value:
            self.latest_pose = Pose.model_validate_json(entry.value)

    async def process_frame(self):
        if (
            self.processing
            or self.latest_rgb is None
            or self.latest_depth is None
            or self.latest_pose is None
            or self.mapper is None
            or self.intrinsics_matrix is None
        ):
            return

        self.processing = True

        # Convert pose to transformation matrix
        pose_matrix = pose_to_transformation_matrix(
            self.latest_pose.translation, self.latest_pose.orientation
        )
        pose_tensor = torch.from_numpy(pose_matrix).float()

        # Convert images to tensors
        depth_tensor = torch.from_numpy(self.latest_depth).float().cuda()
        rgb_tensor = torch.from_numpy(self.latest_rgb).cuda()

        # Add frames to mapper
        self.mapper.add_depth_frame(depth_tensor, pose_tensor, self.intrinsics_matrix)
        self.mapper.add_color_frame(rgb_tensor, pose_tensor, self.intrinsics_matrix)

        # Clear processed data to free memory
        self.latest_rgb = None
        self.latest_depth = None
        self.latest_pose = None

        self.processing = False

    def extract_surface_voxels(self) -> List[Dict[str, Any]]:
        """Extract voxels near the surface from TSDF."""
        if not self.mapper:
            return []

        tsdf_layer = self.mapper.tsdf_layer_view()
        blocks, indices = tsdf_layer.get_all_blocks()

        if len(blocks) == 0:
            return []

        voxel_size = tsdf_layer.voxel_size()
        surface_threshold = self.SURFACE_THRESHOLD_MULTIPLIER * voxel_size

        voxel_centers_list = get_voxel_center_grids(indices, voxel_size, device="cuda")

        all_surface_centers = []
        all_surface_tsdf = []
        all_surface_weights = []

        # Batch process all blocks
        for block, voxel_centers in zip(blocks, voxel_centers_list):
            tsdf_values = block[..., 0]
            weights = block[..., 1]

            # Find surface voxels
            surface_mask = (torch.abs(tsdf_values) < surface_threshold) & (
                weights > self.MIN_WEIGHT_THRESHOLD
            )

            if torch.any(surface_mask):
                all_surface_centers.append(voxel_centers[surface_mask])
                all_surface_tsdf.append(tsdf_values[surface_mask])
                all_surface_weights.append(weights[surface_mask])

        if not all_surface_centers:
            return []

        # Concatenate and convert to CPU in batch
        surface_centers = torch.cat(all_surface_centers).cpu().numpy()
        surface_tsdf = torch.cat(all_surface_tsdf).cpu().numpy()
        surface_weights = torch.cat(all_surface_weights).cpu().numpy()

        # Create voxel data with gradient colors
        voxel_data = []
        for i in range(len(surface_centers)):
            # Normalize TSDF for color gradient
            normalized_tsdf = np.clip(surface_tsdf[i] / surface_threshold, -1, 1)

            color = [
                int(255 * max(0, normalized_tsdf)),  # Red for outside
                int(128 * (1 - abs(normalized_tsdf))),  # Green at surface
                int(255 * max(0, -normalized_tsdf)),  # Blue for inside
            ]

            voxel_data.append(
                {
                    "position": surface_centers[i].tolist(),
                    "color": color,
                    "tsdf": float(surface_tsdf[i]),
                    "weight": float(surface_weights[i]),
                }
            )

        return voxel_data

    async def publish_voxel_map(self, voxel_data: List[Dict[str, Any]]):
        """Publish voxel map to object store."""
        if not voxel_data:
            return

        # Calculate bounds efficiently
        positions = np.array([v["position"] for v in voxel_data])
        bounds_min = positions.min(axis=0).tolist()
        bounds_max = positions.max(axis=0).tolist()

        voxel_output = {
            "voxels": voxel_data,
            "voxel_size": float(self.VOXEL_SIZE),
            "num_voxels": len(voxel_data),
            "bounds": {
                "min": bounds_min,
                "max": bounds_max,
            },
        }

        # Consider using msgpack here if performance matters
        await self.object_store.put(
            "rabbit.nvblox.voxels", json.dumps(voxel_output).encode()
        )

        self.logger.info(
            f"Published {len(voxel_data)} voxels, "
            f"bounds: [{bounds_min[0]:.2f}, {bounds_min[1]:.2f}, {bounds_min[2]:.2f}] "
            f"to [{bounds_max[0]:.2f}, {bounds_max[1]:.2f}, {bounds_max[2]:.2f}]"
        )

    async def update_and_publish_map(self):
        """Main update cycle for map processing."""
        surface_voxels = self.extract_surface_voxels()

        if not surface_voxels:
            self.logger.warning("No surface voxels found")
            return

        await self.publish_voxel_map(surface_voxels)


if __name__ == "__main__":
    Node().run_node()

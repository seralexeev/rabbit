import json
from typing import Optional

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
    def __init__(self):
        super().__init__("nvblox")

        self.mapper: Optional[Mapper] = None
        self.intrinsics_matrix: Optional[torch.Tensor] = None
        self.latest_depth: Optional[np.ndarray] = None
        self.latest_rgb: Optional[np.ndarray] = None
        self.latest_pose: Optional[Pose] = None
        self.processing = False

        projective_integrator_params = ProjectiveIntegratorParams()
        projective_integrator_params.projective_integrator_max_integration_distance_m = (
            5.0
        )

        mapper_params = MapperParams()
        mapper_params.set_projective_integrator_params(projective_integrator_params)

        self.mapper = Mapper(
            voxel_sizes_m=0.05,
            integrator_types=ProjectiveIntegratorType.TSDF,
            mapper_parameters=mapper_params,
        )

    async def init(self):
        await self.load_camera_intrinsics()
        await self.nc.subscribe("rabbit.zed.frame", cb=self.on_rgb_frame)
        await self.nc.subscribe("rabbit.zed.depth", cb=self.on_depth_frame)
        await self.watch_kv("rabbit.zed.pose", self.on_pose_update)

        self.set_interval(self.update_map, 5)
        self.set_interval(self.try_process, 0.1)

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
        valid_mask = (depth_image > 0.1) & (depth_image < 10.0)
        depth_image[~valid_mask] = 0.0

        self.latest_depth = depth_image

    async def on_pose_update(self, entry: KeyValue.Entry):
        if entry.value:
            self.latest_pose = Pose.model_validate_json(entry.value)

    async def try_process(self):
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

        pose_matrix = pose_to_transformation_matrix(
            self.latest_pose.translation, self.latest_pose.orientation
        )
        pose_tensor = torch.from_numpy(pose_matrix).float()
        depth_tensor = torch.from_numpy(self.latest_depth).float().cuda()
        rgb_tensor = torch.from_numpy(self.latest_rgb).cuda()
        self.mapper.add_depth_frame(depth_tensor, pose_tensor, self.intrinsics_matrix)
        self.mapper.add_color_frame(rgb_tensor, pose_tensor, self.intrinsics_matrix)
        self.processing = False

    async def update_map(self):
        tsdf_layer = self.mapper.tsdf_layer_view()
        blocks, indices = tsdf_layer.get_all_blocks()

        if len(blocks) == 0:
            self.logger.warning("No blocks allocated yet")
            return

        voxel_data = []
        voxel_size = tsdf_layer.voxel_size()

        self.logger.info(f"Processing {len(blocks)} blocks, voxel_size={voxel_size}")

        voxel_centers_list = get_voxel_center_grids(indices, voxel_size, device="cuda")

        # Loop over all blocks and extract surface voxels
        for block, voxel_centers in zip(blocks, voxel_centers_list):
            # Get TSDF values and weights
            tsdf_values = block[..., 0]  # First channel is distance
            weights = block[..., 1]  # Second channel is weight

            # Find voxels near surface (like in documentation examples)
            # Surface is where TSDF is close to 0 and has been observed
            surface_mask = (torch.abs(tsdf_values) < 0.1) & (weights > 0.1)

            if torch.any(surface_mask):
                # Get positions of surface voxels
                surface_centers = voxel_centers[surface_mask]
                surface_tsdf = tsdf_values[surface_mask]
                surface_weights = weights[surface_mask]

                # Convert to CPU and add to list
                surface_centers_cpu = surface_centers.cpu().numpy()
                surface_tsdf_cpu = surface_tsdf.cpu().numpy()
                surface_weights_cpu = surface_weights.cpu().numpy()

                for i in range(len(surface_centers_cpu)):
                    pos = surface_centers_cpu[i]
                    tsdf_val = float(surface_tsdf_cpu[i])
                    weight_val = float(surface_weights_cpu[i])

                    # Color based on TSDF value (blue inside, red outside)
                    if tsdf_val < 0:
                        color = [0, 0, 255]  # Blue for inside
                    else:
                        color = [255, 0, 0]  # Red for outside

                    voxel_data.append(
                        {
                            "position": [
                                float(pos[0]),
                                float(pos[1]),
                                float(pos[2]),
                            ],
                            "color": color,
                            "tsdf": tsdf_val,
                            "weight": weight_val,
                        }
                    )

        if len(voxel_data) == 0:
            self.logger.warning("No surface voxels found")
            return

        # Log some sample voxels for debugging
        sample_voxels = voxel_data[:3]
        self.logger.info(f"Sample voxels: {sample_voxels}")

        voxel_output = {
            "voxels": voxel_data,
            "voxel_size": float(voxel_size),
            "num_voxels": len(voxel_data),
            "bounds": {
                "min": [
                    float(min(v["position"][i] for v in voxel_data)) for i in range(3)
                ],
                "max": [
                    float(max(v["position"][i] for v in voxel_data)) for i in range(3)
                ],
            },
        }

        await self.object_store.put(
            "rabbit.nvblox.voxels", json.dumps(voxel_output).encode()
        )

        self.logger.info(
            f"Published {len(voxel_data)} voxels, bounds: {voxel_output['bounds']}"
        )


if __name__ == "__main__":
    Node().run_node()

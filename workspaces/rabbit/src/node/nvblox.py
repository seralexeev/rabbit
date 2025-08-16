import asyncio
import json
from typing import Optional

import cv2
import numpy as np
import torch
from nats.aio.msg import Msg

from lib.model import CameraIntrinsics, Pose
from lib.node import RabbitNode
from nvblox_torch.mapper import Mapper
from nvblox_torch.mapper_params import MapperParams, ProjectiveIntegratorParams
from nvblox_torch.projective_integrator_types import ProjectiveIntegratorType


def quaternion_to_rotation_matrix(q):
    """Convert quaternion [x, y, z, w] to rotation matrix"""
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def pose_to_transformation_matrix(translation, orientation):
    """Convert translation and quaternion to 4x4 transformation matrix"""
    T = np.eye(4, dtype=np.float32)
    T[:3, :3] = quaternion_to_rotation_matrix(orientation)
    T[:3, 3] = translation
    return T


class Node(RabbitNode):
    def __init__(self):
        super().__init__("nvblox")

        self.mapper: Optional[Mapper] = None
        self.intrinsics_matrix: Optional[torch.Tensor] = None

        # Simple frame storage
        self.latest_depth: Optional[np.ndarray] = None
        self.latest_rgb: Optional[np.ndarray] = None
        self.latest_pose: Optional[dict] = None

        # Processing control
        self.processing = False

    async def init(self):
        await self.load_camera_intrinsics()
        await self.init_mapper()
        await self.subscribe_to_data()

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

    async def init_mapper(self):
        """Initialize nvblox mapper"""
        # Simple parameters
        projective_integrator_params = ProjectiveIntegratorParams()
        projective_integrator_params.projective_integrator_max_integration_distance_m = (
            5.0
        )

        mapper_params = MapperParams()
        mapper_params.set_projective_integrator_params(projective_integrator_params)

        self.mapper = Mapper(
            voxel_sizes_m=0.05,  # 5cm voxels
            integrator_types=ProjectiveIntegratorType.TSDF,
            mapper_parameters=mapper_params,
        )

        self.logger.info("NVBlox mapper initialized")

    async def subscribe_to_data(self):
        """Subscribe to camera data"""
        await self.nc.subscribe("rabbit.zed.frame", cb=self.on_rgb_frame)
        await self.nc.subscribe("rabbit.zed.depth", cb=self.on_depth_frame)
        await self.watch_kv("rabbit.zed.pose", self.on_pose_update)

        self.logger.info("Subscribed to camera data")

    async def on_rgb_frame(self, msg: Msg):
        """Handle RGB frame"""
        try:
            nparr = np.frombuffer(msg.data, np.uint8)
            rgb_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            self.latest_rgb = cv2.cvtColor(rgb_image, cv2.COLOR_BGR2RGB)
            await self.try_process()
        except Exception as e:
            self.logger.error(f"Error processing RGB: {e}")

    async def on_depth_frame(self, msg: Msg):
        """Handle depth frame"""
        try:
            headers = msg.headers or {}
            depth_scale = float(headers.get("depth_scale", 0.001))

            nparr = np.frombuffer(msg.data, np.uint8)
            depth_image = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)

            # Convert back to meters and clean
            depth_image = depth_image.astype(np.float32) * depth_scale
            depth_image = np.nan_to_num(depth_image, nan=0.0)

            # Filter valid depths
            valid_mask = (depth_image > 0.1) & (depth_image < 10.0)
            depth_image[~valid_mask] = 0.0

            self.latest_depth = depth_image
            await self.try_process()

        except Exception as e:
            self.logger.error(f"Error processing depth: {e}")

    async def on_pose_update(self, entry):
        """Handle pose update"""
        try:
            if entry.value:
                self.latest_pose = json.loads(entry.value.decode())
                await self.try_process()
        except Exception as e:
            self.logger.error(f"Error processing pose: {e}")

    async def try_process(self):
        """Try to process frame if all data available"""
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
        try:
            # Convert pose to transformation matrix
            pose_matrix = pose_to_transformation_matrix(
                self.latest_pose["translation"], self.latest_pose["orientation"]
            )
            pose_tensor = torch.from_numpy(pose_matrix).float()

            # Convert to tensors
            depth_tensor = torch.from_numpy(self.latest_depth).float().cuda()
            rgb_tensor = torch.from_numpy(self.latest_rgb).cuda()

            # Add to mapper
            self.mapper.add_depth_frame(
                depth_tensor, pose_tensor, self.intrinsics_matrix
            )
            self.mapper.add_color_frame(rgb_tensor, pose_tensor, self.intrinsics_matrix)

            # Update and publish mesh every 10 frames
            frame_num = self.latest_pose.get("frame_number", 0)
            if frame_num % 100 == 0:
                await self.update_mesh()

            self.logger.debug(f"Processed frame {frame_num}")

        except Exception as e:
            self.logger.error(f"Error in processing: {e}")
        finally:
            self.processing = False

    async def update_mesh(self):
        """Update and publish voxel data using nvblox proper methods"""
        try:
            # Get TSDF layer
            tsdf_layer = self.mapper.tsdf_layer_view()

            # Get all allocated blocks and their indices (like in voxels.py example)
            blocks, indices = tsdf_layer.get_all_blocks()

            if len(blocks) == 0:
                self.logger.warning("No blocks allocated yet")
                return

            voxel_data = []
            voxel_size = tsdf_layer.voxel_size()

            self.logger.info(
                f"Processing {len(blocks)} blocks, voxel_size={voxel_size}"
            )

            # Get voxel center grids for each block (from nvblox indexing module)
            from nvblox_torch.indexing import get_voxel_center_grids

            voxel_centers_list = get_voxel_center_grids(
                indices, voxel_size, device="cuda"
            )

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
                        float(min(v["position"][i] for v in voxel_data))
                        for i in range(3)
                    ],
                    "max": [
                        float(max(v["position"][i] for v in voxel_data))
                        for i in range(3)
                    ],
                },
            }

            # Publish voxel data
            await self.object_store.put(
                "rabbit.nvblox.voxels", json.dumps(voxel_output).encode()
            )

            self.logger.info(
                f"Published {len(voxel_data)} voxels, bounds: {voxel_output['bounds']}"
            )

        except Exception as e:
            self.logger.error(f"Error updating voxels: {e}")
            import traceback

            self.logger.error(f"Traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    Node().run_node()

#
# Copyright (c) 2023 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
#
import os

import imageio.v3
import numpy as np
import torch
from torch.utils.data.dataset import Dataset
from transforms3d.quaternions import quat2mat


class Sun3dDataset(Dataset):
    """Sun3d dataset for testing and evaluation.
    """

    def __init__(self, root: str, device: str = 'cuda') -> None:
        super().__init__()
        self.root = root
        self.device = device

        cam_intrinsics_np = np.loadtxt(os.path.join(self.root, 'camera-intrinsics.txt'))
        self.camera_intrinsics = torch.from_numpy(cam_intrinsics_np).float()
        self.sequence_name = list(
            sorted([d for d in os.listdir(self.root)
                    if os.path.isdir(os.path.join(self.root, d))]))[0]
        self.seq_dir = os.path.join(self.root, self.sequence_name)

        self.frame_names = list(sorted({f.split('.')[0] for f in os.listdir(self.seq_dir)}))

    def __len__(self) -> int:
        return len(self.frame_names)

    def __getitem__(self, index: int) -> dict:
        """rgba: HxWx4, depth HxWx1"""
        # Load the raw data
        frame_name = self.frame_names[index]
        rgb_np = imageio.imread(os.path.join(self.seq_dir, f'{frame_name}.color.png'))
        depth_np = imageio.imread(os.path.join(self.seq_dir, f'{frame_name}.depth.png'))
        pose_np = np.loadtxt(os.path.join(self.seq_dir, f'{frame_name}.pose.txt'))

        # Color
        # Give an alpha channel
        rgb = torch.tensor(rgb_np, device=self.device)

        # Depth
        # Convert to uint16 -> float and give a feature channel.
        depth_np = depth_np.astype(np.float32) / 1000
        depth = torch.tensor(depth_np, device=self.device)
        depth = depth.squeeze()
        depth = depth.unsqueeze(dim=-1)

        # Pose
        # Conversion in nvblox:
        # Rotate the world frame since Y is up in the normal 3D match dasets.
        # Eigen::Quaternionf q_L_O = Eigen::Quaternionf::FromTwoVectors(Vector3f(0, 1, 0),
        # Vector3f(0, 0, 1));
        pose = torch.tensor(pose_np, device=self.device, dtype=torch.float32)
        eigen_quat = [0.707106769, 0.707106769, 0, 0]
        sun3d_to_nvblox_T = torch.eye(4, device=self.device, dtype=torch.float32)
        sun3d_to_nvblox_T[:3, :3] = torch.tensor(quat2mat(eigen_quat), device=self.device)
        nvblox_pose = sun3d_to_nvblox_T @ pose

        # Post-conditions
        assert rgb.shape[-1] == 3, 'Only 3-channel RGB images supported by nvblox'
        assert depth.shape[-1] == 1, 'Only 1-channel depth images supported by nvblox'
        assert rgb.dtype == torch.uint8, 'Only 8-bit RGB images supported'
        assert depth.dtype == torch.float, 'CPP-side conversions assume 32-bit float tensors'
        assert pose.dtype == torch.float, 'CPP-side conversions assume 32-bit float tensors'
        assert self.camera_intrinsics.dtype == torch.float, \
            'CPP-side conversions assume 32-bit float tensors'

        return {
            'rgb': rgb,
            'depth': depth,
            'pose': nvblox_pose,
            'intrinsics': self.camera_intrinsics,
        }

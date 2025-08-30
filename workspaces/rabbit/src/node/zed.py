import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import cv2
import lz4.frame
import numpy as np
from lib.model import CameraIntrinsics, Pose
from lib.node import RabbitNode
from nats.js.errors import KeyNotFoundError
from nats.js.kv import KeyValue
from pydantic import BaseModel, Field
from pyzed import sl


class CameraSettings(BaseModel):
    BRIGHTNESS: int = Field(default=4, ge=0, le=8)
    CONTRAST: int = Field(default=4, ge=0, le=8)
    HUE: int = Field(default=0, ge=0, le=11)
    SATURATION: int = Field(default=4, ge=0, le=8)
    SHARPNESS: int = Field(default=4, ge=0, le=8)
    GAMMA: int = Field(default=5, gt=1, le=9)
    GAIN: int = Field(default=97, ge=0, le=100)
    EXPOSURE: int = Field(default=67, ge=0, le=100)
    WHITEBALANCE_TEMPERATURE: int = Field(default=4700, ge=2800, le=6500)
    WHITEBALANCE_AUTO: int = Field(default=1, ge=0, le=1)


class Node(RabbitNode):
    CAMERA_SETTINGS_KEY = "rabbit.zed.camera_settings"

    def __init__(self):
        super().__init__("rabbit-zed")

        self.image = sl.Mat()
        self.depth = sl.Mat()
        self.zed = sl.Camera()
        self.pose = sl.Pose()

        self.runtime_params = sl.RuntimeParameters()
        self.camera_parameters = sl.CameraParameters()
        self.camera_fps = 30

        self.init_params = sl.InitParameters(
            camera_resolution=sl.RESOLUTION.HD720,
            camera_fps=self.camera_fps,
            depth_mode=sl.DEPTH_MODE.NEURAL_LIGHT,
            coordinate_units=sl.UNIT.METER,
            coordinate_system=sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP,
            sdk_verbose=1,
        )

        self.positional_tracking_parameters = sl.PositionalTrackingParameters()
        self.positional_tracking_parameters.set_floor_as_origin = True
        self.frame_number = -1
        self.timestamp = 0

    async def init(self):
        status = self.zed.open(self.init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Camera initialization failed: {status}")

        status = self.zed.enable_positional_tracking(
            self.positional_tracking_parameters
        )
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to enable positional tracking: {status}")

        await self.publish_camera_intrinsics()
        await self.init_camera_settings()
        await self.watch_kv(self.CAMERA_SETTINGS_KEY, self.on_camera_settings_update)
        await self.async_task(self.capture_loop)

        self.set_interval(self.publish_depth, 1 / self.camera_fps)
        self.set_interval(self.publish_image, 1 / self.camera_fps)
        self.set_interval(self.publish_pose, 1 / self.camera_fps)
        self.set_interval(self.nc.flush, 1 / self.camera_fps)

    async def close(self):
        self.zed.close()

    async def publish_camera_intrinsics(self):
        camera_info = self.zed.get_camera_information()
        left_cam = camera_info.camera_configuration.calibration_parameters.left_cam

        intrinsics = CameraIntrinsics(
            fx=left_cam.fx,
            fy=left_cam.fy,
            cx=left_cam.cx,
            cy=left_cam.cy,
            width=camera_info.camera_configuration.resolution.width,
            height=camera_info.camera_configuration.resolution.height,
        ).model_dump_json()

        await self.kv.put("rabbit.zed.intrinsics", intrinsics.encode())
        self.logger.info(f"Published camera intrinsics")

    async def init_camera_settings(self):
        try:
            await self.kv.get(self.CAMERA_SETTINGS_KEY)
            self.logger.info("Camera settings loaded from KeyValue store")
        except KeyNotFoundError:
            settings = self.get_camera_settings()
            await self.kv.put(
                self.CAMERA_SETTINGS_KEY, settings.model_dump_json().encode()
            )
            self.logger.info(
                f"Camera settings not found, initializing default settings: {settings.model_dump()}"
            )

    async def on_camera_settings_update(self, entry: KeyValue.Entry):
        if entry.value is not None:
            settings = CameraSettings.model_validate_json(entry.value)
            self.set_camera_settings(settings)

    async def capture_loop(self):
        status = self.zed.grab(self.runtime_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to grab image from ZED camera: {status}")

        self.frame_number += 1
        self.timestamp = self.zed.get_timestamp(
            sl.TIME_REFERENCE.IMAGE
        ).get_nanoseconds()

        status = self.zed.retrieve_image(self.image, sl.VIEW.LEFT)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to retrieve RGB image: {status}")

    async def publish_pose(self):
        state = self.zed.get_position(self.pose, sl.REFERENCE_FRAME.WORLD)
        if state == sl.POSITIONAL_TRACKING_STATE.OK:
            pose = Pose(
                translation=self.pose.get_translation().get(),
                orientation=self.pose.get_orientation().get(),
                frame_number=self.frame_number,
                timestamp=self.timestamp,
            ).model_dump_json()

            await self.kv.put("rabbit.zed.pose", pose.encode())

    async def publish_image(self):
        frame_data = self.image.get_data()
        frame_number = self.frame_number

        async def encode_publish():
            frame_rgb = np.ascontiguousarray(frame_data[:, :, :3])

            success, buffer = await asyncio.to_thread(
                cv2.imencode,
                ".jpg",
                frame_rgb,
                [cv2.IMWRITE_JPEG_QUALITY, 50],
            )
            if not success:
                raise RuntimeError("Failed to encode RGB image")

            await self.nc.publish(
                "rabbit.zed.frame",
                buffer.tobytes(),
                headers={
                    "type": "image/jpeg",
                    "width": str(frame_rgb.shape[1]),
                    "height": str(frame_rgb.shape[0]),
                    "frame_number": str(frame_number),
                    "timestamp": str(self.timestamp),
                },
            )

        await asyncio.create_task(encode_publish())

    async def publish_depth(self):
        status = self.zed.retrieve_measure(
            self.depth,
            sl.MEASURE.DEPTH,
            resolution=sl.Resolution(width=640, height=480),
        )
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to retrieve depth image: {status}")

        depth_data = self.depth.get_data()

        d = np.nan_to_num(depth_data, nan=0.0, posinf=0.0, neginf=0.0)
        d = np.clip(d, 0.0, 16.0)
        u16 = (d * 1000.0).astype(np.uint16)
        compressed = lz4.frame.compress(u16.tobytes())

        await self.nc.publish(
            "rabbit.zed.depth",
            compressed,
            headers={
                "enc": "DEPTH_MM_U16_LZ4",
                "w": "640",
                "h": "480",
                "timestamp": str(self.timestamp),
            },
        )

    def get_camera_settings(self) -> CameraSettings:
        settings = CameraSettings()
        for setting_str in CameraSettings.model_fields.keys():
            camera_setting = sl.VIDEO_SETTINGS[setting_str]
            error, value = self.zed.get_camera_settings(camera_setting)
            if error != sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(
                    f"Failed to get camera setting {setting_str}: {error}"
                )
            setattr(settings, setting_str, value)

        return settings

    def set_camera_settings(self, setting: CameraSettings):
        current_settings = self.get_camera_settings().model_dump()
        new_settings = setting.model_dump()
        diff = {
            key: new_settings[key]
            for key in new_settings
            if current_settings.get(key) != new_settings[key]
        }

        if "WHITEBALANCE_TEMPERATURE" in diff:
            diff.pop("WHITEBALANCE_AUTO", None)

        for key, value in diff.items():
            camera_setting = sl.VIDEO_SETTINGS[key]
            err = self.zed.set_camera_settings(camera_setting, value)
            if err != sl.ERROR_CODE.SUCCESS:
                self.logger.error(f"Failed to set camera setting {key}: {err}")


if __name__ == "__main__":
    Node().run_node()

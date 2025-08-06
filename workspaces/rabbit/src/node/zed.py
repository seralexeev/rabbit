from asyncio import Task
from typing import Optional

import cv2
from lib.node import RabbitNode
from nats.aio.msg import Msg
from nats.js.errors import KeyNotFoundError
from nats.js.kv import KeyValue
from pydantic import BaseModel
from pyzed import sl


class VideoSettings(BaseModel):
    BRIGHTNESS: int = -1
    CONTRAST: int = -1
    HUE: int = -1
    SATURATION: int = -1
    SHARPNESS: int = -1
    GAMMA: int = -1
    GAIN: int = -1
    EXPOSURE: int = -1
    WHITEBALANCE_TEMPERATURE: int = -1
    WHITEBALANCE_AUTO: int = -1


class Node(RabbitNode):
    VIDEO_SETTINGS_KEY = "rabbit.zed.video_settings"

    VIDEO_SETTINGS_RANGE = {
        sl.VIDEO_SETTINGS.BRIGHTNESS: (0, 8),
        sl.VIDEO_SETTINGS.CONTRAST: (0, 8),
        sl.VIDEO_SETTINGS.HUE: (0, 11),
        sl.VIDEO_SETTINGS.SATURATION: (0, 8),
        sl.VIDEO_SETTINGS.SHARPNESS: (0, 8),
        sl.VIDEO_SETTINGS.GAMMA: (1, 8),
        sl.VIDEO_SETTINGS.GAIN: (0, 100),
        sl.VIDEO_SETTINGS.EXPOSURE: (0, 100),
        sl.VIDEO_SETTINGS.WHITEBALANCE_TEMPERATURE: (2800, 6500),
        sl.VIDEO_SETTINGS.WHITEBALANCE_AUTO: (0, 1),
    }

    def __init__(self):
        super().__init__("rabbit-zed")

        self.operator_timeout: Optional[Task] = None
        self.frame = sl.Mat()
        self.zed = sl.Camera()
        self.runtime_params = sl.RuntimeParameters()
        self.camera_parameters = sl.CameraParameters()
        self.init_params = sl.InitParameters(
            camera_resolution=sl.RESOLUTION.HD720,
            camera_fps=30,
            depth_mode=sl.DEPTH_MODE.NEURAL_LIGHT,
            coordinate_units=sl.UNIT.METER,
            coordinate_system=sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP,
            sdk_verbose=1,
        )

    async def init(self):
        status = self.zed.open(self.init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Camera initialization failed: {status}")

        await self.init_video_settings()
        await self.watch_kv(self.VIDEO_SETTINGS_KEY, self.on_video_settings_update)
        await self.nc.subscribe("rabbit.zed.viewer", cb=self.on_operator_update)
        await self.async_task(self.capture_frame)

    async def close(self):
        self.zed.close()

    async def on_operator_update(self, _: Msg):
        self.logger.info(f"Ping from operator")

        def clear_operator():
            if self.operator_timeout is not None:
                self.operator_timeout.cancel()
                self.operator_timeout = None
                self.logger.info("Operator disconnected")

        if self.operator_timeout is not None:
            self.operator_timeout.cancel()
        self.operator_timeout = self.set_timeout(clear_operator, 5)

    async def init_video_settings(self):
        try:
            await self.kv.get(self.VIDEO_SETTINGS_KEY)
            self.logger.info("Camera settings loaded from KeyValue store")
        except KeyNotFoundError:
            self.logger.info("Camera settings not found, initializing default settings")
            setting = self.get_camera_settings()
            await self.kv.put(
                self.VIDEO_SETTINGS_KEY, setting.model_dump_json().encode()
            )
            self.logger.info("Camera settings initialized and saved to KeyValue store")

    async def on_video_settings_update(self, entry: KeyValue.Entry):
        self.logger.info(f"Video settings updated: {entry.key}")
        if entry.value is not None:
            settings = VideoSettings.model_validate_json(entry.value.decode())
            self.set_camera_settings(settings)

    async def capture_frame(self):
        status = self.zed.grab(self.runtime_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to grab image from ZED camera: {status}")

        status = self.zed.retrieve_image(self.frame, sl.VIEW.RIGHT)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to retrieve image: {status}")

        await self.publish_frame()

    async def publish_frame(self):
        if not self.operator_timeout:
            return

        frame_data = self.frame.get_data()
        frame_rgb = frame_data[:, :, :3]

        success, buffer = cv2.imencode(
            ".jpg", frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 75]
        )

        if not success:
            raise RuntimeError("Failed to encode image")

        await self.nc.publish(
            "rabbit.zed.frame",
            buffer.tobytes(),
            headers={
                "type": "image/jpg",
                "width": str(frame_rgb.shape[1]),
                "height": str(frame_rgb.shape[0]),
            },
        )

        await self.nc.flush()

    def reset_camera_settings(self):
        for setting, _ in self.VIDEO_SETTINGS_RANGE.items():
            if self.zed.set_camera_settings(setting) != sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(f"Failed to reset camera setting: {setting}")

    def get_camera_settings(self) -> VideoSettings:
        settings = VideoSettings()
        for setting_str in VideoSettings.model_fields.keys():
            video_setting = sl.VIDEO_SETTINGS[setting_str]
            value = self.zed.get_camera_settings(video_setting)
            setattr(settings, setting_str, value)

        return settings

    def set_camera_settings(self, setting: VideoSettings):
        for key, value in setting.model_dump().items():
            video_setting = sl.VIDEO_SETTINGS[key]
            range = self.VIDEO_SETTINGS_RANGE.get(video_setting)
            if range is None:
                self.logger.warning(f"Unknown video setting: {key}")
                continue
            value = max(min(value, range[1]), range[0])
            err = self.zed.set_camera_settings(video_setting, value)
            if err != sl.ERROR_CODE.SUCCESS:
                self.logger.error(f"Failed to set camera setting {key}: {err}")


if __name__ == "__main__":
    Node().run_node()

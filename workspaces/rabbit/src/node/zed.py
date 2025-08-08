from asyncio import Task
from typing import Annotated, Optional

import cv2
from lib.node import RabbitNode
from nats.aio.msg import Msg
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
    GAMMA: int = Field(default=5, gt=0, le=8)
    GAIN: int = Field(default=97, ge=0, le=100)
    EXPOSURE: int = Field(default=67, ge=0, le=100)
    WHITEBALANCE_TEMPERATURE: int = Field(default=4700, ge=2800, le=6500)
    WHITEBALANCE_AUTO: int = Field(default=1, ge=0, le=1)


class Node(RabbitNode):
    CAMERA_SETTINGS_KEY = "rabbit.zed.camera_settings"

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

        await self.init_camera_settings()
        await self.watch_kv(self.CAMERA_SETTINGS_KEY, self.on_camera_settings_update)
        # await self.watch_kv("rabbit.operator.alive", self.on_operator_alive)
        await self.async_task(self.capture_frame)

    async def close(self):
        self.zed.close()

    async def on_operator_alive(self, entry: KeyValue.Entry):
        self.logger.info(f"Ping from operator ${entry}")

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
        self.logger.info(f"Camera settings updated: {entry.key}")
        if entry.value is not None:
            settings = CameraSettings.model_validate_json(entry.value)
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
        # if not self.operator_timeout:
        #     return

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
        for key, value in setting.model_dump().items():
            camera_setting = sl.VIDEO_SETTINGS[key]
            err = self.zed.set_camera_settings(camera_setting, value)
            if err != sl.ERROR_CODE.SUCCESS:
                self.logger.error(f"Failed to set camera setting {key}: {err}")


if __name__ == "__main__":
    Node().run_node()

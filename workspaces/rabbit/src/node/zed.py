import json

import cv2
from lib.node import RabbitNode
from nats.js.errors import KeyNotFoundError
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
        sl.VIDEO_SETTINGS.GAMMA: (0, 8),
        sl.VIDEO_SETTINGS.GAIN: (0, 100),
        sl.VIDEO_SETTINGS.EXPOSURE: (0, 100),
        sl.VIDEO_SETTINGS.WHITEBALANCE_TEMPERATURE: (2800, 6500),
        sl.VIDEO_SETTINGS.WHITEBALANCE_AUTO: (0, 1),
    }

    zed = sl.Camera()
    init_params = sl.InitParameters(
        camera_resolution=sl.RESOLUTION.HD720,
        camera_fps=30,
        depth_mode=sl.DEPTH_MODE.NEURAL_LIGHT,
        coordinate_units=sl.UNIT.METER,
        coordinate_system=sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP,
        sdk_verbose=1,
    )

    runtime_params = sl.RuntimeParameters()
    camera_parameters = sl.CameraParameters()
    frame = sl.Mat()

    def __init__(self):
        super().__init__("zed")

    async def init(self):
        status = self.zed.open(self.init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"ZED camera initialization failed: {status}")

        await self.init_camera_settings()
        self.video_settings_watcher = await self.kv.watch(self.VIDEO_SETTINGS_KEY)

        await self.task(self.camera_settings_watcher)
        await self.task(self.capture_frame)

    async def init_camera_settings(self):
        try:
            await self.kv.get(self.VIDEO_SETTINGS_KEY)
            print("Camera settings found in KeyValue store")
        except KeyNotFoundError:
            print("Camera settings not found in KeyValue store, initializing defaults")
            setting = self.get_camera_settings()
            await self.kv.put(
                self.VIDEO_SETTINGS_KEY, setting.model_dump_json().encode()
            )
            print("Camera settings initialized and saved to KeyValue store")

    async def camera_settings_watcher(self):
        print("Watching camera settings in KeyValue store")
        async for entry in self.video_settings_watcher:
            if entry.value is not None:
                settings = VideoSettings.model_validate_json(entry.value.decode())
                self.set_camera_settings(settings)

        print("Stopped watching camera settings in KeyValue store")

    async def capture_frame(self):
        if self.zed.grab(self.runtime_params) != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError("Failed to grab image from ZED camera")

        self.zed.retrieve_image(self.frame, sl.VIEW.RIGHT)
        frame_data = self.frame.get_data()
        frame_rgb = frame_data[:, :, :3]

        success, buffer = cv2.imencode(
            ".jpg", frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 75]
        )

        if not success:
            raise RuntimeError("Failed to encode image")

        await self.nc.publish(
            "rabbit.camera.frame",
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
                print(f"Invalid camera setting: {key}")
                continue
            value = max(min(value, range[1]), range[0])
            err = self.zed.set_camera_settings(video_setting, value)
            if err != sl.ERROR_CODE.SUCCESS:
                print(f"Failed to set camera setting {key}: {err}")


if __name__ == "__main__":
    Node().run_node()

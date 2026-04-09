import asyncio
import json

import cv2
import lz4.frame
import numpy as np
from lib.model import (
    DEPTH_ENCODING_MM_U16_LZ4,
    RGB_ENCODING_JPEG,
    SENSOR_BUNDLE_SUBJECT,
    CameraIntrinsics,
    Pose,
    SensorBundle,
    serialize_sensor_bundle,
)
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
    POSE_SUBJECT = "rabbit.zed.pose"
    PREVIEW_SUBJECT = "rabbit.zed.frame.preview"
    LEGACY_PREVIEW_SUBJECT = "rabbit.zed.frame"
    HEALTH_SUBJECT = "rabbit.health.zed"
    PREVIEW_FPS = 10
    INCLUDE_RGB_IN_BUNDLE = False

    def __init__(self):
        super().__init__("rabbit-zed")

        self.image = sl.Mat()
        self.depth = sl.Mat()
        self.zed = sl.Camera()
        self.pose = sl.Pose()

        self.runtime_params = sl.RuntimeParameters()
        self.camera_parameters = sl.CameraParameters()
        self.camera_fps = 30
        self.preview_every_n_frames = 1

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
        self.bundle_messages = 0
        self.bundle_bytes = 0
        self.preview_messages = 0
        self.preview_bytes = 0
        self.pose_messages = 0
        self.pose_drop_count = 0
        self.last_capture_duration_ms = 0.0
        self.last_pose_state = "UNKNOWN"
        self.last_bundle_frame = -1
        self.last_preview_frame = -1

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
        self.preview_every_n_frames = max(
            1, round(self.camera_fps / self.PREVIEW_FPS)
        )

        self.set_interval(self.capture_and_publish, 1 / self.camera_fps, max_parallel=1)
        self.set_interval(self.publish_health, 1, max_parallel=1)

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

    def _encode_depth_payload(self, depth_data: np.ndarray) -> bytes:
        d = np.nan_to_num(depth_data, nan=0.0, posinf=0.0, neginf=0.0)
        d = np.clip(d, 0.0, 16.0)
        u16 = (d * 1000.0).astype(np.uint16)
        return lz4.frame.compress(u16.tobytes())

    def _encode_preview_frame(self, frame_rgb: np.ndarray) -> bytes:
        success, buffer = cv2.imencode(
            ".jpg",
            frame_rgb,
            [cv2.IMWRITE_JPEG_QUALITY, 50],
        )
        if not success:
            raise RuntimeError("Failed to encode RGB image")
        return buffer.tobytes()

    async def publish_health(self):
        payload = json.dumps(
            {
                "frame_number": self.frame_number,
                "timestamp": self.timestamp,
                "camera_fps": self.camera_fps,
                "preview_every_n_frames": self.preview_every_n_frames,
                "bundle_messages": self.bundle_messages,
                "bundle_bytes": self.bundle_bytes,
                "preview_messages": self.preview_messages,
                "preview_bytes": self.preview_bytes,
                "pose_messages": self.pose_messages,
                "pose_drop_count": self.pose_drop_count,
                "last_capture_duration_ms": self.last_capture_duration_ms,
                "last_pose_state": self.last_pose_state,
                "last_bundle_frame": self.last_bundle_frame,
                "last_preview_frame": self.last_preview_frame,
            }
        ).encode()
        await self.nc.publish(self.HEALTH_SUBJECT, payload)

    async def capture_and_publish(self):
        loop = asyncio.get_running_loop()
        started = loop.time()

        status = self.zed.grab(self.runtime_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to grab image from ZED camera: {status}")

        self.frame_number += 1
        self.timestamp = self.zed.get_timestamp(
            sl.TIME_REFERENCE.IMAGE
        ).get_nanoseconds()

        state = self.zed.get_position(self.pose, sl.REFERENCE_FRAME.WORLD)
        self.last_pose_state = str(state)

        status = self.zed.retrieve_measure(
            self.depth,
            sl.MEASURE.DEPTH,
            resolution=sl.Resolution(width=640, height=480),
        )
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to retrieve depth image: {status}")

        depth_data = np.array(self.depth.get_data(), copy=True)
        should_publish_preview = self.frame_number % self.preview_every_n_frames == 0
        preview_data: np.ndarray | None = None
        if should_publish_preview:
            status = self.zed.retrieve_image(self.image, sl.VIEW.LEFT)
            if status != sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(f"Failed to retrieve RGB image: {status}")
            preview_data = np.ascontiguousarray(self.image.get_data()[:, :, :3])

        tasks = [asyncio.to_thread(self._encode_depth_payload, depth_data)]
        if preview_data is not None:
            tasks.append(asyncio.to_thread(self._encode_preview_frame, preview_data))
        encoded = await asyncio.gather(*tasks)

        depth_payload = encoded[0]
        preview_payload = encoded[1] if len(encoded) > 1 else None

        if state == sl.POSITIONAL_TRACKING_STATE.OK:
            translation = tuple(float(v) for v in self.pose.get_translation().get())
            orientation = tuple(float(v) for v in self.pose.get_orientation().get())
            pose = Pose(
                translation=list(translation),
                orientation=list(orientation),
                frame_number=self.frame_number,
                timestamp=self.timestamp,
            ).model_dump_json()

            bundle = SensorBundle(
                frame_number=self.frame_number,
                timestamp=self.timestamp,
                translation=translation,
                orientation=orientation,
                depth_width=640,
                depth_height=480,
                depth_payload=depth_payload,
                rgb_encoding=RGB_ENCODING_JPEG
                if self.INCLUDE_RGB_IN_BUNDLE and preview_payload is not None
                else 0,
                rgb_width=preview_data.shape[1]
                if self.INCLUDE_RGB_IN_BUNDLE and preview_data is not None
                else 0,
                rgb_height=preview_data.shape[0]
                if self.INCLUDE_RGB_IN_BUNDLE and preview_data is not None
                else 0,
                rgb_payload=preview_payload
                if self.INCLUDE_RGB_IN_BUNDLE and preview_payload is not None
                else b"",
            )
            bundle_payload = serialize_sensor_bundle(bundle)

            await self.nc.publish(
                SENSOR_BUNDLE_SUBJECT,
                bundle_payload,
                headers={
                    "frame_number": str(self.frame_number),
                    "timestamp": str(self.timestamp),
                    "depth_encoding": DEPTH_ENCODING_MM_U16_LZ4,
                },
            )
            await self.nc.publish(self.POSE_SUBJECT, pose.encode())

            self.bundle_messages += 1
            self.bundle_bytes += len(bundle_payload)
            self.pose_messages += 1
            self.last_bundle_frame = self.frame_number
        else:
            self.pose_drop_count += 1

        if preview_payload is not None and preview_data is not None:
            headers = {
                "type": "image/jpeg",
                "width": str(preview_data.shape[1]),
                "height": str(preview_data.shape[0]),
                "frame_number": str(self.frame_number),
                "timestamp": str(self.timestamp),
            }
            await self.nc.publish(self.PREVIEW_SUBJECT, preview_payload, headers=headers)
            await self.nc.publish(
                self.LEGACY_PREVIEW_SUBJECT, preview_payload, headers=headers
            )
            self.preview_messages += 1
            self.preview_bytes += len(preview_payload) * 2
            self.last_preview_frame = self.frame_number

        self.last_capture_duration_ms = (loop.time() - started) * 1000.0

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

from asyncio import Task
import time
from typing import Annotated, Optional
import tempfile
import cv2
from numpy import diff
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
    GAMMA: int = Field(default=5, gt=1, le=9)
    GAIN: int = Field(default=97, ge=0, le=100)
    EXPOSURE: int = Field(default=67, ge=0, le=100)
    WHITEBALANCE_TEMPERATURE: int = Field(default=4700, ge=2800, le=6500)
    WHITEBALANCE_AUTO: int = Field(default=1, ge=0, le=1)


class Node(RabbitNode):
    CAMERA_SETTINGS_KEY = "rabbit.zed.camera_settings"

    def __init__(self):
        super().__init__("rabbit-zed")

        self.frame = sl.Mat()
        self.zed = sl.Camera()
        self.mesh = sl.Mesh()

        self.runtime_params = sl.RuntimeParameters()
        self.camera_parameters = sl.CameraParameters()

        self.init_params = sl.InitParameters(
            camera_resolution=sl.RESOLUTION.HD720,
            camera_fps=30,
            depth_mode=sl.DEPTH_MODE.NEURAL,
            coordinate_units=sl.UNIT.METER,
            coordinate_system=sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP,
            sdk_verbose=1,
        )

        self.positional_tracking_parameters = sl.PositionalTrackingParameters()
        self.positional_tracking_parameters.set_floor_as_origin = True

        self.spatial_mapping_parameters = sl.SpatialMappingParameters(
            resolution=sl.MAPPING_RESOLUTION.LOW,
            mapping_range=sl.MAPPING_RANGE.SHORT,
            max_memory_usage=2048,
            save_texture=False,
            use_chunk_only=True,
            reverse_vertex_order=False,
            map_type=sl.SPATIAL_MAP_TYPE.MESH,
        )

        self.mapping_activated = False
        self.frame_number = -1

    async def init(self):
        status = self.zed.open(self.init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Camera initialization failed: {status}")

        status = self.zed.enable_positional_tracking(
            self.positional_tracking_parameters
        )
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to enable positional tracking: {status}")

        await self.init_camera_settings()
        await self.watch_kv(self.CAMERA_SETTINGS_KEY, self.on_camera_settings_update)
        await self.async_task(self.capture_loop)

    async def close(self):
        self.zed.close()

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

        status = self.zed.retrieve_image(self.frame, sl.VIEW.RIGHT)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to retrieve image: {status}")
        await self.publish_frame()

        if not self.mapping_activated and self.frame_number % 30 == 0:
            self.activate_spatial_mapping()

        if self.mapping_activated:
            await self.retrieve_spatial_mapping()

    async def retrieve_spatial_mapping(self):
        mapping_state = self.zed.get_spatial_mapping_state()
        if mapping_state == sl.SPATIAL_MAPPING_STATE.OK:
            if self.frame_number % 30 == 0:
                self.zed.request_spatial_map_async()

            status = self.zed.get_spatial_map_request_status_async()
            if status == sl.ERROR_CODE.SUCCESS:
                self.zed.retrieve_spatial_map_async(self.mesh)
                # self.mesh.apply_texture()
                self.logger.info(
                    f"Spatial map retrieved successfully: {self.mesh.get_number_of_triangles()} triangles"
                )
                tmp = tempfile.NamedTemporaryFile(suffix=".obj", delete=False)
                tmp.close()
                ok = self.mesh.save(tmp.name, sl.MESH_FILE_FORMAT.OBJ)
                if not ok:
                    raise RuntimeError("Failed to save spatial map to OBJ file")
                with open(tmp.name, "rb") as f:
                    data = f.read()
                await self.object_store.put("rabbit.zed.mesh", data)

    def activate_spatial_mapping(self):
        init_pose = sl.Transform()
        self.zed.reset_positional_tracking(init_pose)
        status = self.zed.enable_spatial_mapping(self.spatial_mapping_parameters)
        if status == sl.ERROR_CODE.SUCCESS:
            self.mesh.clear()
            self.mapping_activated = True
            self.logger.info("Spatial mapping activated")

    async def publish_frame(self):
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

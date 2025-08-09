from asyncio import Task
import time
from typing import Annotated, Optional

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

    frame = sl.Mat()
    zed = sl.Camera()
    mesh = sl.Mesh()

    def __init__(self):
        super().__init__("rabbit-zed")

        self.runtime_params = sl.RuntimeParameters()
        self.camera_parameters = sl.CameraParameters()
        self.tracking_state = sl.POSITIONAL_TRACKING_STATE.OFF
        
        self.init_params = sl.InitParameters(
            camera_resolution=sl.RESOLUTION.HD720,
            camera_fps=30,
            depth_mode=sl.DEPTH_MODE.NEURAL_LIGHT,
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

    async def init(self):
        status = self.zed.open(self.init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Camera initialization failed: {status}")

        status = self.zed.enable_spatial_mapping(self.spatial_mapping_parameters)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to enable spatial mapping: {status}")

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

        status = self.zed.retrieve_image(self.frame, sl.VIEW.RIGHT)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to retrieve image: {status}")
        await self.publish_frame()

        now = time.time()
        # раз в ~0.5с — запрос апдейта карты
        if (now - self._last_map_req) > 0.5:
            self.zed.request_spatial_map_async()
            self._last_map_req = now

        # если готово — забираем куски в self.mesh
        if self.zed.get_spatial_map_request_status_async() == sl.ERROR_CODE.SUCCESS:
            self.zed.retrieve_spatial_map_async(self.mesh)
            # Печатаем размер (вершины/треугольники)
            self._print_mesh_size()

    def _print_mesh_size(self, prefix: str = ""):
        try:
            v = self.mesh.get_number_of_vertices()
            t = self.mesh.get_number_of_triangles()
            self.logger.info(f"{prefix} mesh size: {v} vertices, {t} triangles")
        except AttributeError:
            # Фолбек: вытянуть целиком и попытаться через чанки
            try:
                self.zed.extract_whole_spatial_map(self.mesh)
                # В некоторых версиях можно обратиться к self.mesh.chunks
                total_v = 0
                total_t = 0
                for ch in self.mesh.chunks:
                    total_v += ch.get_number_of_vertices()
                    total_t += ch.get_number_of_triangles()
                self.logger.info(
                    f"{prefix} mesh size (chunks): {total_v} vertices, {total_t} triangles"
                )
            except Exception as e:
                self.logger.warning(f"Cannot read mesh size: {e}")

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

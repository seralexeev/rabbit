import asyncio
import json
import os
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np
from lib.geometry import CAMERA_HEIGHT, CENTERLINE_OFFSET, GRAVITY, quaternion_to_matrix, tilt_deg
from lib.model import CameraIntrinsics
from lib.node import RabbitNode
from lib.safety import bin_scan, heights_above_floor
from lib.spatial_map import (
    AREA_ARCHIVE_DIR,
    AREA_FILE,
    CHUNKS_FILE,
    MESH_FILE,
    MAP_CHUNKS_SUBJECT,
    MAP_DIR,
    MAP_RESET_SUBJECT,
    MAP_SAVE_SUBJECT,
    MAP_SNAPSHOT_SUBJECT,
    decode_chunks,
    encode_chunk,
)
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
    GAMMA: int = Field(default=5, ge=1, le=9)
    AEC_AGC: int = Field(default=1, ge=0, le=1)
    GAIN: int = Field(default=50, ge=0, le=100)
    EXPOSURE: int = Field(default=50, ge=0, le=100)
    WHITEBALANCE_AUTO: int = Field(default=1, ge=0, le=1)
    WHITEBALANCE_TEMPERATURE: int = Field(default=4600, ge=2800, le=6500)


@dataclass(slots=True)
class CapturedFrame:
    frame_number: int
    timestamp: int
    pose: dict | None
    obstacle: dict | None
    preview: np.ndarray | None
    map_update: bytes | None


class Node(RabbitNode):
    CAMERA_SETTINGS_KEY = "rabbit.zed.camera_settings"
    POSE_SUBJECT = "rabbit.zed.pose"
    PREVIEW_SUBJECT = "rabbit.zed.frame.preview"
    IMU_SUBJECT = "rabbit.zed.imu"
    MAGNETOMETER_SUBJECT = "rabbit.zed.magnetometer"
    BAROMETER_SUBJECT = "rabbit.zed.barometer"
    OBSTACLE_SUBJECT = "rabbit.zed.obstacle"
    OBSTACLE_EVERY_N_FRAMES = 3
    OBSTACLE_RESOLUTION = (160, 90)
    OBSTACLE_MIN_HEIGHT = 0.04
    OBSTACLE_MAX_HEIGHT = 0.45
    OBSTACLE_MAX_RANGE = 5.0
    OBSTACLE_MIN_DEPTH = 0.25
    SCAN_MIN_POINTS = 4
    CORRIDOR_HALF_WIDTH = 0.15
    SCAN_HALF_FOV_DEG = 60.0
    SCAN_BINS = 48
    BLIND_ROWS = (0.65, 0.82)
    BLIND_COLUMNS = (0.3, 0.7)
    BLIND_FRACTION = 0.85
    SENSOR_POLL_S = 0.005
    SENSOR_PUBLISH_S = 0.05
    IMU_WINDOW_NS = 10_000_000
    STATUS_EVERY_N_FRAMES = 30
    RELOCALIZATION_TIMEOUT_S = 30.0
    FRESH_MAP_SUSPECT_S = 120.0
    BASE_INDEX_OFFSET = 1 << 20
    BASE_REPLACE_MARGIN = 0.1
    AREA_ARCHIVE_KEEP = 5
    TILT_MISMATCH_DEG = 8.0
    FLOOR_SMOOTHING = 0.02
    FLOOR_MAX_VERTICAL_SPEED = 0.05
    FLOOR_MAX_TILT_DEG = 10.0
    FLOOR_REENCODE_SHIFT = 0.02
    TILT_MISMATCH_S = 3.0
    HEALTH_SUBJECT = "rabbit.health.zed"
    PREVIEW_FPS = 10
    MAP_INTERVAL_S = 3.0
    MAP_STATIC_INTERVAL_S = 15.0
    MAP_WORK_BUDGET = 0.05
    AREA_EXPORT_TIMEOUT_S = 15.0
    TEMPERATURE_LOCATIONS = (
        sl.SENSOR_LOCATION.IMU,
        sl.SENSOR_LOCATION.BAROMETER,
        sl.SENSOR_LOCATION.ONBOARD_LEFT,
        sl.SENSOR_LOCATION.ONBOARD_RIGHT,
    )

    def __init__(self):
        super().__init__("rabbit-zed")

        self.image = sl.Mat()
        self.points = sl.Mat()
        self.zed = sl.Camera()
        self.pose = sl.Pose()
        self.sensor_samples: deque[tuple] = deque(maxlen=4096)
        self._sensors_stop = threading.Event()
        self._sensors_thread = threading.Thread(target=self._poll_sensors, daemon=True)
        self.map = sl.Mesh()
        self._camera_lock = threading.Lock()
        self._encoding: asyncio.Task | None = None

        self.runtime_params = sl.RuntimeParameters()
        self.runtime_params.confidence_threshold = 95
        self.runtime_params.texture_confidence_threshold = 100
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
        self.init_params.enable_image_validity_check = 1

        self.tracking_parameters = sl.PositionalTrackingParameters()
        self.tracking_parameters.mode = sl.POSITIONAL_TRACKING_MODE.GEN_3
        self.tracking_parameters.set_floor_as_origin = True
        self.tracking_parameters.enable_area_memory = True

        self.mapping_parameters = sl.SpatialMappingParameters()
        self.mapping_parameters.map_type = sl.SPATIAL_MAP_TYPE.MESH
        self.mapping_parameters.save_texture = False
        self.mapping_parameters.resolution_meter = 0.05
        self.mapping_parameters.range_meter = 4.0
        self.mapping_parameters.max_memory_usage = 1024
        self.mapping_parameters.use_chunk_only = True
        self.mapping_parameters.stability_counter = 4
        self.map_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self.map_worker: threading.Thread | None = None
        self.pending_map: bytes | None = None
        self.snapshot_payload = b""

        self.session = str(time.time_ns())
        self.set_log_context(map_session=self.session)
        self.mapping_enabled = False
        self.map_requested = False
        self.last_map_request = 0.0
        self.save_requested = False
        self.chunk_timestamps: dict[int, int] = {}
        self.encoded_chunks: dict[int, bytes] = {}
        self.map_interval_s = self.MAP_INTERVAL_S
        self.chunk_points: dict[int, int] = {}
        self.base_keys = np.empty(0, dtype=np.int64)
        self.base_centers = np.empty((0, 3))
        self.relocalization_motion_s = 0.0
        self.relocalization_checked_at = 0.0
        self.restarting = False
        self.started_at = time.monotonic()

        self.frame_number = -1
        self.timestamp = 0
        self.preview_messages = 0
        self.preview_bytes = 0
        self.preview_skipped = 0
        self.pose_messages = 0
        self.pose_drop_count = 0
        self.corrupted_frames = 0
        self.map_messages = 0
        self.map_bytes = 0
        self.map_chunk_count = 0
        self.map_points = 0
        self.map_triangles = 0
        self.mapping_state = "DISABLED"
        self.last_capture_duration_ms = 0.0
        self.last_pose_state = "UNKNOWN"
        self.last_preview_frame = -1
        self.status: dict = {}
        self.relocalizing_since: float | None = None
        self.clock_offset_ns = 0
        self.floor_y: float | None = None
        self.encoded_floor_y = 0.0
        self.last_camera_height: tuple[float, float] | None = None
        self.imu_tilt_deg: float | None = None
        self.tilt_mismatch_since: float | None = None
        self.sensor_state: dict = {}

    async def init(self):
        status = self.zed.open(self.init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Camera initialization failed: {status}")

        MAP_DIR.mkdir(parents=True, exist_ok=True)
        if AREA_FILE.exists():
            self.tracking_parameters.area_file_path = str(AREA_FILE)
            self.relocalizing_since = self.relocalization_checked_at = time.monotonic()
            self.logger.info(f"Relocalizing against {AREA_FILE}")

        status = self.zed.enable_positional_tracking(self.tracking_parameters)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to enable positional tracking: {status}")

        await self.publish_camera_intrinsics()
        await self.init_camera_settings()
        await self.watch_kv(self.CAMERA_SETTINGS_KEY, self.on_camera_settings_update)
        await self.subscribe(MAP_SAVE_SUBJECT, self.on_map_save)
        await self.subscribe(MAP_RESET_SUBJECT, self.on_map_reset)
        await self.subscribe(MAP_SNAPSHOT_SUBJECT, self.on_map_snapshot)
        self.preview_every_n_frames = max(
            1, round(self.camera_fps / self.PREVIEW_FPS)
        )

        self._sensors_thread.start()
        await self.async_task(self.capture)
        self.set_interval(self.publish_sensors, self.SENSOR_PUBLISH_S, max_parallel=1)
        self.set_interval(self.publish_health, 1, max_parallel=1)

    async def close(self):
        await asyncio.to_thread(self._shutdown_camera)

    def _shutdown_camera(self):
        self._sensors_stop.set()
        if self._sensors_thread.is_alive():
            self._sensors_thread.join()
        with self._camera_lock:
            if self.map_worker is not None:
                self.map_worker.join()
            self._save_map()
            if self.mapping_enabled:
                self.zed.disable_spatial_mapping()
            deadline = time.monotonic() + self.AREA_EXPORT_TIMEOUT_S
            while (
                self.zed.get_area_export_state() == sl.AREA_EXPORTING_STATE.RUNNING
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
            self.logger.info(f"Area export: {self.zed.get_area_export_state()}")
            self.zed.close()

    def _save_map(self):
        if self.restarting:
            self.logger.warning("Not saving the map of a discarded session")
            return
        if self.relocalizing_since is not None:
            self.logger.warning("Not saving the map before relocalizing against the saved one")
            return
        status = self.zed.save_area_map(str(AREA_FILE))
        if status != sl.ERROR_CODE.SUCCESS:
            self.logger.error(f"Failed to save area map: {status}")
        with self.map_lock:
            if self.map.get_number_of_triangles() > 0 and not self.map.save(
                str(MESH_FILE), sl.MESH_FILE_FORMAT.PLY
            ):
                self.logger.error(f"Failed to save mesh to {MESH_FILE}")
            if self.snapshot_payload:
                staging = CHUNKS_FILE.with_suffix(".tmp")
                staging.write_bytes(self.snapshot_payload)
                staging.replace(CHUNKS_FILE)

    async def on_map_save(self, msg: Msg):
        self.save_requested = True

    async def on_map_reset(self, msg: Msg):
        source = json.loads(msg.data or b"{}").get("source", "unknown")
        await asyncio.to_thread(self._reset_map, source)

    def _reset_map(self, source: str):
        with self._camera_lock:
            self._restart_process(f"map reset requested by {source}", archive=True)

    async def on_map_snapshot(self, msg: Msg):
        await self.publish(
            msg.reply,
            self.snapshot_payload,
            headers={"session": self.session, "format": "mesh"},
        )

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
            settings = CameraSettings()
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

    async def publish_health(self):
        await self.publish_json(
            self.HEALTH_SUBJECT,
            {
                "frame_number": self.frame_number,
                "timestamp": self.timestamp,
                "camera_fps": self.camera_fps,
                "current_fps": round(self.zed.get_current_fps(), 1),
                "preview_every_n_frames": self.preview_every_n_frames,
                "preview_messages": self.preview_messages,
                "preview_bytes": self.preview_bytes,
                "preview_skipped": self.preview_skipped,
                "pose_messages": self.pose_messages,
                "pose_drop_count": self.pose_drop_count,
                "dropped_publishes": self.dropped_publishes,
                "corrupted_frames": self.corrupted_frames,
                "last_capture_duration_ms": self.last_capture_duration_ms,
                "last_pose_state": self.last_pose_state,
                "last_preview_frame": self.last_preview_frame,
                **self.status,
                "mapping_state": self.mapping_state,
                "map_interval_s": round(self.map_interval_s, 1),
                "map_session": self.session,
                "map_chunks": self.map_chunk_count,
                "map_points": self.map_points,
                "map_triangles": self.map_triangles,
                "floor_y": None if self.floor_y is None else round(self.floor_y, 3),
                "map_messages": self.map_messages,
                "map_bytes": self.map_bytes,
                **self.sensor_state,
            },
        )

    def _grab(self) -> CapturedFrame | None:
        if self.restarting:
            return None
        with self._camera_lock:
            status = self.zed.grab(self.runtime_params)
            if status == sl.ERROR_CODE.CORRUPTED_FRAME:
                self.corrupted_frames += 1
                return None
            if status != sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(f"Failed to grab image from ZED camera: {status}")

            started = time.monotonic()
            self.frame_number += 1
            self.timestamp = self.zed.get_timestamp(
                sl.TIME_REFERENCE.IMAGE
            ).get_nanoseconds()

            tracking_ok = (
                self.zed.get_position(self.pose, sl.REFERENCE_FRAME.WORLD)
                == sl.POSITIONAL_TRACKING_STATE.OK
                and self.pose.pose_confidence > 0
            )

            if tracking_ok:
                self._update_floor()
            self._update_map(tracking_ok)
            with self._pending_lock:
                map_update, self.pending_map = self.pending_map, None

            if self.save_requested:
                self.save_requested = False
                self._save_map()

            preview = None
            if self.frame_number % self.preview_every_n_frames == 0:
                status = self.zed.retrieve_image(self.image, sl.VIEW.LEFT)
                if status != sl.ERROR_CODE.SUCCESS:
                    raise RuntimeError(f"Failed to retrieve RGB image: {status}")
                preview = np.ascontiguousarray(self.image.get_data()[:, :, :3])

            if self.frame_number % self.STATUS_EVERY_N_FRAMES == 0:
                self.clock_offset_ns = time.time_ns() - self.zed.get_timestamp(
                    sl.TIME_REFERENCE.CURRENT
                ).get_nanoseconds()
                self.status = self._read_status()
                self._check_relocalization()
                self._check_tilt(tracking_ok)

            self.last_capture_duration_ms = (time.monotonic() - started) * 1000.0
            return CapturedFrame(
                frame_number=self.frame_number,
                timestamp=self.timestamp,
                pose=self._read_pose() if tracking_ok else None,
                obstacle=self._find_obstacles()
                if tracking_ok and self.frame_number % self.OBSTACLE_EVERY_N_FRAMES == 0
                else None,
                preview=preview,
                map_update=map_update,
            )

    def _update_floor(self):
        camera_y = float(self.pose.get_translation().get()[1])
        now = time.monotonic()
        previous, self.last_camera_height = self.last_camera_height, (now, camera_y)
        if previous is None or now <= previous[0]:
            return
        vertical_speed = abs(camera_y - previous[1]) / (now - previous[0])
        if vertical_speed > self.FLOOR_MAX_VERTICAL_SPEED or tilt_deg(self.pose.get_orientation().get()) > self.FLOOR_MAX_TILT_DEG:
            return
        estimate = camera_y - CAMERA_HEIGHT
        self.floor_y = estimate if self.floor_y is None else self.floor_y + self.FLOOR_SMOOTHING * (estimate - self.floor_y)

    def _floor(self) -> float:
        return self.floor_y or 0.0

    def _read_pose(self) -> dict:
        twist = np.asarray(self.pose.twist, dtype=float)
        covariance = np.asarray(self.pose.pose_covariance, dtype=float).reshape(6, 6)
        translation = np.asarray(self.pose.get_translation().get(), dtype=float) - np.array([0.0, self._floor(), 0.0])
        return {
            "translation": [round(float(v), 4) for v in translation],
            "orientation": [round(float(v), 6) for v in self.pose.get_orientation().get()],
            "euler_deg": [round(float(v), 3) for v in self.pose.get_euler_angles(radian=False)],
            "velocity": [round(float(v), 4) for v in twist[:3]],
            "angular_velocity": [round(float(v), 4) for v in twist[3:]],
            "position_std": [round(float(v), 5) for v in np.sqrt(np.diag(covariance)[:3])],
            "confidence": self.pose.pose_confidence,
        }

    def _find_obstacles(self) -> dict | None:
        width, height = self.OBSTACLE_RESOLUTION
        status = self.zed.retrieve_measure(
            self.points, sl.MEASURE.XYZ, sl.MEM.CPU, sl.Resolution(width, height)
        )
        if status != sl.ERROR_CODE.SUCCESS:
            return None

        image = self.points.get_data()[:, :, :3]
        rows, columns = image.shape[:2]
        window = image[
            int(rows * self.BLIND_ROWS[0]) : int(rows * self.BLIND_ROWS[1]),
            int(columns * self.BLIND_COLUMNS[0]) : int(columns * self.BLIND_COLUMNS[1]),
        ]
        blind_fraction = float(1.0 - np.isfinite(window).all(axis=2).mean())
        camera = image.reshape(-1, 3)
        camera = camera[np.isfinite(camera).all(axis=1)]
        camera = camera[np.linalg.norm(camera, axis=1) > self.OBSTACLE_MIN_DEPTH]
        rotation = quaternion_to_matrix(self.pose.get_orientation().get())
        origin = np.asarray(self.pose.get_translation().get(), dtype=float)
        world = camera @ rotation.T + origin
        world[:, 1] -= self._floor()
        origin = origin - np.array([0.0, self._floor(), 0.0])

        offset = world - origin
        horizontal = np.hypot(offset[:, 0], offset[:, 2])
        height = heights_above_floor(offset[:, [0, 2]], world[:, 1])
        mask = (
            (height > self.OBSTACLE_MIN_HEIGHT)
            & (height < self.OBSTACLE_MAX_HEIGHT)
            & (horizontal < self.OBSTACLE_MAX_RANGE)
        )
        if not mask.any():
            return {"nearest": None, "ahead": None, "scan": self._empty_scan(blind_fraction)}

        world, offset, horizontal = world[mask], offset[mask], horizontal[mask]
        forward = rotation @ np.array([0.0, 0.0, -1.0])
        forward = np.array([forward[0], 0.0, forward[2]])
        forward /= np.linalg.norm(forward)
        right = np.array([-forward[2], 0.0, forward[0]])
        along = offset @ forward
        across = offset @ right

        def describe(index: int) -> dict:
            return {
                "distance": round(float(horizontal[index]), 3),
                "point": [round(float(v), 3) for v in world[index]],
                "bearing_deg": round(float(np.degrees(np.arctan2(across[index], along[index]))), 1),
            }

        def kth_nearest(candidates: np.ndarray) -> dict | None:
            if len(candidates) < self.SCAN_MIN_POINTS:
                return None
            order = np.argpartition(horizontal[candidates], self.SCAN_MIN_POINTS - 1)
            return describe(int(candidates[order[self.SCAN_MIN_POINTS - 1]]))

        corridor = np.flatnonzero((along > 0) & (np.abs(across) < self.CORRIDOR_HALF_WIDTH))
        return {
            "nearest": kth_nearest(np.arange(len(horizontal))),
            "ahead": kth_nearest(corridor),
            "scan": self._scan(along, across - CENTERLINE_OFFSET, blind_fraction),
        }

    def _empty_scan(self, blind_fraction: float) -> dict:
        step = 2 * self.SCAN_HALF_FOV_DEG / self.SCAN_BINS
        return {
            "angle_min_deg": -self.SCAN_HALF_FOV_DEG,
            "angle_step_deg": step,
            "ranges": [None] * self.SCAN_BINS,
            "blind_fraction": round(blind_fraction, 3),
            "blind": blind_fraction > self.BLIND_FRACTION,
        }

    def _scan(self, along: np.ndarray, across: np.ndarray, blind_fraction: float) -> dict:
        scan = self._empty_scan(blind_fraction)
        nearest = bin_scan(along, across, self.SCAN_HALF_FOV_DEG, self.SCAN_BINS, self.SCAN_MIN_POINTS)
        scan["ranges"] = [round(float(r), 3) if np.isfinite(r) else None for r in nearest]
        return scan

    def _check_relocalization(self):
        if self.relocalizing_since is None:
            return
        memory = self.status["spatial_memory_status"]
        if memory not in ("INITIALIZING", "SEARCHING"):
            self.relocalizing_since = None
            self.logger.info(f"Relocalized ({memory})")
            self._load_base_map()
            return
        now = time.monotonic()
        if self.sensor_state.get("camera_moving_state") != "STATIC":
            self.relocalization_motion_s += now - self.relocalization_checked_at
        self.relocalization_checked_at = now
        if self.relocalization_motion_s < self.RELOCALIZATION_TIMEOUT_S:
            return

        self._restart_process("relocalization timed out", archive=True)

    def _check_tilt(self, tracking_ok: bool):
        if not tracking_ok or self.imu_tilt_deg is None:
            return
        pose_tilt = tilt_deg(self.pose.get_orientation().get())
        self.status["pose_tilt_deg"] = round(pose_tilt, 2)
        self.status["imu_tilt_deg"] = round(self.imu_tilt_deg, 2)
        if abs(pose_tilt - self.imu_tilt_deg) < self.TILT_MISMATCH_DEG:
            self.tilt_mismatch_since = None
            return
        now = time.monotonic()
        if self.tilt_mismatch_since is None:
            self.tilt_mismatch_since = now
        elif now - self.tilt_mismatch_since > self.TILT_MISMATCH_S:
            self.tilt_mismatch_since = None
            self._restart_process(
                f"pose tilt {pose_tilt:.1f} deg disagrees with IMU {self.imu_tilt_deg:.1f} deg",
                archive=time.monotonic() - self.started_at < self.FRESH_MAP_SUSPECT_S,
            )

    def _restart_process(self, reason: str, archive: bool):
        if self.restarting:
            return
        self.restarting = True
        self.logger.warning(f"Restarting the camera process: {reason}", extra={"archive_map": archive})
        if archive:
            self._archive_area()
        os.kill(os.getpid(), signal.SIGTERM)

    def _archive_area(self):
        if not AREA_FILE.exists():
            return
        AREA_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archived = AREA_ARCHIVE_DIR / f"room.{time.strftime('%Y%m%d-%H%M%S')}.area"
        AREA_FILE.replace(archived)
        if CHUNKS_FILE.exists():
            CHUNKS_FILE.replace(archived.with_suffix(".chunks"))
        self.logger.warning(f"Archived the previous area map to {archived}")
        for pattern in ("room.*.area", "room.*.chunks"):
            for stale in sorted(AREA_ARCHIVE_DIR.glob(pattern))[: -self.AREA_ARCHIVE_KEEP]:
                stale.unlink()

    def _load_base_map(self):
        if not CHUNKS_FILE.exists():
            return
        saved = [chunk for chunk in decode_chunks(CHUNKS_FILE.read_bytes()).values() if len(chunk[0])]
        keys = self.BASE_INDEX_OFFSET + np.arange(len(saved))
        encoded = [encode_chunk(int(key), vertices, triangles) for key, (vertices, triangles) in zip(keys, saved)]
        with self.map_lock:
            for key, chunk, (vertices, _) in zip(keys, encoded, saved):
                self.encoded_chunks[int(key)] = chunk
                self.chunk_points[int(key)] = len(vertices)
            self.base_keys = keys
            self.base_centers = np.array([(vertices.min(axis=0) + vertices.max(axis=0)) / 2 for vertices, _ in saved]).reshape(-1, 3)
            self.snapshot_payload = b"".join(self.encoded_chunks.values())
        self._queue_map_update(b"".join(encoded))
        self.logger.info(f"Loaded {len(saved)} saved map chunks")

    def _queue_map_update(self, payload: bytes):
        if not payload:
            return
        with self._pending_lock:
            self.pending_map = payload if self.pending_map is None else self.pending_map + payload

    def _retire_base_chunks(self, vertices: np.ndarray) -> list[bytes]:
        if not len(self.base_keys) or not len(vertices):
            return []
        low = vertices.min(axis=0) - self.BASE_REPLACE_MARGIN
        high = vertices.max(axis=0) + self.BASE_REPLACE_MARGIN
        covered = np.all((self.base_centers >= low) & (self.base_centers <= high), axis=1)
        if not covered.any():
            return []
        retired = self.base_keys[covered]
        self.base_keys, self.base_centers = self.base_keys[~covered], self.base_centers[~covered]
        empty = np.empty((0, 3))
        tombstones = []
        for key in retired.tolist():
            self.encoded_chunks.pop(key, None)
            self.chunk_points.pop(key, None)
            tombstones.append(encode_chunk(key, empty, empty))
        return tombstones

    def _read_status(self) -> dict:
        tracking = self.zed.get_positional_tracking_status()
        health = self.zed.get_health_status()
        settings = {
            name.lower(): self.zed.get_camera_settings(sl.VIDEO_SETTINGS[name])[1]
            for name in ("EXPOSURE", "GAIN", "WHITEBALANCE_TEMPERATURE")
        }
        return {
            "odometry_status": tracking.odometry_status.name,
            "spatial_memory_status": tracking.spatial_memory_status.name,
            "tracking_fusion_status": tracking.tracking_fusion_status.name,
            "low_image_quality": health.low_image_quality,
            "low_lighting": health.low_lighting,
            "low_depth_reliability": health.low_depth_reliability,
            "low_motion_sensors_reliability": health.low_motion_sensors_reliability,
            "frames_dropped": self.zed.get_frame_dropped_count(),
            **settings,
        }

    def _poll_sensors(self):
        data = sl.SensorsData()
        last_imu = last_magnetometer = last_barometer = 0
        last_state = 0.0
        while not self._sensors_stop.wait(self.SENSOR_POLL_S):
            if self.zed.get_sensors_data(data, sl.TIME_REFERENCE.CURRENT) != sl.ERROR_CODE.SUCCESS:
                continue

            now = time.monotonic()
            if now - last_state >= 1.0:
                last_state = now
                temperatures = data.get_temperature_data()
                self.sensor_state = {
                    "camera_moving_state": data.camera_moving_state.name,
                    "temperature": {
                        location.name.lower(): round(temperatures.get(location), 1)
                        for location in self.TEMPERATURE_LOCATIONS
                    },
                }

            imu = data.get_imu_data()
            ts = imu.timestamp.get_nanoseconds()
            if ts != last_imu:
                last_imu = ts
                orientation = imu.get_pose().get_orientation().get()
                self.imu_tilt_deg = tilt_deg(orientation)
                self.sensor_samples.append(
                    (
                        "imu",
                        ts,
                        imu.get_linear_acceleration(),
                        imu.get_angular_velocity(),
                        orientation,
                    )
                )

            magnetometer = data.get_magnetometer_data()
            ts = magnetometer.timestamp.get_nanoseconds()
            if magnetometer.is_available and ts != last_magnetometer:
                last_magnetometer = ts
                self.sensor_samples.append(
                    (
                        "magnetometer",
                        ts,
                        magnetometer.get_magnetic_field_calibrated(),
                        magnetometer.magnetic_heading,
                        magnetometer.magnetic_heading_state.name,
                    )
                )

            barometer = data.get_barometer_data()
            ts = barometer.timestamp.get_nanoseconds()
            if barometer.is_available and ts != last_barometer:
                last_barometer = ts
                self.sensor_samples.append(("barometer", ts, barometer.pressure))

    async def publish_sensors(self):
        imu_windows: dict[int, list[tuple]] = {}
        while self.sensor_samples:
            sample = self.sensor_samples.popleft()
            kind, ts = sample[0], sample[1]
            if kind == "imu":
                imu_windows.setdefault(ts // self.IMU_WINDOW_NS, []).append(sample)
            elif kind == "magnetometer":
                await self.publish_json(
                    self.MAGNETOMETER_SUBJECT,
                    {
                        "ts": ts + self.clock_offset_ns,
                        "field_ut": [round(float(v), 3) for v in sample[2]],
                        "heading_deg": round(float(sample[3]), 2),
                        "heading_state": sample[4],
                    },
                )
            else:
                await self.publish_json(
                    self.BAROMETER_SUBJECT,
                    {"ts": ts + self.clock_offset_ns, "pressure_hpa": round(float(sample[2]) / 100.0, 3)},
                )

        for window in imu_windows.values():
            acceleration = np.mean([s[2] for s in window], axis=0)
            angular_velocity = np.mean([s[3] for s in window], axis=0)
            await self.publish_json(
                self.IMU_SUBJECT,
                {
                    "ts": window[-1][1] + self.clock_offset_ns,
                    "acceleration": [round(float(v), 4) for v in acceleration],
                    "angular_velocity": [round(float(v), 4) for v in angular_velocity],
                    "orientation": [round(float(v), 6) for v in window[-1][4]],
                    "g": round(float(np.linalg.norm(acceleration)) / GRAVITY, 4),
                    "samples": len(window),
                },
            )

    def _update_map(self, tracking_ok: bool) -> None:
        if not self.mapping_enabled:
            if not tracking_ok or self.relocalizing_since is not None:
                return None
            status = self.zed.enable_spatial_mapping(self.mapping_parameters)
            if status != sl.ERROR_CODE.SUCCESS:
                self.mapping_state = f"ENABLE_FAILED_{status.name}"
                return None
            self.mapping_enabled = True
            self.logger.info("Spatial mapping enabled")

        self.mapping_state = self.zed.get_spatial_mapping_state().name
        if self.map_worker is not None and self.map_worker.is_alive():
            return None
        now = time.monotonic()
        if not self.map_requested:
            static = self.sensor_state.get("camera_moving_state") == "STATIC"
            interval = max(self.map_interval_s, self.MAP_STATIC_INTERVAL_S if static else 0.0)
            if now - self.last_map_request >= interval:
                self.zed.request_spatial_map_async()
                self.map_requested = True
                self.last_map_request = now
            return None

        if self.zed.get_spatial_map_request_status_async() != sl.ERROR_CODE.SUCCESS:
            return None

        self.map_requested = False
        with self.map_lock:
            self.zed.retrieve_spatial_map_async(self.map)
        self.map_worker = threading.Thread(target=self._process_map, daemon=True)
        self.map_worker.start()
        return None

    def _process_map(self):
        with self.map_lock:
            started = time.monotonic()
            chunks = self.map.chunks
            self.map_chunk_count = len(chunks)
            self.map_triangles = self.map.get_number_of_triangles()
            floor = self._floor()
            if abs(floor - self.encoded_floor_y) > self.FLOOR_REENCODE_SHIFT:
                self.chunk_timestamps.clear()
                self.encoded_floor_y = floor
            updated = []
            for index, chunk in enumerate(chunks):
                timestamp = chunk.timestamp
                if self.chunk_timestamps.get(index) == timestamp:
                    continue
                self.chunk_timestamps[index] = timestamp
                vertices = np.array(chunk.vertices, dtype=np.float32)
                if len(vertices):
                    vertices[:, 1] -= self.encoded_floor_y
                encoded = encode_chunk(index, vertices, chunk.triangles)
                self.chunk_points[index] = len(vertices)
                self.encoded_chunks[index] = encoded
                updated.append(encoded)
                updated.extend(self._retire_base_chunks(vertices))
            self.map_points = sum(self.chunk_points.values())
            self.snapshot_payload = b"".join(self.encoded_chunks.values())
            self.map_interval_s = max(self.MAP_INTERVAL_S, (time.monotonic() - started) / self.MAP_WORK_BUDGET)
        self._queue_map_update(b"".join(updated))

    async def capture(self):
        frame = await asyncio.to_thread(self._grab)
        if frame is None:
            return

        if frame.pose is None:
            self.pose_drop_count += 1
            self.last_pose_state = "LOST"
        else:
            self.last_pose_state = "OK"
            await self.publish_json(
                self.POSE_SUBJECT,
                {
                    "ts": frame.timestamp + self.clock_offset_ns,
                    "frame_number": frame.frame_number,
                    "timestamp": frame.timestamp,
                    **frame.pose,
                },
            )
            self.pose_messages += 1

        if frame.obstacle is not None:
            await self.publish_json(
                self.OBSTACLE_SUBJECT, {"ts": frame.timestamp + self.clock_offset_ns, **frame.obstacle}
            )

        if frame.map_update is not None:
            await self.publish(
                MAP_CHUNKS_SUBJECT, frame.map_update, headers={"session": self.session, "format": "mesh"}
            )
            self.map_messages += 1
            self.map_bytes += len(frame.map_update)

        if frame.preview is None:
            return
        if self._encoding is not None and not self._encoding.done():
            self.preview_skipped += 1
            return
        self._encoding = asyncio.create_task(self._publish_preview(frame))

    async def _publish_preview(self, frame: CapturedFrame):
        assert frame.preview is not None
        payload = await asyncio.to_thread(self._encode_preview_frame, frame.preview)
        await self.publish(
            self.PREVIEW_SUBJECT,
            payload,
            headers={
                "type": "image/jpeg",
                "width": str(frame.preview.shape[1]),
                "height": str(frame.preview.shape[0]),
                "frame_number": str(frame.frame_number),
                "timestamp": str(frame.timestamp),
            },
        )
        self.preview_messages += 1
        self.preview_bytes += len(payload)
        self.last_preview_frame = frame.frame_number

    def _encode_preview_frame(self, frame_rgb: np.ndarray) -> bytes:
        success, buffer = cv2.imencode(
            ".jpg",
            frame_rgb,
            [cv2.IMWRITE_JPEG_QUALITY, 50],
        )
        if not success:
            raise RuntimeError("Failed to encode RGB image")
        return buffer.tobytes()

    def set_camera_settings(self, settings: CameraSettings):
        values = settings.model_dump()
        auto_white_balance = values.pop("WHITEBALANCE_AUTO")
        white_balance = values.pop("WHITEBALANCE_TEMPERATURE")
        auto_exposure = values.pop("AEC_AGC")
        exposure = values.pop("EXPOSURE")
        gain = values.pop("GAIN")

        if auto_white_balance:
            values["WHITEBALANCE_AUTO"] = 1
        else:
            values["WHITEBALANCE_TEMPERATURE"] = white_balance
        if auto_exposure:
            values["AEC_AGC"] = 1
        else:
            values["EXPOSURE"] = exposure
            values["GAIN"] = gain

        for name, value in values.items():
            error = self.zed.set_camera_settings(sl.VIDEO_SETTINGS[name], value)
            if error != sl.ERROR_CODE.SUCCESS:
                self.logger.error(f"Failed to set camera setting {name}: {error}")


if __name__ == "__main__":
    Node().run_node()

import asyncio
import json
import os
import shutil
import signal
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from lib.detector import (
    DEFAULT_CONFIDENCE,
    DETECTOR_LABELS,
    DETECTOR_MODEL,
    MOVING_LABELS,
    OBJECTS_SUBJECT,
    DetectedObject,
    DetectedObjects,
    TrackConfirmer,
    confidence_threshold,
    load_labels,
    normalized_box,
    object_corners,
    object_depth,
    to_world,
)
from lib.drive import CAMERA_WAKE_SUBJECT, DRIVE_SUBJECT, HEARTBEAT_SUBJECT, JOY_SUBJECT, is_active, parse_joy
from lib.floor import FloorEstimator
from lib.geometry import CENTERLINE_OFFSET, GRAVITY, matrix_to_quaternion, plausible_position, quaternion_to_matrix, rotation_deg, tilt_deg
from lib.model import CameraIntrinsics
from lib.pose_gate import JumpGate, odometry_step_ok
from lib.relocalization import LOCALIZED_STATES, Relocalization
from lib.loc import KEYFRAME_SUBJECT, LOCALIZED, MAP_ODOM_SUBJECT, KeyframePolicy, encode_keyframe, planar
from lib.map_frame import MapFrame, Plan
from lib.node import RabbitNode
from lib.safety import bin_scan, heights_above_floor
from lib.spatial_map import (
    AREA_ARCHIVE_DIR,
    AREA_FILE,
    EXTEND_FILE,
    MESH_FILE,
    MAP_CHUNKS_SUBJECT,
    MAP_EXTEND_SUBJECT,
    MAP_GRID_SNAPSHOT_SUBJECT,
    MAP_GRID_SUBJECT,
    MAP_ID_FILE,
    MAP_DIR,
    MAP_RESET_SUBJECT,
    MAP_SAVE_SUBJECT,
    MAP_SNAPSHOT_SUBJECT,
    NVBLOX_FILE,
    encode_chunk,
    encode_grid,
)
from nats.aio.msg import Msg
from nats.js.errors import KeyNotFoundError
from nats.js.kv import KeyValue
from pydantic import BaseModel, Field
from pyzed import sl
from rabbit_nvblox import Mapper

SHADOW_LOG = MAP_DIR.parent / "loc" / "shadow.jsonl"
SHADOW_LOG_MAX_BYTES = 32 * 2**20
LOC_NVBLOX_FILE = MAP_DIR / "loc.nvblx"
LOC_NVBLOX_ID_FILE = MAP_DIR / "loc.nvblx.id"


def euler_deg(rotation: np.ndarray) -> np.ndarray:
    matrix = sl.Matrix3f()
    matrix.r = np.asarray(rotation, dtype=np.float32)
    converted = sl.Rotation()
    converted.init_matrix(matrix)
    return converted.get_euler_angles(radian=False)


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
class StoredFrame:
    depth: np.ndarray
    world_from_camera: np.ndarray
    keyframe_id: int
    world_from_keyframe: np.ndarray


@dataclass(slots=True)
class CapturedFrame:
    frame_number: int
    timestamp: int
    preview: np.ndarray | None
    map_update: bytes | None
    objects: list[DetectedObject] | None


class Node(RabbitNode):
    CAMERA_SETTINGS_KEY = "rabbit.zed.camera_settings"
    POSE_SUBJECT = "rabbit.zed.pose"
    PREVIEW_SUBJECT = "rabbit.zed.frame.preview"
    IMU_SUBJECT = "rabbit.zed.imu"
    MAGNETOMETER_SUBJECT = "rabbit.zed.magnetometer"
    BAROMETER_SUBJECT = "rabbit.zed.barometer"
    OBSTACLE_SUBJECT = "rabbit.zed.obstacle"
    RECORD_SUBJECT = "rabbit.zed.record"
    NAV_STATE_SUBJECT = "rabbit.nav.state"
    RECORDINGS_DIR = MAP_DIR.parent / "svo"
    MIN_FREE_DISK_BYTES = 10 * 1024**3
    OBSTACLE_EVERY_N_FRAMES = 2
    DEPTH_EVERY_N_FRAMES = 2
    MAX_WAKE_S = 60.0
    SLOW_STEP_S = 0.3
    MAX_GRAB_FAILURES = 10
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
    SENSOR_PUBLISH_S = 0.01
    IMU_WINDOW_NS = 10_000_000
    STATUS_EVERY_N_FRAMES = 15
    RELOCALIZATION_DISTANCE_M = 3.0
    KEYFRAMES_EVERY_N_FRAMES = 30
    AUTOSAVE_S = 300.0
    MAPPING_IDLE_S = 180.0
    SWITCH_MIN_OPEN_M = 1.2
    SWITCH_LOCALIZED_S = 60.0
    RELOCALIZED_STABLE_S = 10.0
    RELOCALIZE_ACTIVE_S = 60.0
    RELOCALIZATION_TIMEOUT_S = 45.0
    MAX_RELOCALIZATION_STEP_M = 1.0
    FIRST_SAVE_S = 60.0
    STORED_FRAME_STEP_M = 0.2
    STORED_FRAME_STEP_DEG = 10.0
    MAX_STORED_FRAMES = 400
    CORRECTION_M = 0.05
    CORRECTION_DEG = 2.0
    FRESH_MAP_SUSPECT_S = 120.0
    AREA_ARCHIVE_KEEP = 5
    TILT_MISMATCH_DEG = 8.0
    FLOOR_MAX_VERTICAL_SPEED = 0.05
    FLOOR_MAX_TILT_DEG = 10.0
    FLOOR_REENCODE_SHIFT = 0.02
    BELOW_FLOOR_CLEAR_M = 0.15
    TILT_MISMATCH_S = 3.0
    HEALTH_SUBJECT = "rabbit.health.zed"
    PREVIEW_FPS = 10
    DETECTOR_EVERY_N_FRAMES = 4
    DETECTOR_EVERY_N_FRAMES_MOVING = 2
    DETECTOR_MIN_HITS = 3
    DETECTOR_FORGET_AFTER = 8
    DETECTOR_MAX_RANGE = 8.0
    DETECTOR_INPUT = (640, 384)
    COMPUTE_FPS = 30
    IDLE_FPS = 5
    UNWATCHED_FPS = 1
    WATCHED_FOR_S = 5.0
    IDLE_AFTER_S = 3.0
    MOVING_SPEED = 0.03
    MOVING_TURN_RATE = 0.1
    PREVIEW_RESOLUTION = (640, 360)
    DEPTH_RESOLUTION = (640, 360)
    VOXEL_SIZE = 0.05
    MAX_INTEGRATION_DISTANCE = 5.0
    MESH_MIN_WEIGHT = 0.5
    DEPTH_DILATIONS = 0
    FLOOR_SNAP_M = 0.03
    MIN_DEPTH = 0.3
    MAX_DEPTH = 6.0
    MESH_INTERVAL_S = 2.0
    MESH_CHANGE_M = 0.01
    GRID_INTERVAL_S = 2.0
    GRID_HALF_EXTENT_M = 25.0
    KEEP_RADIUS_M = 50.0
    IMPLAUSIBLE_RESTART_S = 15.0
    MAX_INTEGRATION_SPEED = 1.5
    STATIC_INTEGRATE_S = 2.0
    POSE_JUMP_M = 0.5
    POSE_JUMP_SETTLE_S = 4.0
    ODOM_STEP_SLACK_M = 0.05
    ODOM_STEP_SLACK_DEG = 2.0
    MAX_TURN_RATE_DEG = 120.0
    INTEGRATE_EVERY_N_FRAMES = 2
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
        self.step_pose = sl.Pose()
        self.odom: np.ndarray | None = None
        self.odom_rejected = 0
        self.recording_since: float | None = None
        self.odom_timestamp = 0
        self.sensor_samples: deque[tuple] = deque(maxlen=4096)
        self._sensors_stop = threading.Event()
        self._sensors_thread = threading.Thread(target=self._poll_sensors, daemon=True)
        self.depth = sl.Mat()
        self._camera_lock = threading.Lock()
        self._encoding: asyncio.Task | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.obstacle_worker = ThreadPoolExecutor(max_workers=1)
        self.obstacle_job: Future | None = None

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
        self.init_params.enable_image_validity_check = 0
        self.init_params.depth_stabilization = 0

        self.tracking_parameters = sl.PositionalTrackingParameters()
        self.tracking_parameters.mode = sl.POSITIONAL_TRACKING_MODE.GEN_3
        self.tracking_parameters.compute_preference = sl.COMPUTE_PREFERENCE.PREFER_GPU
        self.tracking_parameters.set_floor_as_origin = True
        self.loc_mode = os.environ.get("LOC_MODE", "shadow")
        self.applying = self.loc_mode == "apply"
        self.tracking_parameters.enable_area_memory = not self.applying
        self.mapping_mode = not self.applying and (not AREA_FILE.exists() or EXTEND_FILE.exists())
        self.tracking_parameters.enable_localization_only = not self.mapping_mode and not self.applying
        self.nvblox_file = LOC_NVBLOX_FILE if self.applying else NVBLOX_FILE

        self.mapper = Mapper(
            self.VOXEL_SIZE,
            self.MAX_INTEGRATION_DISTANCE,
            self.MIN_DEPTH,
            self.MAX_DEPTH,
            mesh_min_weight=self.MESH_MIN_WEIGHT,
            depth_dilations=self.DEPTH_DILATIONS,
            floor_snap=self.FLOOR_SNAP_M,
        )
        self.depth_intrinsics: tuple[float, float, float, float] | None = None
        self.map_lock = threading.Lock()
        self.mapper_lock = threading.Lock()
        self.map_job: tuple[np.ndarray, np.ndarray, int] | None = None
        self.map_keyframes: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self.stored_frames: list[StoredFrame] = []
        self.map_from_file = False
        self.last_save = time.monotonic() - self.AUTOSAVE_S + self.FIRST_SAVE_S
        self.rebuilds = 0
        self.map_job_ready = threading.Condition()
        self.map_stop = False
        self.map_worker = threading.Thread(target=self._map_loop, daemon=True)
        self.pending_map: bytes | None = None

        self.session = str(time.time_ns())
        self.map_id = (
            MAP_ID_FILE.read_text().strip() if AREA_FILE.exists() and MAP_ID_FILE.exists() else self.session
        )
        self.map_frame_lock = threading.Lock()
        self.map_plan = Plan()
        self.map_frame = MapFrame(
            odom_session=self.session,
            map_id=LOC_NVBLOX_ID_FILE.read_text().strip() if self.applying and LOC_NVBLOX_FILE.exists() and LOC_NVBLOX_ID_FILE.exists() else None,
            step_m=self.STORED_FRAME_STEP_M,
            step_deg=self.STORED_FRAME_STEP_DEG,
            max_frames=self.MAX_STORED_FRAMES,
        )
        if self.applying and self.map_frame.map_id is not None:
            self.map_id = self.map_frame.map_id
        self.grid_payload = b""
        self.robot_xz = (0.0, 0.0)
        self.view_open = False
        self.localized_since: float | None = None
        self.last_integrated: tuple[float, np.ndarray] | None = None
        self.skipped_jumps = 0
        self.pending_grid: bytes | None = None
        self.grid_dirty = False
        self.last_grid = 0.0
        self.grid_ms = 0.0
        self.map_save = False
        self.area_export = "NONE"
        self.set_log_context(map_session=self.session, odom_session=self.session, map_id=self.map_id)
        self.mapping_enabled = False
        self.last_mesh_update = 0.0
        self.save_requested = False
        self.block_ids: dict[tuple[int, int, int], int] = {}
        self.block_meshes: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.encoded_chunks: dict[int, bytes] = {}
        self.relocalization = Relocalization(
            self.RELOCALIZED_STABLE_S, self.RELOCALIZATION_DISTANCE_M, self.MAX_RELOCALIZATION_STEP_M, self.RELOCALIZATION_TIMEOUT_S
        )
        self.restarting = False
        self.started_at = time.monotonic()
        self.active_until = self.started_at + self.IDLE_AFTER_S
        self.watched_until = 0.0
        self.last_grab = 0.0
        self.grab_failures = 0

        self.frame_number = -1
        self.timestamp = 0
        self.preview_messages = 0
        self.preview_bytes = 0
        self.preview_skipped = 0
        self.pose_messages = 0
        self.pose_drop_count = 0
        self.implausible_poses = 0
        self.held_poses = 0
        self.jump_gate = JumpGate(self.POSE_JUMP_M, self.MAX_INTEGRATION_SPEED, self.POSE_JUMP_SETTLE_S)
        self.last_static_integration = 0.0
        self.implausible_since: float | None = None
        self.corrupted_frames = 0
        self.map_messages = 0
        self.map_bytes = 0
        self.map_chunk_count = 0
        self.map_points = 0
        self.map_triangles = 0
        self.integrated_frames = 0
        self.keyframes = 0
        self.keyframes_ms = 0.0
        self.integrate_ms = 0.0
        self.mesh_ms = 0.0
        self.mapping_state = "DISABLED"
        self.last_capture_duration_ms = 0.0
        self.last_pose_state = "UNKNOWN"
        self.last_preview_frame = -1
        self.status: dict = {}
        self.relocalizing_since: float | None = None
        self.clock_offset_ns = 0
        self.floor = FloorEstimator()
        self.floor_y: float | None = None
        self.encoded_floor_y = 0.0
        self.last_camera_height: tuple[float, float] | None = None
        self.imu_tilt_deg: float | None = None
        self.tilt_mismatch_since: float | None = None
        self.sensor_state: dict = {}
        self.detector_labels: list[str] = []
        self.detector_image_size = (1, 1)
        self.detected = sl.Objects()
        self.detector_messages = 0
        self.detector_ms = 0.0
        self.detector_tracks = TrackConfirmer(self.DETECTOR_MIN_HITS, self.DETECTOR_FORGET_AFTER)
        self.loc_policy = KeyframePolicy()
        self.loc_worker = ThreadPoolExecutor(max_workers=1)
        self.loc_job: Future | None = None
        self.loc_image = sl.Mat()
        self.loc_depth = sl.Mat()
        self.loc_intrinsics: tuple[float, float, float, float] | None = None
        self.loc_map_odom: dict | None = None
        self.loc_map_from_odom: np.ndarray | None = None
        self.loc_received_at = 0.0
        self.loc_sent = 0

    async def init(self):
        self.loop = asyncio.get_running_loop()
        status = self.zed.open(self.init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            self.event("camera.open_failed", str(status), severity="critical", message=f"Camera initialization failed: {status}")
            raise RuntimeError(f"Camera initialization failed: {status}")
        information = self.zed.get_camera_information()
        self.event(
            "camera.opened",
            f"{information.camera_model} serial {information.serial_number}",
            sdk_version=sl.Camera.get_sdk_version(),
            camera_model=str(information.camera_model),
            serial_number=str(information.serial_number),
            camera_firmware=information.camera_configuration.firmware_version,
            sensors_firmware=information.sensors_configuration.firmware_version,
            loc_mode=self.loc_mode,
            map_mode="loc" if self.applying else "mapping" if self.mapping_mode else "localization",
            area_file=AREA_FILE.exists(),
            area_bytes=AREA_FILE.stat().st_size if AREA_FILE.exists() else None,
        )

        MAP_DIR.mkdir(parents=True, exist_ok=True)
        if self.applying:
            self.logger.info("LOC_MODE=apply: GEN_3 area memory off, the map frame comes from rabbit-loc")
        elif AREA_FILE.exists():
            self.tracking_parameters.area_file_path = str(AREA_FILE)
            self.relocalizing_since = time.monotonic()
            self.event("camera.relocalization_started", "a saved area map exists", message=f"Relocalizing against {AREA_FILE}", area_file=str(AREA_FILE))

        status = self.zed.enable_positional_tracking(self.tracking_parameters)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to enable positional tracking: {status}")
        await asyncio.to_thread(self._enable_detector)

        await self.publish_camera_intrinsics()
        await self.init_camera_settings()
        await self.watch_kv(self.CAMERA_SETTINGS_KEY, self.on_camera_settings_update)
        await self.subscribe(MAP_SAVE_SUBJECT, self.on_map_save)
        await self.subscribe(MAP_RESET_SUBJECT, self.on_map_reset)
        await self.subscribe(MAP_EXTEND_SUBJECT, self.on_map_extend)
        await self.subscribe(MAP_SNAPSHOT_SUBJECT, self.on_map_snapshot)
        await self.subscribe(MAP_GRID_SNAPSHOT_SUBJECT, self.on_grid_snapshot)
        await self.subscribe(self.RECORD_SUBJECT, self.on_record)
        await self.subscribe(JOY_SUBJECT, self.on_joy)
        await self.subscribe(HEARTBEAT_SUBJECT, self.on_heartbeat)
        await self.subscribe(CAMERA_WAKE_SUBJECT, self.on_wake)
        await self.subscribe(DRIVE_SUBJECT, self.on_drive)
        await self.subscribe(self.NAV_STATE_SUBJECT, self.on_nav_state)
        if self.loc_mode != "off":
            await self.subscribe(MAP_ODOM_SUBJECT, self.on_loc_map_odom)
        self.preview_every_n_frames = max(
            1, round(self.COMPUTE_FPS / self.PREVIEW_FPS)
        )

        self._sensors_thread.start()
        self.map_worker.start()
        threading.Thread(target=self._gil_watch, daemon=True).start()
        if self.applying:
            await asyncio.to_thread(self._load_map)
        await self.async_task(self.capture)
        self.set_interval(self.publish_sensors, self.SENSOR_PUBLISH_S, max_parallel=1)
        self.set_interval(self.publish_health, 1, max_parallel=1)

    async def close(self):
        await asyncio.to_thread(self._shutdown_camera)

    def _shutdown_camera(self):
        self._sensors_stop.set()
        if self._sensors_thread.is_alive():
            self._sensors_thread.join()
        with self.map_job_ready:
            self.map_stop = True
            self.map_job_ready.notify()
        self.map_worker.join()
        with self._camera_lock:
            self._save_map(sync=True)
            deadline = time.monotonic() + self.AREA_EXPORT_TIMEOUT_S
            while (
                self.zed.get_area_export_state() == sl.AREA_EXPORTING_STATE.RUNNING
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
            self.logger.info(f"Area export: {self.zed.get_area_export_state()}")
            self.zed.close()

    def _save_map(self, sync: bool = False):
        if self.restarting:
            self.event("map.save_skipped", "the session is being discarded", severity="warning", message="Not saving the map of a discarded session")
            return
        if self.relocalizing_since is not None:
            self.event("map.save_skipped", "not relocalized against the saved map yet", severity="warning", every_s=60.0, message="Not saving the map before relocalizing against the saved one")
            return
        memory = self.status.get("spatial_memory_status")
        if self.applying:
            self.area_export = "off (LOC_MODE=apply)"
        elif self.mapping_mode and memory in LOCALIZED_STATES:
            status = self.zed.save_area_map(str(AREA_FILE))
            if status != sl.ERROR_CODE.SUCCESS:
                self.event("map.save_failed", f"area map: {status}", severity="error", message=f"Failed to save area map: {status}")
            self.area_export = status.name
            MAP_ID_FILE.write_text(self.map_id)
        else:
            self.area_export = f"kept ({'mapping' if self.mapping_mode else 'localization'}, {memory})"
        self.last_save = time.monotonic()
        if not self.mapping_enabled:
            return
        if sync:
            with self.mapper_lock:
                self._save_nvblox()
            return
        with self.map_job_ready:
            self.map_save = True
            self.map_job_ready.notify()

    def _save_nvblox(self):
        started = time.monotonic()
        if self.applying and self.map_frame.map_id is None:
            return
        staging = self.nvblox_file.with_suffix(".tmp")
        if not self.mapper.save(str(staging)):
            self.event("map.save_failed", "nvblox map", severity="error", message=f"Failed to save the nvblox map to {staging}")
            return
        staging.replace(self.nvblox_file)
        self.map_from_file = True
        if self.applying:
            LOC_NVBLOX_ID_FILE.write_text(self.map_frame.map_id or "")
            with self.map_frame_lock:
                self.map_frame.saved()
        else:
            self.stored_frames.clear()
        if not self.mapper.save_mesh(str(MESH_FILE)):
            self.logger.error(f"Failed to save mesh to {MESH_FILE}")
        self.event(
            "map.saved",
            f"area export {self.area_export}",
            message=f"Saved the map: area export {self.area_export}, {self.map_chunk_count} blocks to {self.nvblox_file} in {time.monotonic() - started:.1f} s",
            area_export=self.area_export,
            blocks=self.map_chunk_count,
            save_s=time.monotonic() - started,
            file=str(self.nvblox_file),
        )

    async def on_map_save(self, msg: Msg):
        self.save_requested = True

    async def on_map_reset(self, msg: Msg):
        source = json.loads(msg.data or b"{}").get("source", "unknown")
        self.event("map.reset", f"requested by {source}", severity="warning", source=source)
        await asyncio.to_thread(self._reset_map, source)

    async def on_map_extend(self, msg: Msg):
        source = json.loads(msg.data or b"{}").get("source", "unknown")
        memory = self.status.get("spatial_memory_status")
        if self.applying:
            answer = {"accepted": True, "restarting": False, "reason": "rabbit-loc extends its map by itself (LOC_MODE=apply)"}
        elif self.mapping_mode:
            answer = {"accepted": True, "restarting": False, "reason": "already mapping"}
        elif self.relocalizing_since is not None or memory not in LOCALIZED_STATES:
            answer = {"accepted": False, "restarting": False, "reason": f"not localized in the saved map ({memory})"}
        else:
            answer = {"accepted": True, "restarting": True, "reason": "restarting the camera in mapping mode"}
        self.event(
            "map.extend_requested",
            answer["reason"],
            message=f"Map extension requested by {source}: {answer['reason']}",
            source=source,
            accepted=answer["accepted"],
            restarting=answer["restarting"],
            spatial_memory=memory,
        )
        if msg.reply:
            await self.publish_json(msg.reply, answer)
        if answer["restarting"]:
            await asyncio.to_thread(self._switch_map_mode, True, f"map extension requested by {source}")

    def _switch_map_mode(self, mapping: bool, reason: str):
        with self._camera_lock:
            if self.restarting:
                return
            if mapping:
                EXTEND_FILE.touch()
            else:
                EXTEND_FILE.unlink(missing_ok=True)
            self._save_map(sync=True)
            self._restart_process(reason, archive=False)

    def _reset_map(self, source: str):
        with self._camera_lock:
            self._restart_process(f"map reset requested by {source}", archive=True)

    def _keep_active(self):
        self.active_until = time.monotonic() + self.IDLE_AFTER_S

    async def on_wake(self, msg: Msg):
        seconds = float(json.loads(msg.data or b"{}").get("seconds", self.IDLE_AFTER_S))
        self.active_until = max(self.active_until, time.monotonic() + min(seconds, self.MAX_WAKE_S))

    async def on_heartbeat(self, msg: Msg):
        self.watched_until = time.monotonic() + self.WATCHED_FOR_S

    async def on_joy(self, msg: Msg):
        if is_active(*parse_joy(json.loads(msg.data))):
            self._keep_active()

    async def on_drive(self, msg: Msg):
        command = json.loads(msg.data)
        if command.get("speed") or command.get("steer"):
            self._keep_active()

    async def on_nav_state(self, msg: Msg):
        if json.loads(msg.data).get("mode") in ("driving", "maneuvering", "blocked"):
            self._keep_active()

    async def on_record(self, msg: Msg):
        name = json.loads(msg.data or b"{}").get("name")
        await asyncio.to_thread(self._record, name)

    def _record(self, name: str | None):
        with self._camera_lock:
            if self.recording_since is not None:
                status = self.zed.get_recording_status()
                elapsed = time.monotonic() - self.recording_since
                self.event(
                    "camera.recording_stopped",
                    "requested" if not name else f"switching to {name}",
                    message=(
                        f"Recording stopped: {status.number_frames_encoded} frames in {elapsed:.0f} s "
                        f"({status.number_frames_encoded / max(elapsed, 1e-3):.1f} fps), "
                        f"{status.number_frames_ingested} ingested, compression {status.average_compression_time:.0f} ms/frame"
                    ),
                    frames=status.number_frames_encoded,
                    ingested=status.number_frames_ingested,
                    duration_s=elapsed,
                    fps=status.number_frames_encoded / max(elapsed, 1e-3),
                    compression_ms=status.average_compression_time,
                )
            self.zed.disable_recording()
            self.recording_since = None
            if not name:
                return
            self.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            path = self.RECORDINGS_DIR / f"{Path(name).name}.svo2"
            status = self.zed.enable_recording(sl.RecordingParameters(str(path), sl.SVO_COMPRESSION_MODE.LOSSLESS))
            if status == sl.ERROR_CODE.SUCCESS:
                self.recording_since = time.monotonic()
            self.event(
                "camera.recording_started" if status == sl.ERROR_CODE.SUCCESS else "camera.recording_failed",
                str(status),
                severity="info" if status == sl.ERROR_CODE.SUCCESS else "error",
                message=f"Recording to {path}: {status}",
                file=str(path),
            )

    def _map_headers(self, kind: str) -> dict:
        return {"session": self.session, "map": self.map_id, "format": kind}

    async def on_grid_snapshot(self, msg: Msg):
        await self.publish(msg.reply, self.grid_payload, headers=self._map_headers("grid"))

    async def on_map_snapshot(self, msg: Msg):
        with self.map_lock:
            snapshot = b"".join(self.encoded_chunks.values())
        await self.publish(
            msg.reply,
            snapshot,
            headers=self._map_headers("mesh"),
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
        if self.recording_since is not None and shutil.disk_usage(self.RECORDINGS_DIR).free < self.MIN_FREE_DISK_BYTES:
            self.event("camera.recording_disk_full", "less than 10 GB free", severity="warning", message="Stopping the recording: the disk is almost full")
            await asyncio.to_thread(self._record, None)
        if not self.status:
            return
        await self.publish_json(
            self.HEALTH_SUBJECT,
            {
                "frame_number": self.frame_number,
                "timestamp": self.timestamp,
                "camera_fps": self.COMPUTE_FPS,
                "current_fps": round(self.zed.get_current_fps(), 1),
                "preview_every_n_frames": self.preview_every_n_frames,
                "preview_messages": self.preview_messages,
                "preview_bytes": self.preview_bytes,
                "preview_skipped": self.preview_skipped,
                "pose_messages": self.pose_messages,
                "pose_drop_count": self.pose_drop_count,
                "implausible_poses": self.implausible_poses,
                "held_poses": self.held_poses,
                "odom_rejected": self.odom_rejected,
                "dropped_publishes": self.dropped_publishes,
                "corrupted_frames": self.corrupted_frames,
                "last_capture_duration_ms": self.last_capture_duration_ms,
                "last_pose_state": self.last_pose_state,
                "last_preview_frame": self.last_preview_frame,
                **self.status,
                "mapping_state": self.mapping_state,
                "integrated_frames": self.integrated_frames,
                "keyframes": self.keyframes,
                "keyframes_ms": round(self.keyframes_ms, 1),
                "map_id": self.map_id,
                "map_mode": "loc" if self.applying else "mapping" if self.mapping_mode else "localization",
                "relocalizing": not self.map_frame.localized(time.monotonic()) if self.applying else self.relocalizing_since is not None,
                "grid_ms": round(self.grid_ms, 2),
                "skipped_jumps": self.skipped_jumps,
                "idle": time.monotonic() > self.active_until,
                "stored_frames": len(self.map_frame.frames) if self.applying else len(self.stored_frames),
                "map_rebuilds": self.rebuilds,
                "integrate_ms": round(self.integrate_ms, 2),
                "mesh_ms": round(self.mesh_ms, 2),
                "map_session": self.session,
                "map_chunks": self.map_chunk_count,
                "map_points": self.map_points,
                "map_triangles": self.map_triangles,
                "floor_y": None if self.floor_y is None else round(self.floor_y, 3),
                "map_messages": self.map_messages,
                "detector_labels": len(self.detector_labels),
                "detector_messages": self.detector_messages,
                "detector_ms": round(self.detector_ms, 2),
                "map_bytes": self.map_bytes,
                "loc": self._loc_health() if self.loc_mode != "off" else None,
                **self.sensor_state,
            },
        )

    def _grab(self) -> CapturedFrame | None:
        if self.restarting:
            return None
        with self._camera_lock:
            self.runtime_params.enable_depth = (self.frame_number + 1) % self.DEPTH_EVERY_N_FRAMES == 0
            grab_started = time.monotonic()
            status = self.zed.grab(self.runtime_params)
            grab_s = time.monotonic() - grab_started
            self.observe("grab_ms", grab_s * 1000.0)
            if grab_s > self.SLOW_STEP_S:
                self.logger.warning(f"Slow grab: {grab_s * 1000:.0f} ms")
            if status == sl.ERROR_CODE.CORRUPTED_FRAME:
                self.corrupted_frames += 1
                return None
            if status != sl.ERROR_CODE.SUCCESS:
                self.grab_failures += 1
                self.event("camera.grab_failed", str(status), severity="warning", every_s=5.0, failures=self.grab_failures)
                if self.grab_failures >= self.MAX_GRAB_FAILURES:
                    self._restart_process(f"grab keeps failing: {status}", archive=False)
                raise RuntimeError(f"Failed to grab image from ZED camera: {status}")
            self.grab_failures = 0

            started = time.monotonic()
            marks = [("grab", started)]
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
                self._update_odom()
            if tracking_ok and not plausible_position(self.pose.get_translation().get(), self.floor_y or 0.0):
                tracking_ok = False
                self.implausible_poses += 1
                if self.implausible_since is None:
                    self.implausible_since = time.monotonic()
                    sample = np.round(self.pose.get_translation().get(), 2).tolist()
                    self.event(
                        "camera.implausible_poses",
                        "the SDK reports positions far from the map",
                        severity="warning",
                        message=f"Dropping implausible poses such as {sample}",
                        sample=sample,
                        relocalizing=self.relocalizing_since is not None,
                        implausible_poses=self.implausible_poses,
                    )
                elif self.relocalizing_since is None and time.monotonic() - self.implausible_since > self.IMPLAUSIBLE_RESTART_S:
                    self._restart_process("the SDK keeps reporting implausible poses", archive=False)
                    return None
            elif tracking_ok:
                self.implausible_since = None
            if tracking_ok and not self.jump_gate.update(time.monotonic(), self.pose.get_translation().get()):
                tracking_ok = False
                self.held_poses += 1

            if tracking_ok:
                _, translation = self._camera_pose()
                self.robot_xz = (float(translation[0]), float(translation[2]))
                self._update_floor()
                self._emit(
                    self.POSE_SUBJECT,
                    {
                        "ts": self.timestamp + self.clock_offset_ns,
                        "frame_number": self.frame_number,
                        "timestamp": self.timestamp,
                        **self._read_pose(),
                    },
                )
                self.pose_messages += 1
                self.last_pose_state = "OK"
                if self.frame_number % self.OBSTACLE_EVERY_N_FRAMES == 0:
                    self._queue_obstacles()
                if self.loc_mode != "off" and self.runtime_params.enable_depth and self.odom is not None and self.recording_since is None:
                    self._queue_loc_keyframe()
                twist = np.abs(np.asarray(self.pose.twist, dtype=float))
                if np.linalg.norm(twist[:3]) > self.MOVING_SPEED or np.linalg.norm(twist[3:]) > self.MOVING_TURN_RATE:
                    self._keep_active()
            else:
                self.pose_drop_count += 1
                self.last_pose_state = "LOST"
            marks.append(('pose', time.monotonic()))
            self._update_map(tracking_ok)
            with self.map_lock:
                map_update, self.pending_map = self.pending_map, None

            marks.append(('map', time.monotonic()))
            if self.save_requested:
                self.save_requested = False
                self._save_map()

            marks.append(('save', time.monotonic()))
            preview = None
            if time.monotonic() > self.active_until or self.frame_number % self.preview_every_n_frames == 0:
                status = self.zed.retrieve_image(
                    self.image, sl.VIEW.LEFT, sl.MEM.CPU, sl.Resolution(*self.PREVIEW_RESOLUTION)
                )
                if status != sl.ERROR_CODE.SUCCESS:
                    raise RuntimeError(f"Failed to retrieve RGB image: {status}")
                preview = cv2.cvtColor(self.image.get_data(), cv2.COLOR_BGRA2BGR)

            marks.append(('preview', time.monotonic()))
            if self.frame_number % self.STATUS_EVERY_N_FRAMES == 0:
                self.clock_offset_ns = time.time_ns() - self.zed.get_timestamp(
                    sl.TIME_REFERENCE.CURRENT
                ).get_nanoseconds()
                self.status = self._read_status()
                if self.status["spatial_memory_status"] not in LOCALIZED_STATES:
                    self.localized_since = None
                elif self.localized_since is None:
                    self.localized_since = time.monotonic()
                self._check_relocalization(tracking_ok)
                self._check_tilt(tracking_ok)
            marks.append(('status', time.monotonic()))
            if self.mapping_enabled and not self.applying and self.frame_number % self.KEYFRAMES_EVERY_N_FRAMES == 0:
                self._queue_keyframes()
            marks.append(('keyframes', time.monotonic()))
            if (
                self.mapping_enabled
                and time.monotonic() > self.active_until
                and time.monotonic() - self.last_save > self.AUTOSAVE_S
            ):
                self.save_requested = True
            if (
                self.mapping_mode
                and self.mapping_enabled
                and self.view_open
                and self.localized_since is not None
                and time.monotonic() - self.localized_since > self.SWITCH_LOCALIZED_S
                and time.monotonic() - self.active_until > self.MAPPING_IDLE_S
            ):
                EXTEND_FILE.unlink(missing_ok=True)
                self._save_map(sync=True)
                self._restart_process("idle after mapping, switching to localization", archive=False)
                return None

            self.last_capture_duration_ms = (time.monotonic() - started) * 1000.0
            self.observe("frame_ms", self.last_capture_duration_ms)
            if self.last_capture_duration_ms > self.SLOW_STEP_S * 1000.0:
                steps = ", ".join(f"{name} {(at - previous) * 1000:.0f}" for (_, previous), (name, at) in zip(marks, marks[1:]))
                self.logger.warning(f"Slow frame processing: {self.last_capture_duration_ms:.0f} ms ({steps})")
            return CapturedFrame(
                frame_number=self.frame_number,
                timestamp=self.timestamp,
                preview=preview,
                map_update=map_update,
                objects=self._detect_objects()
                if tracking_ok and self.detector_labels and self.recording_since is None and self.frame_number % self._detector_every() == 0
                else None,
            )

    def _detector_every(self) -> int:
        return self.DETECTOR_EVERY_N_FRAMES_MOVING if time.monotonic() < self.active_until else self.DETECTOR_EVERY_N_FRAMES

    def _camera_pose(self) -> tuple[np.ndarray, np.ndarray]:
        if self.applying and self.odom is not None:
            world = self.map_frame.to_map(self.odom)
            world = self.odom if world is None else world
            return world[:3, :3], world[:3, 3]
        return quaternion_to_matrix(self.pose.get_orientation().get()), np.asarray(self.pose.get_translation().get(), dtype=float)

    def _update_floor(self):
        rotation, translation = self._camera_pose()
        camera_x, camera_y, camera_z = (float(v) for v in translation)
        now = time.monotonic()
        previous, self.last_camera_height = self.last_camera_height, (now, camera_y)
        if previous is None or now <= previous[0]:
            return
        vertical_speed = abs(camera_y - previous[1]) / (now - previous[0])
        if vertical_speed > self.FLOOR_MAX_VERTICAL_SPEED or tilt_deg(matrix_to_quaternion(rotation)) > self.FLOOR_MAX_TILT_DEG:
            return
        self.floor_y = self.floor.update(camera_x, camera_y, camera_z)

    def _floor(self) -> float:
        return self.encoded_floor_y

    def _update_odom(self):
        if self.odom is None:
            if plausible_position(self.pose.get_translation().get(), self.floor_y or 0.0):
                self.odom = np.asarray(self.pose.pose_data().m, dtype=float)
                self.odom_timestamp = self.timestamp
            return
        if self.zed.get_position(self.step_pose, sl.REFERENCE_FRAME.CAMERA) != sl.POSITIONAL_TRACKING_STATE.OK:
            self.odom_rejected += 1
            return
        step = np.asarray(self.step_pose.pose_data().m, dtype=float)
        elapsed = max(0.0, (self.timestamp - self.odom_timestamp) * 1e-9)
        self.odom_timestamp = self.timestamp
        if not odometry_step_ok(step, elapsed, self.MAX_INTEGRATION_SPEED, self.MAX_TURN_RATE_DEG, self.ODOM_STEP_SLACK_M, self.ODOM_STEP_SLACK_DEG):
            self.odom_rejected += 1
            return
        self.odom = self.odom @ step

    def _read_pose(self) -> dict:
        twist = np.asarray(self.pose.twist, dtype=float)
        covariance = np.asarray(self.pose.pose_covariance, dtype=float).reshape(6, 6)
        if self.applying:
            rotation, world = self._camera_pose()
            translation = world - np.array([0.0, self._floor(), 0.0])
            orientation = matrix_to_quaternion(rotation)
            euler = euler_deg(rotation)
        else:
            translation = np.asarray(self.pose.get_translation().get(), dtype=float) - np.array([0.0, self._floor(), 0.0])
            orientation = self.pose.get_orientation().get()
            euler = self.pose.get_euler_angles(radian=False)
        return {
            "translation": [round(float(v), 4) for v in translation],
            "orientation": [round(float(v), 6) for v in orientation],
            "euler_deg": [round(float(v), 3) for v in euler],
            "velocity": [round(float(v), 4) for v in twist[:3]],
            "angular_velocity": [round(float(v), 4) for v in twist[3:]],
            "position_std": [round(float(v), 5) for v in np.sqrt(np.diag(covariance)[:3])],
            "confidence": self.pose.pose_confidence,
            "odom": self._read_odom(),
        }

    def _read_odom(self) -> dict | None:
        if self.odom is None:
            return None
        translation = self.odom[:3, 3] - np.array([0.0, self._floor(), 0.0])
        return {
            "translation": [round(float(v), 4) for v in translation],
            "orientation": [round(float(v), 6) for v in matrix_to_quaternion(self.odom[:3, :3])],
            "session": self.session,
        }

    async def on_loc_map_odom(self, msg: Msg):
        payload = json.loads(msg.data)
        self.loc_map_odom = payload
        self.loc_received_at = time.monotonic()
        transform = payload.get("transform")
        self.loc_map_from_odom = None if transform is None else np.asarray(transform, dtype=float).reshape(4, 4)
        if not self.applying:
            return
        with self.map_frame_lock:
            plan = self.map_frame.receive(payload, time.monotonic())
        if self.map_frame.map_id is not None:
            self.map_id = self.map_frame.map_id
        if plan != Plan():
            with self.map_job_ready:
                self.map_plan = Plan(
                    reset=self.map_plan.reset or plan.reset,
                    rebuild=self.map_plan.rebuild or plan.rebuild,
                    flush=self.map_plan.flush or plan.flush,
                )
                self.map_job_ready.notify()

    def _queue_loc_keyframe(self):
        if self.loc_job is not None and not self.loc_job.done():
            return
        now = time.monotonic()
        localized = (self.loc_map_odom or {}).get("status") == LOCALIZED
        if not self.loc_policy.due(now, self.odom, localized):
            return
        resolution = sl.Resolution(*self.DEPTH_RESOLUTION)
        if (
            self.zed.retrieve_image(self.loc_image, sl.VIEW.LEFT, sl.MEM.CPU, resolution) != sl.ERROR_CODE.SUCCESS
            or self.zed.retrieve_measure(self.loc_depth, sl.MEASURE.DEPTH, sl.MEM.CPU, resolution) != sl.ERROR_CODE.SUCCESS
        ):
            return
        if self.loc_intrinsics is None:
            left = self.zed.get_camera_information(resolution).camera_configuration.calibration_parameters.left_cam
            self.loc_intrinsics = (left.fx, left.fy, left.cx, left.cy)
        self.loc_policy.sent(now, self.odom)
        self.loc_job = self.loc_worker.submit(
            self._send_loc_keyframe,
            self.timestamp + self.clock_offset_ns,
            self.odom.copy(),
            np.array(self.loc_image.get_data()[:, :, :3]),
            np.array(self.loc_depth.get_data(), dtype=np.float32),
        )

    def _send_loc_keyframe(self, ts: int, odom: np.ndarray, image: np.ndarray, depth: np.ndarray):
        millimetres = np.nan_to_num(depth * 1000.0, nan=0.0, posinf=0.0, neginf=0.0)
        ok_rgb, rgb = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        ok_depth, png = cv2.imencode(".png", np.clip(millimetres, 0, 65535).astype(np.uint16), [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not (ok_rgb and ok_depth):
            return
        payload, headers = encode_keyframe(ts, self.session, odom, self.loc_intrinsics, rgb.tobytes(), png.tobytes())
        asyncio.run_coroutine_threadsafe(self.publish(KEYFRAME_SUBJECT, payload, headers=headers), self.loop)
        self.loc_sent += 1

    def _loc_health(self) -> dict:
        state = self.loc_map_odom or {}
        health = {
            "mode": self.loc_mode,
            "status": state.get("status"),
            "loc_mode": state.get("mode"),
            "age_s": round(time.monotonic() - self.loc_received_at, 1) if self.loc_map_odom else None,
            "matches": state.get("matches"),
            "corrections": state.get("corrections"),
            "map_id": state.get("map_id"),
            "keyframes_sent": self.loc_sent,
            "gen3_from_loc": None,
            "map_frame": self.map_frame.health(time.monotonic()) if self.applying else None,
        }
        if (
            self.loc_map_from_odom is not None
            and self.odom is not None
            and self.last_pose_state == "OK"
            and self.status.get("spatial_memory_status") in LOCALIZED_STATES
        ):
            gen3 = np.asarray(self.pose.pose_data().m, dtype=float)
            x, z, yaw = planar(gen3 @ np.linalg.inv(self.loc_map_from_odom @ self.odom))
            health["gen3_from_loc"] = [round(x, 3), round(z, 3), round(yaw, 2)]
        if self.loc_mode == "shadow":
            self._log_shadow(health)
        return health

    def _log_shadow(self, health: dict):
        if self.odom is None:
            return
        SHADOW_LOG.parent.mkdir(parents=True, exist_ok=True)
        if SHADOW_LOG.exists() and SHADOW_LOG.stat().st_size > SHADOW_LOG_MAX_BYTES:
            SHADOW_LOG.replace(SHADOW_LOG.with_suffix(".jsonl.1"))
        x, z, yaw = planar(self.odom)
        line = {"t": time.time(), "odom": [round(x, 3), round(z, 3), round(yaw, 2)], **health}
        with SHADOW_LOG.open("a") as f:
            f.write(json.dumps(line, separators=(",", ":")) + "\n")

    def _emit(self, subject: str, payload: dict):
        asyncio.run_coroutine_threadsafe(self.publish_json(subject, payload), self.loop)

    def _queue_obstacles(self):
        if self.obstacle_job is not None and not self.obstacle_job.done():
            return
        width, height = self.OBSTACLE_RESOLUTION
        if self.zed.retrieve_measure(self.points, sl.MEASURE.XYZ, sl.MEM.CPU, sl.Resolution(width, height)) != sl.ERROR_CODE.SUCCESS:
            return
        image = np.array(self.points.get_data()[:, :, :3], dtype=np.float32)
        rotation, origin = self._camera_pose()
        ts = self.timestamp + self.clock_offset_ns
        self.obstacle_job = self.obstacle_worker.submit(self._publish_obstacles, image, rotation, origin, self._floor(), ts)

    def _publish_obstacles(self, image: np.ndarray, rotation: np.ndarray, origin: np.ndarray, floor: float, ts: int):
        obstacles = self._find_obstacles(image, rotation, origin, floor)
        ahead = obstacles["ahead"]
        self.view_open = not obstacles["scan"]["blind"] and (ahead is None or ahead["distance"] > self.SWITCH_MIN_OPEN_M)
        self._emit(self.OBSTACLE_SUBJECT, {"ts": ts, **obstacles})

    def _find_obstacles(self, image: np.ndarray, rotation: np.ndarray, origin: np.ndarray, floor: float) -> dict:
        rows, columns = image.shape[:2]
        window = image[
            int(rows * self.BLIND_ROWS[0]) : int(rows * self.BLIND_ROWS[1]),
            int(columns * self.BLIND_COLUMNS[0]) : int(columns * self.BLIND_COLUMNS[1]),
        ]
        blind_fraction = float(1.0 - np.isfinite(window).all(axis=2).mean())
        camera = image.reshape(-1, 3)
        camera = camera[np.isfinite(camera).all(axis=1)]
        camera = camera[np.linalg.norm(camera, axis=1) > self.OBSTACLE_MIN_DEPTH]
        world = camera @ rotation.T + origin
        world[:, 1] -= floor
        origin = origin - np.array([0.0, floor, 0.0])

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

    def _enable_detector(self):
        if not DETECTOR_MODEL.exists():
            self.event("detector.disabled", "model file not found", message=f"Object detection disabled: {DETECTOR_MODEL} not found")
            return
        labels = load_labels(DETECTOR_LABELS)
        parameters = sl.ObjectDetectionParameters()
        parameters.detection_model = sl.OBJECT_DETECTION_MODEL.CUSTOM_YOLOLIKE_BOX_OBJECTS
        parameters.custom_onnx_file = str(DETECTOR_MODEL)
        parameters.custom_onnx_dynamic_input_shape = sl.Resolution(*self.DETECTOR_INPUT)
        parameters.enable_tracking = True
        parameters.max_range = self.DETECTOR_MAX_RANGE
        started = time.monotonic()
        status = self.zed.enable_object_detection(parameters)
        if status != sl.ERROR_CODE.SUCCESS:
            self.event("detector.failed", str(status), severity="error", message=f"Failed to enable object detection: {status}")
            return

        runtime = sl.CustomObjectDetectionRuntimeParameters()
        runtime.object_detection_properties.detection_confidence_threshold = DEFAULT_CONFIDENCE
        properties = {}
        for index, label in enumerate(labels):
            item = sl.CustomObjectDetectionProperties()
            item.detection_confidence_threshold = confidence_threshold(label)
            item.is_static = label not in MOVING_LABELS
            properties[index] = item
        runtime.object_class_detection_properties = properties
        self.zed.set_custom_object_detection_runtime_parameters(runtime)
        resolution = self.zed.get_camera_information().camera_configuration.resolution
        self.detector_image_size = (resolution.width, resolution.height)
        self.detector_labels = labels
        self.event(
            "detector.enabled",
            f"{len(labels)} labels",
            message=f"Object detection enabled with {len(labels)} labels in {time.monotonic() - started:.1f} s",
            labels=len(labels),
            enable_s=time.monotonic() - started,
        )

    def _detect_objects(self) -> list[DetectedObject] | None:
        started = time.monotonic()
        if self.zed.retrieve_objects(self.detected) != sl.ERROR_CODE.SUCCESS:
            return None
        rotation, origin = self._camera_pose()
        objects = []
        items = [
            item
            for item in self.detected.object_list
            if item.tracking_state == sl.OBJECT_TRACKING_STATE.OK
            and np.isfinite(np.asarray(item.position, dtype=float)).all()
            and np.isfinite(np.asarray(item.dimensions, dtype=float)).all()
        ]
        confirmed = self.detector_tracks.update([item.id for item in items])
        camera = origin - np.array([0.0, self._floor(), 0.0])
        for item in items:
            if item.id not in confirmed:
                continue
            label = self.detector_labels[item.raw_label] if 0 <= item.raw_label < len(self.detector_labels) else "object"
            position = to_world(np.asarray(item.position, dtype=float), rotation, origin, self._floor())
            width, height, _ = (float(v) for v in item.dimensions)
            objects.append(
                DetectedObject(
                    id=item.id,
                    label=label,
                    confidence=round(float(item.confidence), 1),
                    position=position,
                    dimensions=[round(width, 3), round(height, 3), round(object_depth(label, width), 3)],
                    corners=object_corners(np.asarray(position), camera, label, width, height),
                    box=normalized_box(item.bounding_box_2d, *self.detector_image_size),
                    moving=label in MOVING_LABELS,
                )
            )
        self.detector_ms = (time.monotonic() - started) * 1000.0
        return objects

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

    def _check_relocalization(self, tracking_ok: bool):
        if self.relocalizing_since is None:
            return
        memory = self.status["spatial_memory_status"]
        position = np.asarray(self.pose.get_translation().get(), dtype=float)[[0, 2]] if tracking_ok else None
        outcome = self.relocalization.update(memory, time.monotonic(), position)
        waited = time.monotonic() - self.relocalizing_since
        if outcome == "relocalized":
            self.relocalizing_since = None
            self.implausible_since = None
            self.event("camera.relocalized", memory, message=f"Relocalized ({memory})", spatial_memory=memory, relocalization_s=waited, travel_m=self.relocalization.travel_m)
            self._load_map()
        elif outcome in ("give_up", "timeout"):
            self.event(
                "camera.relocalization_failed",
                "drove too far without a fix" if outcome == "give_up" else "no fix in time",
                severity="error",
                outcome=outcome,
                spatial_memory=memory,
                relocalization_s=waited,
                travel_m=self.relocalization.travel_m,
                travel_limit_m=self.RELOCALIZATION_DISTANCE_M,
                timeout_s=self.RELOCALIZATION_TIMEOUT_S,
            )
            if outcome == "give_up":
                self._restart_process(f"no relocalization after driving {self.relocalization.travel_m:.1f} m", archive=True)
            else:
                self._restart_process(f"no relocalization within {self.RELOCALIZATION_TIMEOUT_S:.0f} s, starting a new map", archive=True)

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
            self.event(
                "camera.tracking_failed",
                "pose tilt disagrees with the IMU",
                severity="error",
                pose_tilt_deg=pose_tilt,
                imu_tilt_deg=self.imu_tilt_deg,
                mismatch_limit_deg=self.TILT_MISMATCH_DEG,
                uptime_s=time.monotonic() - self.started_at,
            )
            self._restart_process(
                f"pose tilt {pose_tilt:.1f} deg disagrees with IMU {self.imu_tilt_deg:.1f} deg",
                archive=time.monotonic() - self.started_at < self.FRESH_MAP_SUSPECT_S,
            )

    def _restart_process(self, reason: str, archive: bool):
        if self.restarting:
            return
        self.restarting = True
        self.stop_reason = f"camera restart: {reason}"
        self.event(
            "camera.restart",
            reason,
            severity="warning",
            message=f"Restarting the camera process: {reason}",
            archive_map=archive,
            uptime_s=time.monotonic() - self.started_at,
            relocalizing=self.relocalizing_since is not None,
            map_mode="loc" if self.applying else "mapping" if self.mapping_mode else "localization",
            spatial_memory=self.status.get("spatial_memory_status"),
            map_blocks=self.map_chunk_count,
        )
        if archive:
            self._archive_area()
        os.kill(os.getpid(), signal.SIGTERM)

    def _archive_area(self):
        EXTEND_FILE.unlink(missing_ok=True)
        if self.applying:
            self._archive_loc_map()
            return
        if not AREA_FILE.exists():
            return
        AREA_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archived = AREA_ARCHIVE_DIR / f"room.{time.strftime('%Y%m%d-%H%M%S')}.area"
        AREA_FILE.replace(archived)
        if NVBLOX_FILE.exists():
            NVBLOX_FILE.replace(archived.with_suffix(".nvblx"))
        if MAP_ID_FILE.exists():
            MAP_ID_FILE.replace(archived.with_suffix(".id"))
        self.event("map.archived", "a new map starts", severity="warning", message=f"Archived the previous area map to {archived}", file=str(archived))
        for pattern in ("room.*.area", "room.*.nvblx", "room.*.id", "room.*.chunks"):
            for stale in sorted(AREA_ARCHIVE_DIR.glob(pattern))[: -self.AREA_ARCHIVE_KEEP]:
                stale.unlink()

    def _load_map(self):
        if not self.nvblox_file.exists():
            return
        with self.mapper_lock:
            if not self.mapper.load(str(self.nvblox_file)):
                self.event("map.load_failed", "nvblox load returned false", severity="error", message=f"Failed to load the nvblox map from {self.nvblox_file}", file=str(self.nvblox_file))
                return
            self.map_from_file = True
            self.mapper.clear_below(self.encoded_floor_y - self.BELOW_FLOOR_CLEAR_M)
            self.mapper.clear_outside(*self.robot_xz, self.KEEP_RADIUS_M)
            self._publish_mesh(everything=True)
            self._publish_grid()
        self.event("map.loaded", f"{self.map_chunk_count} blocks", message=f"Loaded {self.map_chunk_count} saved map blocks", blocks=self.map_chunk_count, file=str(self.nvblox_file))

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

    def _update_map(self, tracking_ok: bool):
        if self.recording_since is not None:
            return
        if not tracking_ok or self.relocalizing_since is not None:
            return
        if not self.mapping_enabled:
            self.mapping_enabled = True
            self.mapping_state = "OK"
            with self.map_lock:
                self.pending_map = self.pending_map or b""
            self.event("mapping.enabled", "tracking is good and relocalization is done", message="Mapping enabled")
        if self.frame_number % self.INTEGRATE_EVERY_N_FRAMES:
            return
        now = time.monotonic()
        if self.sensor_state.get("camera_moving_state") == "STATIC":
            if now - self.last_static_integration < self.STATIC_INTEGRATE_S:
                return
            self.last_static_integration = now
        resolution = sl.Resolution(*self.DEPTH_RESOLUTION)
        if self.zed.retrieve_measure(self.depth, sl.MEASURE.DEPTH, sl.MEM.CPU, resolution) != sl.ERROR_CODE.SUCCESS:
            return
        if self.depth_intrinsics is None:
            left = self.zed.get_camera_information(resolution).camera_configuration.calibration_parameters.left_cam
            self.depth_intrinsics = (left.fx, left.fy, left.cx, left.cy)
        if self.applying:
            if self.odom is None:
                return
            world_from_camera = self.odom.astype(np.float32)
        else:
            world_from_camera = np.eye(4, dtype=np.float32)
            world_from_camera[:3, :3] = quaternion_to_matrix(self.pose.get_orientation().get())
            world_from_camera[:3, 3] = self.pose.get_translation().get()
        now = time.monotonic()
        previous, self.last_integrated = self.last_integrated, (now, world_from_camera[:3, 3].copy())
        if previous is not None and np.linalg.norm(world_from_camera[:3, 3] - previous[1]) > self.MAX_INTEGRATION_SPEED * max(
            now - previous[0], 1.0 / self.COMPUTE_FPS
        ):
            self.skipped_jumps += 1
            return
        with self.map_job_ready:
            self.map_job = (np.array(self.depth.get_data(), dtype=np.float32), world_from_camera, self.timestamp)
            self.map_job_ready.notify()

    def _queue_keyframes(self):
        started = time.monotonic()
        keyframes = {}
        if self.zed.get_positional_tracking_keyframes(keyframes) != sl.ERROR_CODE.SUCCESS or not keyframes:
            return
        self.keyframes = len(keyframes)
        ids = np.fromiter(keyframes.keys(), dtype=np.int64, count=len(keyframes))
        stamps = np.array([keyframes[i].timestamp.get_nanoseconds() for i in ids.tolist()], dtype=np.int64)
        poses = np.array([keyframes[i].pose.m for i in ids.tolist()], dtype=np.float64)
        self.keyframes_ms = (time.monotonic() - started) * 1000.0
        with self.map_job_ready:
            self.map_keyframes = (ids, stamps, poses)
            self.map_job_ready.notify()

    def _gil_watch(self):
        last = time.monotonic()
        while not self.map_stop:
            time.sleep(0.05)
            now = time.monotonic()
            self.observe("gil_gap_ms", (now - last) * 1000.0)
            if now - last > self.SLOW_STEP_S:
                self.logger.warning(f"GIL stall: {(now - last) * 1000:.0f} ms")
            last = now

    def _map_loop(self):
        known: dict[int, np.ndarray] = {}
        stamps = np.empty(0, dtype=np.int64)
        ids = np.empty(0, dtype=np.int64)
        while True:
            with self.map_job_ready:
                while (
                    self.map_job is None
                    and self.map_keyframes is None
                    and not self.map_save
                    and not self.map_stop
                    and self.map_plan == Plan()
                ):
                    self.map_job_ready.wait()
                if self.map_stop:
                    return
                job, self.map_job = self.map_job, None
                keyframes, self.map_keyframes = self.map_keyframes, None
                save, self.map_save = self.map_save, False
                plan, self.map_plan = self.map_plan, Plan()
            with self.mapper_lock:
                try:
                    if save:
                        self._save_nvblox()
                    if plan != Plan():
                        self._apply_plan(plan)
                    if self.applying:
                        if job is not None:
                            self._integrate_odom_frame(*job)
                        continue
                    if keyframes is not None:
                        ids, stamps, poses = keyframes
                        known = dict(zip(ids.tolist(), poses))
                        self._correct_stored_frames(known)
                    if job is None:
                        continue
                    depth, world_from_camera, timestamp = job
                    started = time.monotonic()
                    self.mapper.integrate(depth, *self.depth_intrinsics, world_from_camera, self.encoded_floor_y)
                    self.integrated_frames += 1
                    self.grid_dirty = True
                    self.integrate_ms = (time.monotonic() - started) * 1000.0
                    if len(ids):
                        nearest = int(ids[np.argmin(np.abs(stamps - timestamp))])
                        self._store_frame(depth, world_from_camera, nearest, known[nearest])
                    if started - self.last_mesh_update >= self.MESH_INTERVAL_S:
                        self.last_mesh_update = started
                        self._publish_mesh(everything=abs((self.floor_y or 0.0) - self.encoded_floor_y) > self.FLOOR_REENCODE_SHIFT)
                    if self.grid_dirty and started - self.last_grid >= self.GRID_INTERVAL_S:
                        self._publish_grid()
                except Exception as e:
                    self.logger.exception("The map worker failed")
                    self.event("mapping.failed", repr(e), severity="critical")
                    self.mapping_state = "FAILED"
                    self._restart_process("the map worker failed", archive=False)
                    return

    def _integrate_odom_frame(self, depth: np.ndarray, odom_from_camera: np.ndarray, timestamp: int):
        with self.map_frame_lock:
            integrate = self.map_frame.store(depth[::2, ::2].astype(np.float16), odom_from_camera, time.monotonic())
            world_from_camera = self.map_frame.integration_pose(odom_from_camera)
            full = self.map_frame.over_capacity()
        if full and not self.restarting:
            self._save_nvblox()
        if not integrate or world_from_camera is None:
            return
        started = time.monotonic()
        self.mapper.integrate(depth, *self.depth_intrinsics, world_from_camera.astype(np.float32), self.encoded_floor_y)
        self.integrated_frames += 1
        self.grid_dirty = True
        self.integrate_ms = (time.monotonic() - started) * 1000.0
        if started - self.last_mesh_update >= self.MESH_INTERVAL_S:
            self.last_mesh_update = started
            self._publish_mesh(everything=abs((self.floor_y or 0.0) - self.encoded_floor_y) > self.FLOOR_REENCODE_SHIFT)
        if self.grid_dirty and started - self.last_grid >= self.GRID_INTERVAL_S:
            self._publish_grid()

    def _apply_plan(self, plan: Plan):
        started = time.monotonic()
        if plan.reset:
            self._archive_loc_map()
            self.mapper.reset()
            self.map_from_file = False
            self.event("map.loc_switched", "rabbit-loc switched to another map", severity="warning", message=f"rabbit-loc switched to map {self.map_frame.map_id}: starting an empty nvblox map", loc_map_id=self.map_frame.map_id)
        with self.map_frame_lock:
            if plan.rebuild:
                frames = self.map_frame.rebuild_poses()
            elif plan.flush:
                frames = self.map_frame.pending_poses()
            else:
                frames = []
        if plan.rebuild and not plan.reset:
            self.mapper.reset()
            if self.map_from_file and not self.mapper.load(str(self.nvblox_file)):
                self.logger.error(f"Failed to reload the nvblox map from {self.nvblox_file}")
        if frames and self.depth_intrinsics is not None:
            fx, fy, cx, cy = self.depth_intrinsics
            for depth, world_from_camera in frames:
                self.mapper.integrate(
                    depth.astype(np.float32), fx / 2, fy / 2, cx / 2, cy / 2, world_from_camera.astype(np.float32), self.encoded_floor_y
                )
        if plan.reset or plan.rebuild:
            self._publish_mesh(everything=True, resend=False)
            self._publish_grid()
        if plan.rebuild:
            self.rebuilds += 1
            self.event(
                "map.rebuilt",
                "rabbit-loc moved map<-odom",
                message=(
                    f"Rebuilt the map from {len(frames)} frames in {time.monotonic() - started:.1f} s with map<-odom "
                    f"{np.round(self.map_frame.applied[:3, 3], 3).tolist() if self.map_frame.applied is not None else None}"
                ),
                frames=len(frames),
                rebuild_s=time.monotonic() - started,
                rebuilds=self.rebuilds,
            )
        elif frames:
            self.grid_dirty = True
            self.logger.info(f"Integrated {len(frames)} frames kept while rabbit-loc was not localized")

    def _archive_loc_map(self):
        if not LOC_NVBLOX_FILE.exists():
            return
        AREA_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archived = AREA_ARCHIVE_DIR / f"loc.{time.strftime('%Y%m%d-%H%M%S')}.nvblx"
        LOC_NVBLOX_FILE.replace(archived)
        if LOC_NVBLOX_ID_FILE.exists():
            LOC_NVBLOX_ID_FILE.replace(archived.with_suffix(".id"))
        self.logger.warning(f"Archived the nvblox map of the previous rabbit-loc map to {archived}")
        for pattern in ("loc.*.nvblx", "loc.*.id"):
            for stale in sorted(AREA_ARCHIVE_DIR.glob(pattern))[: -self.AREA_ARCHIVE_KEEP]:
                stale.unlink()

    def _publish_grid(self):
        started = self.last_grid = time.monotonic()
        self.grid_dirty = False
        origin_x, origin_z, resolution, clearance = self.mapper.clearance_grid(
            self.encoded_floor_y, *self.robot_xz, self.GRID_HALF_EXTENT_M
        )
        if not clearance.size:
            return
        payload = encode_grid((origin_x, origin_z), resolution, clearance)
        with self.map_lock:
            self.grid_payload = self.pending_grid = payload
        self.grid_ms = (time.monotonic() - started) * 1000.0

    def _store_frame(self, depth: np.ndarray, world_from_camera: np.ndarray, keyframe_id: int, world_from_keyframe: np.ndarray):
        if self.stored_frames:
            last = self.stored_frames[-1].world_from_camera
            moved = np.linalg.norm(world_from_camera[:3, 3] - last[:3, 3])
            if moved < self.STORED_FRAME_STEP_M and rotation_deg(last[:3, :3].T @ world_from_camera[:3, :3]) < self.STORED_FRAME_STEP_DEG:
                return
        self.stored_frames.append(
            StoredFrame(depth[::2, ::2].astype(np.float16), world_from_camera.astype(np.float64), keyframe_id, world_from_keyframe.copy())
        )
        if len(self.stored_frames) > self.MAX_STORED_FRAMES and not self.restarting:
            self._save_nvblox()

    def _correct_stored_frames(self, keyframes: dict[int, np.ndarray]):
        corrections = {}
        for frame in self.stored_frames:
            current = keyframes.get(frame.keyframe_id)
            if current is not None and frame.keyframe_id not in corrections:
                corrections[frame.keyframe_id] = current @ np.linalg.inv(frame.world_from_keyframe)
        shifts = [(np.linalg.norm(c[:3, 3]), rotation_deg(c[:3, :3])) for c in corrections.values()]
        if not shifts or max(m for m, _ in shifts) < self.CORRECTION_M and max(d for _, d in shifts) < self.CORRECTION_DEG:
            return
        started = time.monotonic()
        for frame in self.stored_frames:
            correction = corrections.get(frame.keyframe_id)
            if correction is not None:
                frame.world_from_camera = correction @ frame.world_from_camera
                frame.world_from_keyframe = keyframes[frame.keyframe_id].copy()
        self.mapper.reset()
        if self.map_from_file and not self.mapper.load(str(NVBLOX_FILE)):
            self.logger.error(f"Failed to reload the nvblox map from {NVBLOX_FILE}")
        fx, fy, cx, cy = self.depth_intrinsics
        for frame in self.stored_frames:
            self.mapper.integrate(
                frame.depth.astype(np.float32),
                fx / 2,
                fy / 2,
                cx / 2,
                cy / 2,
                frame.world_from_camera.astype(np.float32),
                self.encoded_floor_y,
            )
        self._publish_mesh(everything=True, resend=False)
        self._publish_grid()
        self.rebuilds += 1
        self.event(
            "map.rebuilt",
            "GEN_3 corrected keyframe poses",
            message=(
                f"Rebuilt the map from {len(self.stored_frames)} frames in {time.monotonic() - started:.1f} s after a pose "
                f"correction of {max(m for m, _ in shifts):.2f} m / {max(d for _, d in shifts):.1f} deg"
            ),
            frames=len(self.stored_frames),
            rebuild_s=time.monotonic() - started,
            correction_m=max(m for m, _ in shifts),
            correction_deg=max(d for _, d in shifts),
            rebuilds=self.rebuilds,
        )

    def _publish_mesh(self, everything: bool = False, resend: bool = True):
        started = time.monotonic()
        blocks = self.mapper.take_mesh_updates(everything)
        if everything:
            self.encoded_floor_y = self.floor_y or 0.0
        shift = np.array([0.0, self.encoded_floor_y, 0.0], dtype=np.float32)
        updated = []
        with self.map_lock:
            if everything:
                present = {self.block_ids.get((x, y, z)) for x, y, z, _, _ in blocks}
                empty = np.empty((0, 3), dtype=np.float32)
                for key in [key for key in self.encoded_chunks if key not in present]:
                    updated.append(encode_chunk(key, empty, empty))
                    del self.encoded_chunks[key]
                    self.block_meshes.pop(key, None)
            for x, y, z, vertices, triangles in blocks:
                key = self.block_ids.setdefault((x, y, z), len(self.block_ids))
                if not (everything and resend) and not self._mesh_changed(key, vertices, triangles):
                    continue
                encoded = encode_chunk(key, vertices - shift, triangles)
                self.encoded_chunks[key] = encoded
                self.block_meshes[key] = (vertices, triangles)
                updated.append(encoded)
            self.map_chunk_count = sum(1 for vertices, _ in self.block_meshes.values() if len(vertices))
            self.map_points = sum(len(vertices) for vertices, _ in self.block_meshes.values())
            self.map_triangles = sum(len(triangles) for _, triangles in self.block_meshes.values())
            if updated:
                self.pending_map = b"".join([self.pending_map or b"", *updated])
        self.mesh_ms = (time.monotonic() - started) * 1000.0

    def _mesh_changed(self, key: int, vertices: np.ndarray, triangles: np.ndarray) -> bool:
        previous = self.block_meshes.get(key)
        if previous is None or previous[0].shape != vertices.shape or not np.array_equal(previous[1], triangles):
            return True
        return bool(len(vertices)) and float(np.abs(previous[0] - vertices).max()) > self.MESH_CHANGE_M

    async def capture(self):
        now = time.monotonic()
        relocalizing = self.relocalizing_since is not None and now - self.relocalizing_since < self.RELOCALIZE_ACTIVE_S
        if now > self.active_until and not relocalizing:
            fps = self.IDLE_FPS if now < self.watched_until else self.UNWATCHED_FPS
            await asyncio.sleep(max(0.0, self.last_grab + 1.0 / fps - now))
        self.last_grab = time.monotonic()
        frame = await asyncio.to_thread(self._grab)
        if frame is None:
            return

        if frame.objects is not None:
            await self.publish(
                OBJECTS_SUBJECT,
                DetectedObjects(
                    ts=frame.timestamp + self.clock_offset_ns, frame_number=frame.frame_number, objects=frame.objects
                ).model_dump_json().encode(),
            )
            self.detector_messages += 1

        with self.map_lock:
            grid, self.pending_grid = self.pending_grid, None
        if grid is not None:
            await self.publish(MAP_GRID_SUBJECT, grid, headers=self._map_headers("grid"))

        if frame.map_update is not None:
            await self.publish(
                MAP_CHUNKS_SUBJECT, frame.map_update, headers=self._map_headers("mesh")
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

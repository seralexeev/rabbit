import asyncio
import json
import math
import time

import numpy as np
from lib.drive import CAMERA_WAKE_SUBJECT
from lib.log import time_id
from lib.navmap import USE_GRID, ObstacleMemory, ScanHistory, camera_frame, forward_of, map_source, scan_rays, warm_up
from lib.node import RabbitNode
from lib.spatial_map import MAP_CHUNKS_SUBJECT, MAP_DIR, MAP_GRID_SNAPSHOT_SUBJECT, MAP_GRID_SUBJECT, MAP_SNAPSHOT_SUBJECT
from lib.trip import TERMINAL, Navigator, Target, theta_to_heading
from nats.aio.msg import Msg

GOAL_SUBJECT = "rabbit.planner.goal"
STATE_SUBJECT = "rabbit.planner.state"
PLACES_SUBJECT = "rabbit.planner.places"
PLACE_SAVE_SUBJECT = "rabbit.planner.places.save"
PLACE_DELETE_SUBJECT = "rabbit.planner.places.delete"
CANCEL_SUBJECT = "rabbit.nav.cancel"
NAV_STATE_SUBJECT = "rabbit.nav.state"
POSE_SUBJECT = "rabbit.zed.pose"
OBSTACLE_SUBJECT = "rabbit.zed.obstacle"
HEALTH_SUBJECT = "rabbit.health.zed"
PLACES_FILE = MAP_DIR / "places.json"
UNSETTLED_MEMORY = ("INITIALIZING", "SEARCHING")


class Node(RabbitNode):
    TICK = 0.25
    STATE_INTERVAL = 0.5
    IDLE_STATE_INTERVAL = 2.0
    MAP_INTERVAL = 1.0
    SNAPSHOT_RETRY = 5.0
    MAX_TRIP_DISTANCE = 30.0
    POSE_FRESH = 1.0
    WAKE_SECONDS = 30.0
    WAKE_WAIT = 3.0

    def __init__(self):
        super().__init__("planner")
        self.navigator = Navigator()
        self.map = map_source()
        self.scans = ScanHistory()
        self.obstacles = ObstacleMemory()
        self.pose: dict | None = None
        self.pose_at = 0.0
        self.odom_session: str | None = None
        self.map_id: str | None = None
        self.built_version = -1
        self.built_at = 0.0
        self.building = False
        self.map_ms: float | None = None
        self.places: dict[str, dict] = {}
        self.state_at = 0.0
        self.memory: str | None = None
        self.relocalizing = False
        self.exploration_id: str | None = None

    async def init(self):
        self.places = self.load_places()
        await asyncio.to_thread(self.warm_up)
        await self.subscribe(POSE_SUBJECT, self.on_pose)
        await self.subscribe(OBSTACLE_SUBJECT, self.on_obstacle)
        await self.subscribe(NAV_STATE_SUBJECT, self.on_nav)
        await self.subscribe(HEALTH_SUBJECT, self.on_health)
        await self.subscribe(MAP_GRID_SUBJECT if USE_GRID else MAP_CHUNKS_SUBJECT, self.on_map)
        await self.subscribe(GOAL_SUBJECT, self.on_goal)
        await self.subscribe(CANCEL_SUBJECT, self.on_cancel)
        await self.subscribe(PLACES_SUBJECT, self.on_places)
        await self.subscribe(PLACE_SAVE_SUBJECT, self.on_place_save)
        await self.subscribe(PLACE_DELETE_SUBJECT, self.on_place_delete)
        self.set_interval(self.fetch_snapshot, self.SNAPSHOT_RETRY, max_parallel=1)
        self.set_interval(self.tick, self.TICK, max_parallel=1)
        self.set_interval(self.refresh_map, self.MAP_INTERVAL / 2, max_parallel=1)
        self.set_interval(self.publish_periodic_state, self.STATE_INTERVAL, max_parallel=1)

    def warm_up(self):
        began = time.monotonic()
        warm_up()
        self.event("planner.ready", "numba kernels compiled", message=f"Planner ready in {time.monotonic() - began:.1f} s", warm_up_s=time.monotonic() - began)

    async def fetch_snapshot(self):
        if self.map.ready():
            return
        subject = MAP_GRID_SNAPSHOT_SUBJECT if USE_GRID else MAP_SNAPSHOT_SUBJECT
        try:
            reply = await self.nc.request(subject, b"", timeout=10)
        except Exception as e:
            self.logger.warning(f"Map snapshot unavailable: {e!r}")
            return
        if reply.data:
            self.apply_map(reply, snapshot=True)

    def apply_map(self, msg: Msg, snapshot: bool = False):
        headers = msg.headers or {}
        session = headers.get("session")
        if self.map.apply(session, msg.data, snapshot):
            self.scans.clear()
            self.obstacles.clear()
            self.navigator.forget_trail()
            self.set_log_context(map_session=session)
            self.event(
                "map.session_changed",
                "new map session from the camera; scan memory and trail dropped",
                message=f"Map session {session} ({self.map.kind})",
                map_session=session,
                map_id=headers.get("map") or self.map_id,
                source=self.map.kind,
                from_snapshot=snapshot,
                trip_active=self.navigator.active(),
            )
        if headers.get("map"):
            self.map_id = headers["map"]
            self.set_log_context(map_id=self.map_id)

    async def on_map(self, msg: Msg):
        self.apply_map(msg)

    async def on_health(self, msg: Msg):
        health = json.loads(msg.data)
        if health.get("map_id"):
            self.map_id = str(health["map_id"])
        self.memory = health.get("spatial_memory_status")
        self.relocalizing = bool(health.get("relocalizing", False))
        if self.unsettled() and self.navigator.active() and not self.navigator.trip.preview:
            self.navigator.finish("failed", f"the camera lost its place in the map ({self.camera_state()})", time.monotonic())
            await self.flush()

    def camera_state(self) -> str:
        return "relocalizing" if self.relocalizing else str(self.memory)

    def unsettled(self) -> bool:
        return self.relocalizing or self.memory in UNSETTLED_MEMORY

    def robot_pose(self) -> tuple[float, float, float] | None:
        robot = self.navigator.robot
        return None if robot is None else (robot.x, robot.z, robot.theta)

    async def refresh_map(self):
        if not self.map.ready() or self.building:
            return
        if self.map.version == self.built_version or time.monotonic() - self.built_at < self.MAP_INTERVAL:
            return
        self.building = True
        version = self.map.version
        try:
            began = time.monotonic()
            costmap = await asyncio.to_thread(self.map.costmap, self.scans, self.navigator.trail_points(), self.robot_pose())
            self.map_ms = round((time.monotonic() - began) * 1000.0)
            self.observe("map_build_ms", self.map_ms)
            if costmap is not None:
                self.navigator.on_map(costmap, self.obstacles.points(time.monotonic()))
            self.built_version = version
            self.built_at = time.monotonic()
        finally:
            self.building = False

    async def on_pose(self, msg: Msg):
        pose = json.loads(msg.data)
        forward = forward_of(pose["orientation"])
        self.pose = pose
        self.pose_at = time.monotonic()
        odom = pose.get("odom")
        if odom is not None and odom.get("session") != self.odom_session:
            self.odom_session = odom.get("session")
            self.set_log_context(odom_session=self.odom_session)
            self.navigator.forget_trail()
        local = None
        if odom is not None:
            heading = forward_of(odom["orientation"])
            local = (np.array([odom["translation"][0], odom["translation"][2]]), math.atan2(heading[1], heading[0]))
        self.navigator.on_pose(
            np.array([pose["translation"][0], pose["translation"][2]]), math.atan2(forward[1], forward[0]), self.pose_at, local, float(pose["translation"][1])
        )

    async def on_obstacle(self, msg: Msg):
        scan = json.loads(msg.data).get("scan")
        if scan is None or self.pose is None or scan.get("blind"):
            return
        origin, forward, right = camera_frame(self.pose)
        ends, hits = scan_rays(scan, origin, forward, right)
        self.scans.add(origin, forward, ends, hits)
        self.obstacles.add(time.monotonic(), origin, ends, hits)

    async def on_nav(self, msg: Msg):
        self.navigator.on_nav(json.loads(msg.data))

    async def reply(self, msg: Msg, payload: dict):
        if msg.reply:
            await self.nc.publish(msg.reply, json.dumps({"ts": time.time_ns(), **payload}).encode())

    def target_from(self, request: dict) -> tuple[Target | None, str | None]:
        if isinstance(request.get("object"), dict):
            item = request["object"]
            size = max(float(item.get("width") or 0.0), float(item.get("length") or 0.0))
            seen_from = tuple((float(x), float(z)) for x, z in (item.get("seen_from") or [])[:20])
            return Target("object", float(item["x"]), float(item["z"]), None, str(item.get("label") or "object"), size, seen_from=seen_from), None
        if request.get("place") is not None:
            name = str(request["place"]).strip().lower()
            place = self.places.get(name)
            if place is None:
                known = ", ".join(sorted(self.places)) or "none saved"
                return None, f"unknown place {name!r} (known: {known})"
            if place.get("map_id") and self.map_id and place["map_id"] != self.map_id:
                return None, f"place {name!r} was saved on another map"
            return Target("place", float(place["x"]), float(place["z"]), place.get("heading_deg"), name, 0.0, 0.3), None
        if "x" in request and "z" in request:
            heading = request.get("heading_deg")
            return Target(
                "point", float(request["x"]), float(request["z"]), None if heading is None else float(heading), request.get("label"), 0.0,
                float(request.get("tolerance", 0.25)),
            ), None
        return None, "request needs x and z, an object or a place"

    async def on_goal(self, msg: Msg):
        request = json.loads(msg.data or b"{}")
        target, problem = self.target_from(request)
        if target is not None:
            await self.publish_json(CAMERA_WAKE_SUBJECT, {"seconds": self.WAKE_SECONDS, "source": "planner"})
            deadline = time.monotonic() + self.WAKE_WAIT
            while (self.pose is None or time.monotonic() - self.pose_at > self.POSE_FRESH) and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
        if target is not None and (self.pose is None or time.monotonic() - self.pose_at > self.POSE_FRESH):
            problem = "no fresh pose from the camera"
        if target is not None and problem is None and not self.map.ready():
            problem = "no map yet"
        if target is not None and problem is None and self.unsettled():
            problem = f"the camera is still finding itself in the map ({self.camera_state()})"
        if target is not None and problem is None:
            robot = self.navigator.robot
            assert robot is not None
            distance = math.hypot(target.x - robot.x, target.z - robot.z)
            if distance > self.MAX_TRIP_DISTANCE:
                problem = f"target is {distance:.1f} m away, farther than {self.MAX_TRIP_DISTANCE:.0f} m"
        if problem is not None or target is None:
            self.event(
                "planner.trip_rejected",
                str(problem),
                severity="warning",
                message=f"Rejected trip: {problem}",
                request=request,
                source=request.get("source"),
                requested_trip=request.get("id"),
                exploration_id=request.get("exploration_id"),
                camera=self.camera_state(),
                pose_age_s=None if self.pose is None else time.monotonic() - self.pose_at,
            )
            await self.reply(msg, {"ok": False, "error": problem})
            return
        trip_id = str(request.get("id") or f"trip-{time_id()}")
        try:
            self.navigator.request(trip_id, str(request.get("source", "unknown")), target, time.monotonic(), bool(request.get("preview")))
        except ValueError as e:
            self.event("planner.trip_rejected", f"{e}; a preview cannot replace it", severity="warning", request=request, source=request.get("source"))
            await self.reply(msg, {"ok": False, "error": f"{e}; a preview cannot replace it"})
            return
        self.exploration_id = request.get("exploration_id")
        self.set_log_context(trip_id=trip_id, exploration_id=self.exploration_id)
        await self.reply(msg, {"ok": True, "trip_id": trip_id, "target": target.summary()})
        await self.tick()

    async def on_cancel(self, msg: Msg):
        request = json.loads(msg.data or b"{}")
        if request.get("source") == "planner":
            return
        if self.navigator.active():
            self.navigator.cancel(f"cancelled by {request.get('source', 'operator')}", time.monotonic())
            await self.flush()

    async def tick(self):
        now = time.monotonic()
        if self.navigator.costmap is not None:
            self.navigator.on_map(self.navigator.costmap, self.obstacles.points(now))
        before = self.navigator.trip.phase if self.navigator.trip else None
        job = self.navigator.tick(now)
        await self.flush()
        if job is not None:
            self.logger.info(f"Planning: {job.reason}")
            try:
                result = await asyncio.to_thread(job.run)
            except Exception:
                self.navigator.planning = False
                self.logger.exception("Planning crashed")
                self.navigator.finish("failed", "planner error", time.monotonic())
                await self.flush()
                return
            self.observe("plan_ms", result.milliseconds)
            self.navigator.on_plan(result, job.trip_id, time.monotonic())
            await self.flush()
        trip = self.navigator.trip
        if trip is not None and trip.phase != before:
            if trip.phase in TERMINAL:
                self.set_log_context(trip_id=None, exploration_id=None)
            await self.publish_state()

    async def flush(self):
        for name, reason, severity, fields in self.navigator.drain_records():
            self.event(name, reason, severity=severity, **fields)
        for subject, payload in self.navigator.drain():
            await self.publish_json(subject, payload)

    async def publish_periodic_state(self):
        if self.navigator.active() or time.monotonic() - self.state_at >= self.IDLE_STATE_INTERVAL:
            await self.publish_state()

    async def publish_state(self):
        self.state_at = time.monotonic()
        state = self.navigator.state(time.monotonic())
        state["map"] = {"source": self.map.kind, "build_ms": self.map_ms, "ready": self.navigator.costmap is not None, "map_id": self.map_id}
        if state.get("trip_id") is not None:
            state["exploration_id"] = self.exploration_id
        await self.publish_json(STATE_SUBJECT, state)

    def load_places(self) -> dict[str, dict]:
        try:
            return json.loads(PLACES_FILE.read_text())
        except FileNotFoundError:
            return {}
        except Exception:
            self.logger.exception("Could not read the saved places")
            return {}

    def save_places(self):
        PLACES_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = PLACES_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.places, indent=2))
        temporary.replace(PLACES_FILE)

    def place_list(self) -> list[dict]:
        return [{"name": name, **place, "current_map": not place.get("map_id") or not self.map_id or place["map_id"] == self.map_id} for name, place in sorted(self.places.items())]

    async def on_places(self, msg: Msg):
        await self.reply(msg, {"ok": True, "places": self.place_list()})

    async def on_place_save(self, msg: Msg):
        request = json.loads(msg.data or b"{}")
        name = str(request.get("name", "")).strip().lower()
        if not name:
            await self.reply(msg, {"ok": False, "error": "a place needs a name"})
            return
        if self.unsettled():
            await self.reply(msg, {"ok": False, "error": f"the camera is still finding itself in the map ({self.camera_state()})"})
            return
        if "x" in request and "z" in request:
            place = {"x": float(request["x"]), "z": float(request["z"]), "heading_deg": request.get("heading_deg")}
        elif self.pose is not None and time.monotonic() - self.pose_at <= self.POSE_FRESH and self.navigator.robot is not None:
            forward = forward_of(self.pose["orientation"])
            place = {
                "x": round(float(self.pose["translation"][0]), 3),
                "z": round(float(self.pose["translation"][2]), 3),
                "heading_deg": round(theta_to_heading(math.atan2(forward[1], forward[0])), 1),
            }
        else:
            await self.reply(msg, {"ok": False, "error": "no fresh pose to save"})
            return
        place.update({"map_id": self.map_id, "saved_at": time.time()})
        self.places[name] = place
        self.save_places()
        self.event("planner.place_saved", name, message=f"Saved place {name}", place=name, x=place["x"], z=place["z"], heading_deg=place.get("heading_deg"))
        await self.reply(msg, {"ok": True, "place": {"name": name, **place}})

    async def on_place_delete(self, msg: Msg):
        name = str(json.loads(msg.data or b"{}").get("name", "")).strip().lower()
        removed = self.places.pop(name, None)
        if removed is not None:
            self.save_places()
            self.event("planner.place_deleted", name, place=name)
        await self.reply(msg, {"ok": removed is not None, "error": None if removed else f"unknown place {name!r}"})

    async def close(self):
        if self.navigator.active():
            self.navigator.cancel("planner shutting down", time.monotonic())
            self.navigator.send(CANCEL_SUBJECT, {"source": "planner-shutdown"})
            await self.flush()


if __name__ == "__main__":
    Node().run_node()

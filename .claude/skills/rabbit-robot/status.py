import asyncio
import json

import nats

SUBJECTS = (
    "rabbit.zed.pose",
    "rabbit.zed.obstacle",
    "rabbit.nav.state",
    "rabbit.explore.state",
    "rabbit.health.zed",
    "rabbit.ina",
    "rabbit.roboclaw",
    "rabbit.steering",
    "rabbit.telemetry",
)


async def main():
    nc = await nats.connect("nats://192.168.1.53:4222", connect_timeout=5, max_reconnect_attempts=0)
    latest: dict[str, dict] = {}
    counts: dict[str, int] = {}

    async def collect(msg):
        counts[msg.subject] = counts.get(msg.subject, 0) + 1
        try:
            latest[msg.subject] = json.loads(msg.data)
        except ValueError:
            pass

    for subject in SUBJECTS:
        await nc.subscribe(subject, cb=collect)
    await asyncio.sleep(3)
    await nc.close()

    print("rates/s", {subject.removeprefix("rabbit."): round(counts.get(subject, 0) / 3, 1) for subject in SUBJECTS})
    pose = latest.get("rabbit.zed.pose", {})
    print("pose", pose.get("translation"), "euler", pose.get("euler_deg"), "confidence", pose.get("confidence"))
    obstacle = latest.get("rabbit.zed.obstacle", {})
    scan = obstacle.get("scan", {})
    print("obstacle nearest", obstacle.get("nearest"), "| ahead", obstacle.get("ahead"), "| blind", scan.get("blind"))
    nav = latest.get("rabbit.nav.state", {})
    print("nav", {key: nav.get(key) for key in ("mode", "fault", "free_distance", "mission_id", "speed", "steer")})
    explore = latest.get("rabbit.explore.state", {})
    print("explore", {key: explore.get(key) for key in ("phase", "message", "travelled_m", "frontiers")})
    health = latest.get("rabbit.health.zed", {})
    print(
        "zed",
        {
            key: health.get(key)
            for key in (
                "current_fps",
                "spatial_memory_status",
                "odometry_status",
                "mapping_state",
                "map_chunks",
                "floor_y",
                "frames_dropped",
                "corrupted_frames",
                "dropped_publishes",
            )
        },
    )
    ina = latest.get("rabbit.ina", {})
    print("power", {key: value for key, value in ina.items() if key != "channels"}, ina.get("channels"))
    roboclaw = latest.get("rabbit.roboclaw", {})
    print("roboclaw", {key: roboclaw.get(key) for key in ("supply_voltage", "temperature", "status", "port", "errors")})
    print("steering", latest.get("rabbit.steering"))
    wifi = latest.get("rabbit.telemetry", {}).get("wifi")
    print("wifi", wifi)


asyncio.run(main())

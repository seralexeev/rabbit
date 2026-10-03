import argparse
import asyncio
import json
import re
import subprocess
import time

import nats

NATS_URL = "nats://192.168.1.53:4222"
MIN_FPS = 14.0


async def publish(nc, subject: str, payload: dict):
    await nc.publish(subject, json.dumps(payload).encode())
    await nc.flush()


def recording_stats(since: str) -> tuple[float, str] | None:
    logs = subprocess.run(
        ["ssh", "rabbit", f"docker logs --since {since} rabbit-zed 2>&1 | grep 'Recording stopped' | tail -1"],
        capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    match = re.search(r"\(([\d.]+) fps\)", logs)
    return (float(match.group(1)), logs) if match else None


async def record(name: str, seconds: float, wake: bool):
    nc = await nats.connect(NATS_URL)
    started = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    try:
        await publish(nc, "rabbit.zed.record", {"name": name})
        print(f"recording {name} for {seconds:.0f} s", flush=True)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if wake:
                await publish(nc, "rabbit.zed.wake", {"seconds": 30, "source": "record_session"})
            await asyncio.sleep(min(10.0, max(0.0, deadline - time.monotonic())))
    finally:
        await publish(nc, "rabbit.zed.record", {})
        await nc.close()
    await asyncio.sleep(2)
    stats = recording_stats(started)
    if stats is None:
        print("no 'Recording stopped' line found; check rabbit-zed logs")
        return False
    fps, line = stats
    print(line)
    if fps < MIN_FPS:
        print(f"TOO SLOW: {fps:.1f} fps < {MIN_FPS:.0f}; re-record (close the HUD video, keep the robot still or slow)")
        return False
    print(f"ok: {fps:.1f} fps")
    return True


def main():
    parser = argparse.ArgumentParser(description="Record an SVO2 session on the robot and check its frame rate")
    parser.add_argument("name", help="file name without extension, e.g. wake-m3-1")
    parser.add_argument("seconds", type=float, nargs="?", default=60.0)
    parser.add_argument("--no-wake", action="store_true", help="don't keep the camera at full rate")
    args = parser.parse_args()
    ok = asyncio.run(record(args.name, args.seconds, not args.no_wake))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

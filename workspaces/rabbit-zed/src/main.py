import zlib
import asyncio
import json

import cv2
import nats
import numpy as np
import pyzed.sl as sl
from zed import ZedCamera


async def main():
    nc = await nats.connect(
        "nats://nats:4222",
        name="rabbit-zed",
        ping_interval=5,
        max_reconnect_attempts=-1,
        reconnect_time_wait=2,
    )

    zed = ZedCamera()
    zed.open()
    frame = 0

    while True:
        try:
            frame_rgb = zed.capture_frame()
            success, buffer = cv2.imencode(
                ".jpg", frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 75]
            )

            if not success:
                raise RuntimeError("Failed to encode image")

            await nc.publish(
                "rabbit.camera.frame",
                buffer.tobytes(),
                headers={
                    "type": "image/jpg",
                    "width": str(frame_rgb.shape[1]),
                    "height": str(frame_rgb.shape[0]),
                },
            )

            imu, other = zed.get_sensors_data()

            await nc.publish(
                "rabbit.camera.imu",
                json.dumps(imu).encode(),
                headers={
                    "type": "application/json",
                },
            )

            arr = zed.retrieve_measure().get_data()
            compressed = zlib.compress(arr.tobytes(), level=6)

            await nc.publish(
                "rabbit.camera.point_cloud",
                compressed,
                headers={
                    "type": "application/json",
                    "shape": json.dumps(arr.shape),
                },
            )

            if frame % 30 == 0:
                await nc.publish(
                    "rabbit.camera.sensor",
                    json.dumps(other).encode(),
                    headers={
                        "type": "application/json",
                    },
                )

            frame += 1
            await nc.flush()

        except KeyboardInterrupt:
            print("Exiting...")
            break

    zed.close()
    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import cv2
import nats


async def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    nc = await nats.connect(
        "nats://localhost:4222",
        name="rabbit-camera",
        ping_interval=5,
        max_reconnect_attempts=-1,
        reconnect_time_wait=2,
    )

    while True:
        try:
            if not cap.isOpened():
                raise RuntimeError("Camera is not opened")

            if not nc:
                raise RuntimeError("NATS connection is not established")

            ret, frame = cap.read()
            if not ret:
                raise RuntimeError("Failed to capture image from camera")

            success, webp_buffer = cv2.imencode(
                ".webp", frame, [cv2.IMWRITE_WEBP_QUALITY, 50]
            )
            if not success:
                raise RuntimeError("Failed to encode image")

            await nc.publish("rabbit.camera.image.webp", webp_buffer.tobytes())
            await nc.flush()
        except RuntimeError as e:
            print(f"Something went wrong: {e}")
            await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
            break

    cap.release()
    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())

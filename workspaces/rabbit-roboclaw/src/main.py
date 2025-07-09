import asyncio
import json
import nats
from roboclaw import RoboClaw


async def main():
    nc = await nats.connect(
        "nats://nats:4222",
        name="rabbit-roboclaw",
        ping_interval=5,
        max_reconnect_attempts=-1,
        reconnect_time_wait=2,
    )

    with RoboClaw("/dev/ttyTHS1", 115200, 0x80) as rc:

        async def publish_metrics():
            try:
                for row in rc.get_metrics():
                    await nc.publish(
                        "rabbit.metrics",
                        json.dumps(row).encode(),
                    )
                    print(f"Published metrics: {row}")
            except Exception as e:
                print(f"Failed to publish metrics: {e}")
            await asyncio.sleep(1)

        metrics_task = asyncio.create_task(publish_metrics())

        while True:
            try:
                rc.move(0.2, 0.1)
            except Exception as e:
                print(f"Something went wrong: {e}")
                await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("Exiting...")
                break
            finally:
                metrics_task.cancel()

    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())

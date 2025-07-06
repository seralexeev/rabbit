import asyncio
import nats


async def main():
    nc = await nats.connect(
        "nats://localhost:4222",
        name="rabbit-roboclaw",
        ping_interval=5,
        max_reconnect_attempts=-1,
        reconnect_time_wait=2,
    )

    while True:
        try:
            if not nc:
                raise RuntimeError("NATS connection is not established")

            await nc.publish("rabbit.sensor", b"roboclaw")
            await nc.flush()
        except RuntimeError as e:
            print(f"Something went wrong: {e}")
            await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
            break

    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())

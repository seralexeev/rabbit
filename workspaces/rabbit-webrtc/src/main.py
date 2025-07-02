import asyncio
import json
import os
from webrtc import WebRTCClient
from ros2_publisher import ROS2Publisher


class RobotClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.client = WebRTCClient(
            ws_url=self.ws_url, on_message=self.handle_controller_message
        )

        self.ros2_publisher = ROS2Publisher()
        self.ros2_publisher.initialize()

    async def connect(self):
        await self.client.connect()

    async def cleanup(self):
        await self.client.cleanup()

        # Очистка ROS2 ресурсов
        if self.ros2_publisher:
            self.ros2_publisher.cleanup()

    def handle_controller_message(self, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "joy/STATE":
                controller_data = data.get("data", {})
                if not controller_data:
                    print("Invalid controller data received")
                    return

                if self.ros2_publisher.initialized:
                    self.ros2_publisher.publish_message("hello")

            else:
                print("Received message type", {msg_type})

        except Exception as e:
            print("Controller message handling error", e)


async def main():
    ws_url = os.environ.get("RABBIT_WS_URL")
    if ws_url is None:
        raise ValueError("RABBIT_WS_URL environment variable is not set")

    while True:
        client = RobotClient(ws_url=ws_url)

        try:
            await client.connect()
        except KeyboardInterrupt:
            print("Stop signal received...")
            await client.cleanup()
            break
        except Exception as e:
            print("Connection error", e)
            await client.cleanup()
            print("Reconnecting in 3 seconds...")
            await asyncio.sleep(3)
            continue


if __name__ == "__main__":
    print("Starting robot client...")
    asyncio.run(main())

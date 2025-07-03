import asyncio
import os

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import Header
from webrtc import WebRTCClient


class RabbitWebRTCNode(Node):
    def __init__(self, ws_url):
        super().__init__("rabbit_webrtc_node")

        self.get_logger().info("Initializing RabbitWebRTCNode...")
        self.ws_url = ws_url
        self.webrtc = WebRTCClient(ws_url=self.ws_url, on_message=self.on_message)
        self.joy_publisher = self.create_publisher(Joy, "/joy", 10)
        self.get_logger().info("RabbitWebRTCNode initialized successfully.")

    async def connect(self):
        self.get_logger().info("Connecting to webrtc server...")
        await self.webrtc.connect()
        self.get_logger().info("Connected to webrtc server.")

    async def cleanup(self):
        self.get_logger().info("Cleaning up RabbitWebRTCNode...")
        await self.webrtc.cleanup()
        self.destroy_node()

    def on_message(self, message):
        type = message.get("type", "")
        if type == "joy/STATE":
            self.handle_controller_message(message)

    def handle_controller_message(self, message):
        data = message["data"]

        joy_msg = Joy()
        joy_msg.header = Header()
        joy_msg.header.stamp = self.get_clock().now().to_msg()
        joy_msg.header.frame_id = "gamepad"

        buttons = data.get("buttons", {})
        joy_msg.buttons = [
            1 if buttons.get("cross", {}).get("pressed", False) else 0,
            1 if buttons.get("circle", {}).get("pressed", False) else 0,
            1 if buttons.get("square", {}).get("pressed", False) else 0,
            1 if buttons.get("triangle", {}).get("pressed", False) else 0,
            1 if buttons.get("l1", {}).get("pressed", False) else 0,
            1 if buttons.get("r1", {}).get("pressed", False) else 0,
            1 if buttons.get("l2", {}).get("pressed", False) else 0,
            1 if buttons.get("r2", {}).get("pressed", False) else 0,
            1 if buttons.get("share", {}).get("pressed", False) else 0,
            1 if buttons.get("options", {}).get("pressed", False) else 0,
            1 if buttons.get("l3", {}).get("pressed", False) else 0,
            1 if buttons.get("r3", {}).get("pressed", False) else 0,
            1 if buttons.get("up", {}).get("pressed", False) else 0,
            1 if buttons.get("down", {}).get("pressed", False) else 0,
            1 if buttons.get("left", {}).get("pressed", False) else 0,
            1 if buttons.get("right", {}).get("pressed", False) else 0,
        ]

        sticks = data.get("sticks", {})
        left_stick = sticks.get("left", {})
        right_stick = sticks.get("right", {})

        joy_msg.axes = [
            left_stick.get("x", 0.0),
            left_stick.get("y", 0.0),
            right_stick.get("x", 0.0),
            right_stick.get("y", 0.0),
            buttons.get("l2", {}).get("value", 0.0),
            buttons.get("r2", {}).get("value", 0.0),
        ]

        self.joy_publisher.publish(joy_msg)


async def main():
    ws_url = os.environ.get("RABBIT_WS_URL")
    if ws_url is None:
        raise ValueError("RABBIT_WS_URL environment variable is not set")

    rclpy.init()

    while True:
        client = RabbitWebRTCNode(ws_url=ws_url)

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

    rclpy.shutdown()


if __name__ == "__main__":
    print("Starting rabbit client...")
    asyncio.run(main())

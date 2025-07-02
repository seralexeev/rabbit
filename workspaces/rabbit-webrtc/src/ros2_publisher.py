import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class ROS2Publisher:
    def __init__(self):
        self.node = None
        self.publisher = None
        self.initialized = False

    def initialize(self):
        try:
            rclpy.init()
            self.node = Node("rabbit_webrtc_node")
            self.publisher = self.node.create_publisher(String, "/rabbit/joy", 10)
            self.initialized = True
            print("ROS2 publisher initialized successfully")
        except Exception as e:
            print(f"Failed to initialize ROS2 publisher: {e}")
            self.initialized = False

    def publish_message(self, message: str):
        if not self.initialized:
            print("ROS2 publisher not initialized")
            return

        try:
            msg = String()
            msg.data = message
            self.publisher.publish(msg)
            print(f"Published to ROS2 topic: {message}")
        except Exception as e:
            print(f"Failed to publish message: {e}")

    def cleanup(self):
        if self.node:
            try:
                self.node.destroy_node()
            except Exception as e:
                print(f"Error destroying node: {e}")

        try:
            rclpy.shutdown()
        except Exception as e:
            print(f"Error shutting down ROS2: {e}")

        self.initialized = False
        print("ROS2 publisher cleaned up")

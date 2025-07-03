import os
import random

import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from rabbit_interface.msg import SensorReading


class RabbitPowerNode(Node):
    def __init__(self):
        super().__init__("rabbit_power_node")

        self.get_logger().info("Initializing node")
        self.power_publisher = self.create_publisher(SensorReading, "/power_sensor", 10)

        self.timer = self.create_timer(1.0, self.publish_power_sensor_data)
        self.get_logger().info("Node initialized successfully")

    def publish_power_sensor_data(self):
        msg = SensorReading()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "power_sensor"

        msg.sensor_name = "motor_sensor"
        msg.value = random.uniform(0.0, 100.0)

        self.power_publisher.publish(msg)
        self.get_logger().info(
            f"Published power sensor data: {msg.sensor_name} = {msg.value:.2f}"
        )

    def cleanup(self):
        self.get_logger().info("Cleaning up")
        if hasattr(self, "timer"):
            self.timer.cancel()
        self.destroy_node()
        self.get_logger().info("Cleanup completed")


def main():
    rclpy.init()
    node = None

    try:
        node = RabbitPowerNode()
        rclpy.spin(node)

    except KeyboardInterrupt:
        print("Stop signal received...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if node is not None:
            node.cleanup()

    rclpy.shutdown()


if __name__ == "__main__":
    print("Starting rabbit power node...")
    main()

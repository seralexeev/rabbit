#!/usr/bin/env python3
import random

import rclpy
from rabbit_interfaces.msg import SensorReading
from rclpy.node import Node
from std_msgs.msg import Header


class PowerSensorNode(Node):
    def __init__(self):
        super().__init__("power_sensor")
        self.power_publisher = self.create_publisher(SensorReading, "/power_sensor", 10)
        self.timer = self.create_timer(1.0, self.timer_callback)

    def timer_callback(self):
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


def main():
    rclpy.init()
    node = PowerSensorNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()

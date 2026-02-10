#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import time

class ToggleLimb(Node):
    def __init__(self):
        super().__init__('toggle_limb')
        self.pub = self.create_publisher(String, 'servo_cmd', 10)

        time.sleep(2)  # let Wi-Fi / bridge settle

        for _ in range(5):
            self.send(0, 0)
            time.sleep(0.5)

            self.send(180, 180)
            time.sleep(0.5)

        self.get_logger().info("Done")
        rclpy.shutdown()

    def send(self, a1, a2):
        msg = String()
        msg.data = f"{a1},{a2}"
        self.pub.publish(msg)

def main():
    rclpy.init()
    ToggleLimb()

if __name__ == '__main__':
    main()

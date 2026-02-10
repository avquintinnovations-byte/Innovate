#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import serial
import time

SERIAL_PORT = '/dev/ttyUSB0'   # change if needed
BAUDRATE = 115200

class ServoBridge(Node):
    def __init__(self):
        super().__init__('servo_bridge')

        self.ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.1)
        time.sleep(2)  # let ESP32 reset

        self.create_subscription(
            String,
            'servo_cmd',
            self.cmd_callback,
            10
        )

        self.get_logger().info('Servo bridge ready')
        self.get_logger().info("Send commands like: '1:90'")

    def cmd_callback(self, msg):
        cmd = msg.data.strip()
        if not cmd:
            return
        self.ser.write((cmd + '\n').encode())
        self.get_logger().info(f"Sent -> {cmd}")

def main():
    rclpy.init()
    node = ServoBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.ser.close()
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()

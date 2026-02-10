#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import socket

ESP_IP = "192.168.1.70"   # <-- ESP32 IP from serial output
ESP_PORT = 9000

class WifiServoBridge(Node):
    def __init__(self):
        super().__init__('wifi_servo_bridge')

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((ESP_IP, ESP_PORT))

        self.create_subscription(
            String,
            'servo_cmd',
            self.cb,
            10
        )

        self.get_logger().info("Wi-Fi servo bridge connected")

    def cb(self, msg):
        cmd = msg.data.strip()
        if not cmd:
            return
        self.sock.sendall((cmd + '\n').encode())
        self.get_logger().info(f"Sent -> {cmd}")

def main():
    rclpy.init()
    node = WifiServoBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.sock.close()
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()

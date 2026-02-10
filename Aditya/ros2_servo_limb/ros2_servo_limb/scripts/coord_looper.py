import rclpy
from rclpy.node import Node
from std_msgs.msg import String

class SimpleLoop(Node):
    def __init__(self):
        super().__init__('simple_loop')
        self.publisher_ = self.create_publisher(String, 'target_coord', 10)
        
        # Publish every 1.5 seconds so you have time to see the movement
        self.timer = self.create_timer(1.5, self.send_next_coord)
        
        # List of coordinates to cycle through
        self.targets = [
            (0, 70), 
            (0, 100), 
            (0, 70),
            (-50, 70),
            (0, 70),
            (50, 70),
        ]
        self.index = 0

    def send_next_coord(self):
        # Get current x, y
        x, y = self.targets[self.index]
        
        # Format and publish
        msg = String()
        msg.data = f"{x},{y}"
        self.publisher_.publish(msg)
        
        self.get_logger().info(f'Sent Target: {msg.data}')
        
        # Update index (wrap around to 0 when we reach the end)
        self.index = (self.index + 1) % len(self.targets)

def main(args=None):
    rclpy.init(args=args)
    node = SimpleLoop()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()

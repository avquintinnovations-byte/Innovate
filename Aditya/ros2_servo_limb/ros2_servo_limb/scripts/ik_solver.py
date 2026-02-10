import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import math

# --- Custom Dimensions (mm) ---
L1 = 55.0  # Hip to Knee
L2 = 53.0  # Knee to End

class IKSubscriber(Node):
    def __init__(self):
        super().__init__('ik_subscriber')
        
        self.subscription = self.create_subscription(
            String, 'target_coord', self.listener_callback, 10
        )
        self.publisher_ = self.create_publisher(String, 'servo_cmd', 10)
        
        self.get_logger().info(f"IK Ready (Int Output). L1={L1}, L2={L2}")

    def listener_callback(self, msg):
        try:
            parts = msg.data.split(',')
            x = float(parts[0])
            y = float(parts[1])
            
            # --- 1. Math Safety & Reach ---
            dist = math.sqrt(x**2 + y**2)
            
            # Clamp distance to physical limits
            # Max reach: sum of legs
            dist = min(dist, L1 + L2 - 0.1)
            # Min reach: difference of legs (cannot fold closer than this)
            dist = max(dist, abs(L1 - L2) + 0.1)

            # --- 2. Inverse Kinematics Math ---
            
            # Knee Angle (Gamma) via Law of Cosines
            # c^2 = a^2 + b^2 - 2ab*cos(C)
            num_gamma = (L1**2 + L2**2 - dist**2)
            den_gamma = (2 * L1 * L2)
            gamma_deg = math.degrees(math.acos(num_gamma / den_gamma))
            
            # Map Internal Angle to Servo (Visualizer logic)
            # 180 is straight, 90 is bent. 
            # Note: This mapping depends on your specific servo assembly zero-point.
            raw_knee = 90 - (180 - gamma_deg)

            # Hip Angle (Theta - Beta)
            theta_rad = math.atan2(y, x)
            
            # Beta via Law of Cosines
            num_beta = (L1**2 + dist**2 - L2**2)
            den_beta = (2 * L1 * dist)
            beta_rad = math.acos(num_beta / den_beta)
            
            thigh_deg = math.degrees(theta_rad - beta_rad)
            
            # Map to Servo (Visualizer logic: 0=-x, 180=+x)
            raw_hip = 180 - thigh_deg

            # --- 3. Formatting & Publishing ---
            
            # Clamp to 0-180 range
            final_hip = max(0, min(180, int(round(raw_hip))))
            final_knee = max(0, min(180, int(round(raw_knee))))

            cmd_str = f"{final_hip},{final_knee}"
            self.publisher_.publish(String(data=cmd_str))
            
        except Exception as e:
            self.get_logger().error(f"IK Error: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = IKSubscriber()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
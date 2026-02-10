import pygame
import math
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# --- Constants ---
WIDTH, HEIGHT = 800, 600
WHITE = (255, 255, 255)
BLACK = (20, 20, 20)
RED = (255, 50, 50)
GREEN = (50, 255, 50)
BLUE = (50, 100, 255)
GRAY = (100, 100, 100)

# Physical properties
ORIGIN = (WIDTH // 2, 100)
LINK_LENGTH = 150
JOINT_RADIUS = 8

# Smoothing Factor (0.0 to 1.0)
# 0.05 = Very slow/smooth, 0.5 = Fast/Snappy
SMOOTH_SPEED = 0.1

class ServoListener(Node):
    def __init__(self):
        super().__init__('servo_visualizer')
        
        self.subscription = self.create_subscription(
            String,
            'servo_cmd',
            self.listener_callback,
            10
        )
        
        # We now have TWO sets of angles:
        # 1. Target: The latest command received from ROS (Where we want to go)
        # 2. Current: Where the drawing actually is right now (Where we are)
        self.target_angles = [90.0, 90.0] 
        self.current_angles = [90.0, 90.0]
        
        self.get_logger().info("Smoothed Visualizer Started.")

    def listener_callback(self, msg):
        try:
            data = msg.data.split(',')
            if len(data) == 2:
                # We ONLY update the target here. 
                # The main loop handles moving "current" towards "target".
                t_hip = float(data[0])
                t_knee = float(data[1])
                self.target_angles = [t_hip, t_knee]
        except ValueError:
            pass

def calculate_coords(hip_angle_deg, knee_angle_deg):
    """ Calculates joint positions based on angles. """
    # Hip Math
    hip_rad = math.radians(180 - hip_angle_deg)
    knee_x = ORIGIN[0] + LINK_LENGTH * math.cos(hip_rad)
    knee_y = ORIGIN[1] + LINK_LENGTH * math.sin(hip_rad)
    
    # Knee Math
    relative_offset_rad = math.radians(90 - knee_angle_deg)
    foot_global_rad = hip_rad + relative_offset_rad
    foot_x = knee_x + LINK_LENGTH * math.cos(foot_global_rad)
    foot_y = knee_y + LINK_LENGTH * math.sin(foot_global_rad)
    
    return (knee_x, knee_y), (foot_x, foot_y)

def lerp(start, end, factor):
    """ Linear Interpolation function """
    return start + (end - start) * factor

def main(args=None):
    rclpy.init(args=args)
    ros_node = ServoListener()

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("ROS 2 Smooth Visualizer")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 18)

    running = True
    
    while running:
        # --- 1. Pygame Events ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        # --- 2. ROS Events ---
        rclpy.spin_once(ros_node, timeout_sec=0)

        # --- 3. Smoothing Logic (The Magic Part) ---
        # Get where we want to be
        target_h, target_k = ros_node.target_angles
        # Get where we are
        curr_h, curr_k = ros_node.current_angles

        # Smoothly move current towards target
        # If the difference is very small, just snap to target to save CPU math
        if abs(target_h - curr_h) > 0.1:
            curr_h = lerp(curr_h, target_h, SMOOTH_SPEED)
        else:
            curr_h = target_h

        if abs(target_k - curr_k) > 0.1:
            curr_k = lerp(curr_k, target_k, SMOOTH_SPEED)
        else:
            curr_k = target_k

        # Update the node's current state so it remembers for next frame
        ros_node.current_angles = [curr_h, curr_k]

        # --- 4. Calculate Physics ---
        # Draw the "Ghost" target (where the robot WANTS to be) in gray
        # This helps visualize lag or smoothing delay
        g_knee, g_foot = calculate_coords(target_h, target_k)
        
        # Draw the Actual smoothed position
        knee_pos, foot_pos = calculate_coords(curr_h, curr_k)

        # --- 5. Draw ---
        screen.fill(BLACK)

        # Optional: Draw Ghost Target (faint gray lines)
        pygame.draw.line(screen, (50, 50, 50), ORIGIN, g_knee, 2)
        pygame.draw.line(screen, (50, 50, 50), g_knee, g_foot, 2)

        # Draw Actual Leg
        pygame.draw.circle(screen, WHITE, ORIGIN, JOINT_RADIUS)

        pygame.draw.line(screen, BLUE, ORIGIN, knee_pos, 6)
        pygame.draw.circle(screen, RED, (int(knee_pos[0]), int(knee_pos[1])), JOINT_RADIUS)

        pygame.draw.line(screen, GREEN, knee_pos, foot_pos, 6)
        pygame.draw.circle(screen, RED, (int(foot_pos[0]), int(foot_pos[1])), JOINT_RADIUS)

        # UI
        text_target = font.render(f"Target: {int(target_h)}, {int(target_k)}", True, GRAY)
        text_actual = font.render(f"Actual: {int(curr_h)}, {int(curr_k)}", True, WHITE)
        
        screen.blit(text_target, (20, 20))
        screen.blit(text_actual, (20, 45))

        pygame.display.flip()
        clock.tick(60)

    ros_node.destroy_node()
    rclpy.shutdown()
    pygame.quit()

if __name__ == "__main__":
    main()
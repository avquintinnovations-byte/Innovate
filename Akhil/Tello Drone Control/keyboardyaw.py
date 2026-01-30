from djitellopy import Tello
import pygame
import time
import cv2

# ----------------------------
# Window
# ----------------------------
WIDTH = 960
HEIGHT = 720

# ----------------------------
# Setpoint control
# ----------------------------
TARGET_STEP = 5.0   # deg per key press (directional)

# ----------------------------
# PID settings
# ----------------------------
KP = 1.0
KI = 0.0
KD = 0.4

MAX_SPEED = 80
MIN_SPEED = 12
DEADBAND = 1.0

YAW_FILTER_ALPHA = 0.25
CMD_SMOOTHING = 0.35
MAX_CMD_STEP = 6

INTEGRAL_LIMIT = 120


# ----------------------------
# Angle unwrap helper
# ----------------------------
def unwrap_angle(prev, current):
    delta = current - prev
    if delta > 180:
        current -= 360
    elif delta < -180:
        current += 360
    return current


# ----------------------------
# Setpoint interface (future IMU)
# ----------------------------
def get_target_yaw_from_source(target_yaw):
    """
    Currently: keyboard driven (continuous)
    Future: replace with ESP32 IMU yaw (also continuous)
    """
    return target_yaw


def main():
    global KP, KI, KD

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Tello Continuous Yaw PID (360°)")

    font = pygame.font.SysFont(None, 26)
    clock = pygame.time.Clock()

    # ----------------------------
    # Tello setup
    # ----------------------------
    tello = Tello()
    tello.connect()
    print("Battery:", tello.get_battery(), "%")

    tello.streamoff()
    tello.streamon()
    frame_read = tello.get_frame_read()

    tello.takeoff()
    time.sleep(2)

    # ----------------------------
    # Initial yaw references
    # ----------------------------
    raw_yaw = tello.get_yaw()
    prev_raw_yaw = raw_yaw
    unwrapped_yaw = raw_yaw

    filtered_yaw = unwrapped_yaw
    target_yaw = unwrapped_yaw   # start tracking current heading

    prev_error = 0.0
    prev_time = time.time()
    integral = 0.0
    last_cmd = 0.0

    running = True
    while running:
        clock.tick(40)

        # ----------------------------
        # Events
        # ----------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                # PID tuning
                elif event.key == pygame.K_q:
                    KP += 0.05
                elif event.key == pygame.K_a:
                    KP = max(0, KP - 0.05)

                elif event.key == pygame.K_w:
                    KD += 0.02
                elif event.key == pygame.K_s:
                    KD = max(0, KD - 0.02)

                elif event.key == pygame.K_e:
                    KI += 0.002
                elif event.key == pygame.K_d:
                    KI = max(0, KI - 0.002)

                elif event.key == pygame.K_r:
                    integral = 0.0

                # Continuous target yaw (direction preserved)
                elif event.key == pygame.K_UP:
                    target_yaw += TARGET_STEP

                elif event.key == pygame.K_DOWN:
                    target_yaw -= TARGET_STEP

        # ----------------------------
        # Target yaw interface
        # ----------------------------
        target_yaw = get_target_yaw_from_source(target_yaw)

        # ----------------------------
        # Yaw feedback (unwrap)
        # ----------------------------
        raw_yaw = tello.get_yaw()
        raw_yaw = unwrap_angle(prev_raw_yaw, raw_yaw)
        prev_raw_yaw = raw_yaw

        unwrapped_yaw = raw_yaw

        filtered_yaw = (
            (1 - YAW_FILTER_ALPHA) * filtered_yaw
            + YAW_FILTER_ALPHA * unwrapped_yaw
        )

        error = target_yaw - filtered_yaw

        # ----------------------------
        # Timing
        # ----------------------------
        now = time.time()
        dt = max(0.001, now - prev_time)
        prev_time = now

        # ----------------------------
        # PID
        # ----------------------------
        derivative = (error - prev_error) / dt
        prev_error = error

        integral += error * dt
        integral = max(-INTEGRAL_LIMIT, min(INTEGRAL_LIMIT, integral))

        cmd = KP * error + KD * derivative + KI * integral

        if abs(error) < DEADBAND:
            cmd = 0
            integral *= 0.9

        cmd = max(-MAX_SPEED, min(MAX_SPEED, cmd))

        if cmd > 0:
            cmd = max(MIN_SPEED, cmd)
        elif cmd < 0:
            cmd = min(-MIN_SPEED, cmd)

        if cmd > last_cmd + MAX_CMD_STEP:
            cmd = last_cmd + MAX_CMD_STEP
        elif cmd < last_cmd - MAX_CMD_STEP:
            cmd = last_cmd - MAX_CMD_STEP

        cmd = (1 - CMD_SMOOTHING) * last_cmd + CMD_SMOOTHING * cmd
        last_cmd = cmd

        tello.send_rc_control(0, 0, 0, int(cmd))

        # ----------------------------
        # Video
        # ----------------------------
        frame = frame_read.frame
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        frame = pygame.surfarray.make_surface(frame.swapaxes(0, 1))
        screen.blit(frame, (0, 0))

        # ----------------------------
        # Overlay
        # ----------------------------
        info = [
            f"Battery      : {tello.get_battery()}%",
            f"Target yaw   : {target_yaw:7.1f} deg",
            f"Drone yaw    : {filtered_yaw:7.1f} deg",
            f"Error        : {error:7.1f}",
            f"Yaw command  : {int(cmd)}",
            "",
            f"Kp: {KP:.3f} (Q/A)",
            f"Kd: {KD:.3f} (W/S)",
            f"Ki: {KI:.4f} (E/D)",
            "UP/DOWN = rotate target (continuous)",
            "ESC = land & exit"
        ]

        y = 20
        for line in info:
            txt = font.render(line, True, (255, 255, 255))
            screen.blit(txt, (20, y))
            y += 26

        pygame.display.flip()

    # ----------------------------
    # Cleanup
    # ----------------------------
    tello.send_rc_control(0, 0, 0, 0)
    tello.land()
    tello.streamoff()
    tello.end()
    pygame.quit()


if __name__ == "__main__":
    main()

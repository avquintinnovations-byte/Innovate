from djitellopy import Tello
import pygame
import time
import cv2
import numpy as np

# ----------------------------
# Window
# ----------------------------
WIDTH = 960
HEIGHT = 720

# ----------------------------
# Control settings
# ----------------------------
MAX_YAW = 90

KP = 1.0
KI = 0.0
KD = 0.4

MAX_SPEED = 80
MIN_SPEED = 12
DEADBAND = 1.2

YAW_FILTER_ALPHA = 0.25
CMD_SMOOTHING = 0.35
MAX_CMD_STEP = 6

INTEGRAL_LIMIT = 100


def angle_diff(target, current):
    d = target - current
    while d > 180:
        d -= 360
    while d < -180:
        d += 360
    return d


def main():
    global KP, KI, KD

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Tello PID Yaw Control + Video")

    font = pygame.font.SysFont(None, 28)

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
    # Controller state
    # ----------------------------
    clock = pygame.time.Clock()

    prev_error = 0
    prev_time = time.time()
    filtered_yaw = tello.get_yaw()
    last_cmd = 0
    integral = 0

    running = True
    while running:
        clock.tick(40)  # 40 Hz loop

        # ----------------------------
        # Events
        # ----------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

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
                    integral = 0

        # ----------------------------
        # Mouse → target yaw
        # ----------------------------
        mouse_x, _ = pygame.mouse.get_pos()
        target_yaw = ((mouse_x / WIDTH) * 2 - 1) * MAX_YAW

        # ----------------------------
        # Yaw feedback
        # ----------------------------
        raw_yaw = tello.get_yaw()
        filtered_yaw = (1 - YAW_FILTER_ALPHA) * filtered_yaw + YAW_FILTER_ALPHA * raw_yaw

        error = angle_diff(target_yaw, filtered_yaw)

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

        # Deadband
        if abs(error) < DEADBAND:
            cmd = 0
            integral *= 0.9

        # Clamp
        cmd = max(-MAX_SPEED, min(MAX_SPEED, cmd))

        # Minimum effective speed
        if cmd > 0:
            cmd = max(MIN_SPEED, cmd)
        elif cmd < 0:
            cmd = min(-MIN_SPEED, cmd)

        # Slew rate
        if cmd > last_cmd + MAX_CMD_STEP:
            cmd = last_cmd + MAX_CMD_STEP
        elif cmd < last_cmd - MAX_CMD_STEP:
            cmd = last_cmd - MAX_CMD_STEP

        # Smooth
        cmd = (1 - CMD_SMOOTHING) * last_cmd + CMD_SMOOTHING * cmd
        last_cmd = cmd

        tello.send_rc_control(0, 0, 0, int(cmd))

        # ----------------------------
        # Video frame
        # ----------------------------
        frame = frame_read.frame
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        #frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Convert directly to pygame surface (no rotation)
        frame = pygame.surfarray.make_surface(frame.swapaxes(0, 1))
        screen.blit(frame, (0, 0))

        # ----------------------------
        # Overlay text
        # ----------------------------
        battery = tello.get_battery()

        info_lines = [
            f"Battery: {battery}%",
            f"Target yaw: {target_yaw:6.1f}",
            f"Drone yaw : {filtered_yaw:6.1f}",
            f"Error     : {error:6.1f}",
            f"Cmd       : {int(cmd)}",
            "",
            f"Kp: {KP:.3f} (Q/A)",
            f"Kd: {KD:.3f} (W/S)",
            f"Ki: {KI:.4f} (E/D)",
            "R = reset I   ESC = exit"
        ]

        y = 20
        for line in info_lines:
            txt = font.render(line, True, (255, 255, 255))
            screen.blit(txt, (20, y))
            y += 28

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

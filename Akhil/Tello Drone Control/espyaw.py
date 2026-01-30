from djitellopy import Tello
import pygame
import time
import cv2
import serial

# ----------------------------
# ESP32 serial config
# ----------------------------
ESP_PORT = "COM9"
ESP_BAUD = 115200

# ----------------------------
# Rates (IMPORTANT)
# ----------------------------
CONTROL_HZ = 40
RC_HZ = 20
YAW_HZ = 20

# ----------------------------
# Window
# ----------------------------
WIDTH = 960
HEIGHT = 720

# ----------------------------
# PID
# ----------------------------
KP = 0.6
KI = 0.0
KD = 0.3

MAX_SPEED = 80
MIN_SPEED = 12
DEADBAND = 1.0

CMD_SMOOTHING = 0.3
MAX_CMD_STEP = 6
INTEGRAL_LIMIT = 120

# ----------------------------
# Angle unwrap
# ----------------------------
def unwrap_angle(prev, current):
    d = current - prev
    if d > 180:
        current -= 360
    elif d < -180:
        current += 360
    return current


def main():
    global KP, KI, KD

    # ----------------------------
    # Serial (ESP)
    # ----------------------------
    esp = serial.Serial(ESP_PORT, ESP_BAUD, timeout=0)
    time.sleep(2)
    esp.reset_input_buffer()

    # ----------------------------
    # Pygame
    # ----------------------------
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Tello Real-Time Yaw PID (ESP32)")
    font = pygame.font.SysFont(None, 24)
    clock = pygame.time.Clock()

    # ----------------------------
    # Tello
    # ----------------------------
    tello = Tello()
    tello.connect()
    print("Battery:", tello.get_battery(), "%")

    tello.streamon()
    frame_read = tello.get_frame_read()

    tello.takeoff()
    time.sleep(2)

    # ----------------------------
    # State
    # ----------------------------
    prev_raw_esp = None
    target_yaw = 0.0

    prev_raw_drone = tello.get_yaw()
    drone_yaw = prev_raw_drone

    prev_error = 0.0
    integral = 0.0
    last_cmd = 0.0

    # Timers
    last_rc_time = 0
    last_yaw_time = 0

    running = True
    while running:
        clock.tick(CONTROL_HZ)
        now = time.time()

        # ----------------------------
        # Events
        # ----------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        # ----------------------------
        # ESP yaw (NON-BLOCKING, latest only)
        # ----------------------------
        while esp.in_waiting:
            try:
                line = esp.readline().decode().strip()
                raw = float(line)

                if prev_raw_esp is None:
                    prev_raw_esp = raw
                    target_yaw = raw
                else:
                    raw = unwrap_angle(prev_raw_esp, raw)
                    target_yaw += (raw - prev_raw_esp)
                    prev_raw_esp = raw
            except:
                pass

        # ----------------------------
        # Drone yaw (rate-limited)
        # ----------------------------
        if now - last_yaw_time > 1 / YAW_HZ:
            raw = tello.get_yaw()
            raw = unwrap_angle(prev_raw_drone, raw)
            drone_yaw = raw
            prev_raw_drone = raw
            last_yaw_time = now

        # ----------------------------
        # PID
        # ----------------------------
        error = target_yaw - drone_yaw
        derivative = (error - prev_error) * CONTROL_HZ
        prev_error = error

        integral += error / CONTROL_HZ
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

        # ----------------------------
        # RC command (RATE-LIMITED)
        # ----------------------------
        if now - last_rc_time > 1 / RC_HZ:
            tello.send_rc_control(0, 0, 0, int(cmd))
            last_rc_time = now

        # ----------------------------
        # Video
        # ----------------------------
        frame = frame_read.frame
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        frame = pygame.surfarray.make_surface(frame.swapaxes(0, 1))
        screen.blit(frame, (0, 0))

        info = [
            f"Target yaw : {target_yaw:7.1f}",
            f"Drone yaw  : {drone_yaw:7.1f}",
            f"Error      : {error:7.1f}",
            f"Cmd        : {int(cmd)}",
            "ESC = land"
        ]

        y = 20
        for line in info:
            screen.blit(font.render(line, True, (255, 255, 255)), (20, y))
            y += 24

        pygame.display.flip()

    # ----------------------------
    # Cleanup
    # ----------------------------
    tello.send_rc_control(0, 0, 0, 0)
    tello.land()
    tello.streamoff()
    tello.end()
    esp.close()
    pygame.quit()


if __name__ == "__main__":
    main()

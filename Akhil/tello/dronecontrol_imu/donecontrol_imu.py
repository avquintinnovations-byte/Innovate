from djitellopy import Tello
import serial
import pygame
import time

# ------------------------
# IMU Serial
# ------------------------
IMU_PORT = "COM9"      # change to your port
BAUD = 115200
ser = serial.Serial(IMU_PORT, BAUD, timeout=0.01)

def get_imu_yaw():
    try:
        line = ser.readline().decode().strip()
        if line.startswith("YAW:"):
            return float(line.replace("YAW:", ""))
    except:
        pass
    return None

# ------------------------
# PID Parameters
# ------------------------
KP = 1.2
KI = 0.0
KD = 0.35

MAX_SPEED = 80
MIN_SPEED = 12
DEADBAND = 1.0
INTEGRAL_LIMIT = 100

# ------------------------
def angle_diff(target, current):
    d = target - current
    while d > 180: d -= 360
    while d < -180: d += 360
    return d

# ------------------------
def main():
    global KP, KI, KD

    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    pygame.display.set_caption("IMU Yaw → Tello Control")

    font = pygame.font.SysFont(None, 28)

    tello = Tello()
    tello.connect()
    print("Battery:", tello.get_battery(), "%")

    tello.takeoff()
    time.sleep(2)

    yaw_offset = 0
    target_yaw = 0

    prev_error = 0
    prev_time = time.time()
    integral = 0

    running = True
    while running:
        time.sleep(0.02)  # 50 Hz loop

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                # Press C to set current IMU yaw as center
                if event.key == pygame.K_c:
                    imu = get_imu_yaw()
                    if imu is not None:
                        yaw_offset = imu
                        print("Center set")

        imu_yaw = get_imu_yaw()
        if imu_yaw is None:
            continue

        current_yaw = imu_yaw - yaw_offset
        error = angle_diff(target_yaw, current_yaw)

        now = time.time()
        dt = now - prev_time
        prev_time = now

        derivative = (error - prev_error) / dt if dt > 0 else 0
        prev_error = error

        integral += error * dt
        integral = max(-INTEGRAL_LIMIT, min(INTEGRAL_LIMIT, integral))

        cmd = KP*error + KD*derivative + KI*integral

        if abs(error) < DEADBAND:
            cmd = 0

        cmd = max(-MAX_SPEED, min(MAX_SPEED, cmd))

        if cmd > 0:
            cmd = max(cmd, MIN_SPEED)
        elif cmd < 0:
            cmd = min(cmd, -MIN_SPEED)

        tello.send_rc_control(0, 0, 0, int(cmd))

        # ---------- Display ----------
        screen.fill((30, 30, 30))
        lines = [
            f"IMU Yaw: {imu_yaw:.2f}",
            f"Current: {current_yaw:.2f}",
            f"Error  : {error:.2f}",
            f"Cmd    : {int(cmd)}",
            "",
            "C = set center",
            "ESC = land & exit"
        ]

        y = 20
        for l in lines:
            txt = font.render(l, True, (255,255,255))
            screen.blit(txt, (20, y))
            y += 28

        pygame.display.flip()

    tello.send_rc_control(0,0,0,0)
    tello.land()
    tello.end()
    pygame.quit()

if __name__ == "__main__":
    main()

import cv2
import numpy as np
import pyautogui
from ultralytics import YOLO

# ----------------------------
# SETTINGS
# ----------------------------
MODEL_PATH = "yolo11m-seg-custom.pt"   # <-- change if your model is elsewhere
CAMERA_INDEX = 0
FRAME_W, FRAME_H = 640, 480

# ----------------------------
# Load YOLO model
# ----------------------------
model = YOLO(MODEL_PATH)

# ----------------------------
# Calibration storage
# ----------------------------
calibration = {
    "center": None,
    "left": None,
    "right": None,
    "up": None,
    "down": None
}

calibrated = False

# ----------------------------
# Camera
# ----------------------------
cap = cv2.VideoCapture(CAMERA_INDEX)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

screen_w, screen_h = pyautogui.size()

print("\nCALIBRATION:")
print("Look CENTER press 1")
print("Look LEFT   press 2")
print("Look RIGHT  press 3")
print("Look UP     press 4")
print("Look DOWN   press 5")
print("Press Q to quit\n")

prev_x, prev_y = 0, 0

# ----------------------------
# Main loop
# ----------------------------
while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.resize(frame, (FRAME_W, FRAME_H))

    # Run YOLO prediction
    results = model.predict(frame, device="cpu", imgsz=320, conf=0.4, verbose=False)

    pupil = None

    # If detection exists
    if results[0].boxes and len(results[0].boxes) > 0:
        box = results[0].boxes[0]  # take first detected object

        x1, y1, x2, y2 = map(int, box.xyxy[0])

        # Centroid
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        pupil = (cx, cy)

        # Draw box + center
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)

    # UI text
    cv2.putText(frame, "1:C 2:L 3:R 4:U 5:D  Q:QUIT",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

    cv2.imshow("YOLO Eye Control", frame)

    key = cv2.waitKey(1) & 0xFF

    # ---- Calibration keys ----
    if key == ord('1') and pupil:
        calibration["center"] = pupil
        print("Center:", pupil)

    elif key == ord('2') and pupil:
        calibration["left"] = pupil
        print("Left:", pupil)

    elif key == ord('3') and pupil:
        calibration["right"] = pupil
        print("Right:", pupil)

    elif key == ord('4') and pupil:
        calibration["up"] = pupil
        print("Up:", pupil)

    elif key == ord('5') and pupil:
        calibration["down"] = pupil
        print("Down:", pupil)

    elif key == ord('q'):
        break

    # ---- Enable tracking after calibration ----
    if all(calibration.values()):
        calibrated = True

    # ---- Mouse control using YOLO position ----
    if calibrated and pupil:
        lx, rx = calibration["left"][0], calibration["right"][0]
        uy, dy = calibration["up"][1], calibration["down"][1]

        # Clamp inside calibration region
        x = np.clip(pupil[0], lx, rx)
        y = np.clip(pupil[1], uy, dy)

        # Normalize to screen size
        mouse_x = int((x - lx) / (rx - lx) * screen_w)
        mouse_y = int((y - uy) / (dy - uy) * screen_h)

        # Smooth movement
        smooth = 0.3
        mouse_x = int(prev_x + smooth * (mouse_x - prev_x))
        mouse_y = int(prev_y + smooth * (mouse_y - prev_y))

        pyautogui.moveTo(mouse_x, mouse_y)

        prev_x, prev_y = mouse_x, mouse_y

# ----------------------------
# Cleanup
# ----------------------------
cap.release()
cv2.destroyAllWindows()

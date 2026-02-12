from ultralytics import YOLO
import cv2
import numpy as np

# =========================
# SETTINGS (from marker_test.py)
# =========================
MARKER_SIZE = 100
SCREEN_W = 1920
SCREEN_H = 1080
CAM_INDEX = 2

# Load YOLO model for pupil detection
model = YOLO("best.pt")
cap = cv2.VideoCapture(CAM_INDEX)

if not cap.isOpened():
    print("Camera not opening")
    exit()

# ArUco setup (9 markers: TL=0 TC=5 TR=1 | LC=6 C=4 RC=7 | BL=3 BC=8 BR=2)
aruco = cv2.aruco
dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
markers = {}
for marker_id in range(9):
    img = aruco.generateImageMarker(dictionary, marker_id, MARKER_SIZE)
    markers[marker_id] = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

# 9 marker positions (same layout as marker_test.py)
pad = 10
positions = {
    0: (pad, pad),                                                   # TL
    1: (SCREEN_W - MARKER_SIZE - pad, pad),                          # TR
    2: (SCREEN_W - MARKER_SIZE - pad, SCREEN_H - MARKER_SIZE - pad), # BR
    3: (pad, SCREEN_H - MARKER_SIZE - pad),                          # BL
    4: ((SCREEN_W - MARKER_SIZE) // 2, (SCREEN_H - MARKER_SIZE) // 2),  # center
    5: ((SCREEN_W - MARKER_SIZE) // 2, pad),                         # top-center
    6: (pad, (SCREEN_H - MARKER_SIZE) // 2),                         # left-center
    7: (SCREEN_W - MARKER_SIZE - pad, (SCREEN_H - MARKER_SIZE) // 2),# right-center
    8: ((SCREEN_W - MARKER_SIZE) // 2, SCREEN_H - MARKER_SIZE - pad),# bottom-center
}

# 9-point eye tracking
nine_points = []   # (eye_x, eye_y) for each point 0-8
current_point = 0  # 0-8, which marker is shown

def create_marker_screen(show_marker_id, done=False):
    """Display only one marker at its position (rest of screen white)"""
    screen = np.ones((SCREEN_H, SCREEN_W, 3), dtype=np.uint8) * 255
    if 0 <= show_marker_id < 9:
        x, y = positions[show_marker_id]
        screen[y:y+MARKER_SIZE, x:x+MARKER_SIZE] = markers[show_marker_id]
    if done:
        cv2.putText(screen, "All 9 points recorded. Press R to reset, Q to quit",
                    (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 128, 0), 2)
    else:
        cv2.putText(screen, f"Point {show_marker_id + 1}/9 - Look at marker, press SPACEBAR",
                    (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    return screen

def draw_eye_tracking_frame(frame, nine_points, current_eye_pos=None):
    """Draw 9-point coords on eye tracking window"""
    # Draw each recorded point
    for i, (ex, ey) in enumerate(nine_points):
        color = (0, 255, 0) if i < 4 else (255, 165, 0)
        cv2.circle(frame, (int(ex), int(ey)), 6, color, -1)
        cv2.putText(frame, f"P{i+1}", (int(ex) + 10, int(ey) - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        cv2.putText(frame, f"({int(ex)},{int(ey)})", (int(ex) - 25, int(ey) + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 200, 100), 1)
    # Current eye position
    if current_eye_pos is not None:
        cv2.circle(frame, (int(current_eye_pos[0]), int(current_eye_pos[1])), 10, (255, 0, 255), 3)
    # Instructions
    cv2.putText(frame, "SPACE=record | R=reset | Q=quit", (10, frame.shape[0] - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    # 9-point coords list
    h = frame.shape[0]
    cv2.putText(frame, "9-point coords (eye x,y):", (frame.shape[1] - 200, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    for i, (ex, ey) in enumerate(nine_points):
        yoff = 38 + i * 18
        if yoff < h - 5:
            cv2.putText(frame, f"P{i+1}: ({int(ex)},{int(ey)})", (frame.shape[1] - 195, yoff),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 220, 150), 1)
    return frame

# Windows
cv2.namedWindow("Marker Screen", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("Marker Screen", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
cv2.namedWindow("Pupil Detection", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Pupil Detection", 640, 480)

print("\n=== 9-Point Eye Tracking ===")
print("Marker Screen: shows one marker at a time")
print("Look at the marker, press SPACEBAR to record eye position")
print("Q → Quit\n")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 0)
    results = model.predict(source=frame, device=0, conf=0.8)

    cx, cy = None, None
    for box in results[0].boxes:
        x1, y1, x2, y2 = box.xyxy[0]
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)
        cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)

    annotated_frame = results[0].plot()
    annotated_frame = draw_eye_tracking_frame(
        annotated_frame, nine_points,
        (cx, cy) if cx is not None else None
    )

    done = len(nine_points) >= 9
    marker_screen = create_marker_screen(current_point, done=done)
    cv2.imshow("Marker Screen", marker_screen)
    cv2.imshow("Pupil Detection", annotated_frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('r'):
        nine_points.clear()
        current_point = 0
        print("Reset - start over.")
    elif key == 32 and not done:  # Spacebar
        if cx is not None and cy is not None:
            nine_points.append((float(cx), float(cy)))
            print(f"Point {current_point + 1} recorded: Eye({cx}, {cy})")
            current_point += 1
            if current_point >= 9:
                print("\nAll 9 points recorded. Press R to reset.")
        else:
            print("Pupil not detected - make sure your eye is visible.")

cap.release()
cv2.destroyAllWindows()
print("Eye tracking session ended.")

import cv2
import mediapipe as mp
import math
from collections import deque
from djitellopy import Tello
import time

# =============================
# CONFIG
# =============================
USE_TELLO = True      # <-- change to False for testing without drone
SPEED = 30            # Drone speed (20–40 is safe)

# =============================
# Utils
# =============================
def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)

# =============================
# MediaPipe Setup
# =============================
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

hands = mp_hands.Hands(
    max_num_hands=1,
    min_detection_confidence=0.75,
    min_tracking_confidence=0.75
)

# =============================
# Camera Setup
# =============================
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    cap = cv2.VideoCapture(1)
if not cap.isOpened():
    print("❌ No camera found")
    exit()

print("✅ Camera ready")

# =============================
# Tello Setup
# =============================
if USE_TELLO:
    tello = Tello()
    tello.connect()
    print("Battery:", tello.get_battery())
    tello.send_rc_control(0, 0, 0, 0)

    flying = False
else:
    flying = False

# =============================
# Stabilizer
# =============================
history = deque(maxlen=10)

def stabilize(g):
    history.append(g)
    if history.count(g) > 6:
        return g
    return "Detecting..."

# =============================
# Gesture detection
# =============================
def detect_gesture(lm, hand_label):

    thumb_tip, thumb_ip = lm[4], lm[3]
    index_tip, index_pip = lm[8], lm[6]
    middle_tip, middle_pip = lm[12], lm[10]
    ring_tip, ring_pip = lm[16], lm[14]
    pinky_tip, pinky_pip = lm[20], lm[18]

    index_up = index_tip.y < index_pip.y
    middle_up = middle_tip.y < middle_pip.y
    ring_up = ring_tip.y < ring_pip.y
    pinky_up = pinky_tip.y < pinky_pip.y

    if hand_label == "Right":
        thumb_up = thumb_tip.x < thumb_ip.x
    else:
        thumb_up = thumb_tip.x > thumb_ip.x

    fingers = [thumb_up, index_up, middle_up, ring_up, pinky_up]

    if fingers == [0,0,0,0,0]:
        return "Hover"
    if fingers == [0,1,0,0,0]:
        return "Up"
    if fingers == [1,1,1,1,1]:
        return "Forward"
    if fingers == [1,0,0,0,0]:
        return "Right" if hand_label == "Right" else "Left"
    if fingers == [0,1,1,0,0]:
        return "Land"

    return "Unknown"

# =============================
# Send command to Tello
# =============================
def send_command(gesture):
    global flying

    if not USE_TELLO:
        print("Gesture:", gesture)
        return

    if not flying and gesture != "Land":
        tello.send_rc_control(0, 0, 0, 0)
        return

    if gesture == "Hover":
        tello.send_rc_control(0, 0, 0, 0)

    elif gesture == "Up":
        tello.send_rc_control(0, 0, SPEED, 0)

    elif gesture == "Forward":
        tello.send_rc_control(0, SPEED, 0, 0)

    elif gesture == "Left":
        tello.send_rc_control(-SPEED, 0, 0, 0)

    elif gesture == "Right":
        tello.send_rc_control(SPEED, 0, 0, 0)

    elif gesture == "Land" and flying:
        tello.land()
        flying = False

# =============================
# Main Loop
# =============================
print("Press T = Takeoff | Q = Quit")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = hands.process(rgb)

    gesture = "None"

    if result.multi_hand_landmarks and result.multi_handedness:
        for lm_set, hand_info in zip(result.multi_hand_landmarks,
                                     result.multi_handedness):

            lm = lm_set.landmark
            hand_label = hand_info.classification[0].label

            gesture = detect_gesture(lm, hand_label)
            gesture = stabilize(gesture)

            send_command(gesture)

            mp_draw.draw_landmarks(frame, lm_set, mp_hands.HAND_CONNECTIONS)

    cv2.putText(frame, f"Gesture: {gesture}", (30, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,255,0), 3)

    cv2.putText(frame, "T=Takeoff  Q=Quit", (30, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,0), 2)

    cv2.imshow("Gesture Tello Control", frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord('t') and USE_TELLO and not flying:
        tello.takeoff()
        flying = True

    if key == ord('q'):
        break

# =============================
# Cleanup
# =============================
if USE_TELLO:
    tello.send_rc_control(0, 0, 0, 0)
    tello.end()

cap.release()
cv2.destroyAllWindows()

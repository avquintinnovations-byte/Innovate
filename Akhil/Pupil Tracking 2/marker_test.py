import cv2
import numpy as np
import math
import time

# =========================
# SETTINGS
# =========================
MARKER_SIZE = 100
CAM_INDEX = 1

SCREEN_W = 1920
SCREEN_H = 1080

# Target distances (px) when user is at ideal position
TARGET_VERTICAL = 260  # TL to BL (top left to bottom left)
TARGET_HORIZONTAL = 505 # TL to TR (top left to top right)
TOLERANCE = 25          # ±px allowed for perfect match

# =========================
# ArUco Setup
# =========================
aruco = cv2.aruco
dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)

params = aruco.DetectorParameters()
params.adaptiveThreshWinSizeMin = 3
params.adaptiveThreshWinSizeMax = 60
params.adaptiveThreshWinSizeStep = 3
params.minMarkerPerimeterRate = 0.01
params.maxMarkerPerimeterRate = 4.0
params.polygonalApproxAccuracyRate = 0.05

detector = aruco.ArucoDetector(dictionary, params)

# =========================
# Generate Markers (9 total: 4 corners + 4 edges + 1 center)
# =========================
markers = {}
for marker_id in range(9):
    img = aruco.generateImageMarker(dictionary, marker_id, MARKER_SIZE)
    markers[marker_id] = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

# =========================
# Camera
# =========================
cap = cv2.VideoCapture(CAM_INDEX)

# =========================
# Windows
# =========================
cv2.namedWindow("Marker Screen", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("Marker Screen",
                      cv2.WND_PROP_FULLSCREEN,
                      cv2.WINDOW_FULLSCREEN)

cv2.namedWindow("Camera View", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Camera View", 640, 480)

print("\n=== 9-Marker Screen Alignment ===")
print("IDs: TL=0 TC=5 TR=1 | LC=6 C=4 RC=7 | BL=3 BC=8 BR=2")
print("Q → Quit\n")

# Perfect match sequence: countdown 3,2,1 then show each marker with coords
seq_state = None       # None, 'countdown', 'show_marker'
seq_start_time = 0.0
countdown_val = 3
marker_idx = 0

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ Camera read failed")
        break

    cam_display = frame.copy()

    # =========================
    # Detect Markers (do first so we have detected_centers for sequence)
    # =========================
    corners, ids, _ = detector.detectMarkers(frame)
    detected_centers = {}
    if ids is not None:
        ids = ids.flatten()
        for i, detected_id in enumerate(ids):
            pts = corners[i][0].astype(int)
            cv2.polylines(cam_display, [pts], True, (0, 255, 0), 2)
            center = pts.mean(axis=0).astype(int)
            cx, cy = center
            detected_centers[detected_id] = (cx, cy)
            cv2.circle(cam_display, (cx, cy), 6, (0, 0, 255), -1)
            cv2.putText(cam_display, f"ID {detected_id}", (cx-20, cy-15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.putText(cam_display, f"({cx}, {cy})", (cx-25, cy+25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 165, 0), 2)
    else:
        cv2.putText(cam_display, "NO MARKERS", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

    # =========================
    # Build Marker Screen
    # =========================
    screen = np.ones((SCREEN_H, SCREEN_W, 3), dtype=np.uint8) * 255

    # 3x3 grid: TL=0 TC=5 TR=1 | LC=6 C=4 RC=7 | BL=3 BC=8 BR=2
    pad = 10
    left_x = pad
    right_x = SCREEN_W - MARKER_SIZE - pad
    center_x = (SCREEN_W - MARKER_SIZE) // 2
    top_y = pad
    bottom_y = SCREEN_H - MARKER_SIZE - pad
    center_y = (SCREEN_H - MARKER_SIZE) // 2
    positions = {
        0: (left_x, top_y),       # TL
        1: (right_x, top_y),      # TR
        2: (right_x, bottom_y),   # BR
        3: (left_x, bottom_y),    # BL
        4: (center_x, center_y),  # center
        5: (center_x, top_y),     # top-center
        6: (left_x, center_y),    # left-center
        7: (right_x, center_y),   # right-center
        8: (center_x, bottom_y),  # bottom-center
    }

    # Draw markers: countdown, one marker, or all 9
    if seq_state == 'countdown' and countdown_val > 0:
        for marker_id, (x, y) in positions.items():
            screen[y:y+MARKER_SIZE, x:x+MARKER_SIZE] = markers[marker_id]
        cd_text = str(countdown_val)
        (tw, th), _ = cv2.getTextSize(cd_text, cv2.FONT_HERSHEY_SIMPLEX, 8, 6)
        tx = (SCREEN_W - tw) // 2
        ty = (SCREEN_H + th) // 2
        cv2.putText(screen, cd_text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 8, (0, 180, 0), 6)
    elif seq_state == 'show_marker' and marker_idx < 9:
        mid = marker_idx
        x, y = positions[mid]
        screen[y:y+MARKER_SIZE, x:x+MARKER_SIZE] = markers[mid]
        # Marker label and coords (camera view if detected, else screen pos)
        coord_text = f"ID{mid}: "
        if mid in detected_centers:
            cx, cy = detected_centers[mid]
            coord_text += f"({cx},{cy})"
        else:
            mx, my = x + MARKER_SIZE//2, y + MARKER_SIZE//2
            coord_text += f"screen ({mx},{my})"
        cv2.putText(screen, coord_text, (x, y - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.putText(screen, f"Marker {mid+1}/9", (SCREEN_W//2 - 80, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    else:
        for marker_id, (x, y) in positions.items():
            screen[y:y+MARKER_SIZE, x:x+MARKER_SIZE] = markers[marker_id]

    # Coord summary (camera view: origin top-left, x right, y down)
    h = cam_display.shape[0]
    y_start = h - 20
    for i, mid in enumerate(sorted(detected_centers.keys())):
        x, y = detected_centers[mid]
        cv2.putText(cam_display, f"ID{mid}: ({x},{y})", (10, y_start - i*16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 200, 100), 1)
    if detected_centers:
        cv2.putText(cam_display, "Cam coords (x,y):", (10, y_start - len(detected_centers)*16 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    # =========================
    # Draw distances between corner markers (0,1,2,3) for alignment
    # =========================
    corner_ids = [k for k in detected_centers.keys() if k in (0, 1, 2, 3)]
    for i in range(len(corner_ids)):
        for j in range(i + 1, len(corner_ids)):
            id1, id2 = corner_ids[i], corner_ids[j]
            x1, y1 = detected_centers[id1]
            x2, y2 = detected_centers[id2]
            dist = int(math.sqrt((x2 - x1)**2 + (y2 - y1)**2))
            cv2.line(cam_display, (x1, y1), (x2, y2), (255, 200, 0), 1)
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.putText(cam_display, f"{dist}px", (mx, my),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    # =========================
    # Distance-based guidance (TL=0, TR=1, BL=3)
    # =========================
    guidance = ""
    if 0 in detected_centers and 1 in detected_centers and 3 in detected_centers:
        tl = np.array(detected_centers[0])
        tr = np.array(detected_centers[1])
        bl = np.array(detected_centers[3])
        dist_vertical = int(np.linalg.norm(bl - tl))   # TL to BL
        dist_horizontal = int(np.linalg.norm(tr - tl))  # TL to TR

        v_ok = TARGET_VERTICAL - TOLERANCE <= dist_vertical <= TARGET_VERTICAL + TOLERANCE
        h_ok = TARGET_HORIZONTAL - TOLERANCE <= dist_horizontal <= TARGET_HORIZONTAL + TOLERANCE

        if v_ok and h_ok:
            guidance = "Perfect match!"
        elif dist_vertical < TARGET_VERTICAL - TOLERANCE or dist_horizontal < TARGET_HORIZONTAL - TOLERANCE:
            guidance = "Move toward the screen"
        else:
            guidance = "Move away from the screen"
    else:
        # Head left/right and up/down guidance when markers missing
        left_markers = {0, 3, 6}   # TL, BL, LC
        right_markers = {1, 2, 7}  # TR, BR, RC
        top_markers = {0, 1, 5}    # TL, TR, TC
        bottom_markers = {2, 3, 8} # BR, BL, BC
        corner_markers = {0, 1, 2, 3}
        detected_set = set(detected_centers.keys())
        if not detected_set:
            guidance = "Move head left or right to find markers"
        elif len(detected_set & corner_markers) == 3:
            # One corner missing - diagonal guidance toward missing corner
            missing = (corner_markers - detected_set).pop()
            diagonal = {0: "left and up", 1: "right and up", 2: "right and down", 3: "left and down"}
            guidance = "Move head " + diagonal[missing]
        else:
            parts = []
            if detected_set & left_markers and not (detected_set & right_markers):
                parts.append("right")
            if detected_set & right_markers and not (detected_set & left_markers):
                parts.append("left")
            if detected_set & top_markers and not (detected_set & bottom_markers):
                parts.append("down")   # see top only -> look down to see bottom
            if detected_set & bottom_markers and not (detected_set & top_markers):
                parts.append("up")     # see bottom only -> look up to see top
            if parts:
                guidance = "Move head " + " and ".join(parts)
            else:
                guidance = ""

    # Perfect match sequence: countdown 3,2,1 then show each marker with coords
    if guidance == "Perfect match!" and seq_state is None:
        seq_state = 'countdown'
        seq_start_time = time.time()
        countdown_val = 3
        marker_idx = 0

    if seq_state is not None:
        elapsed = time.time() - seq_start_time
        if seq_state == 'countdown':
            countdown_val = max(0, 3 - int(elapsed))
            if countdown_val == 0:
                seq_state = 'show_marker'
                seq_start_time = time.time()
                marker_idx = 0
        elif seq_state == 'show_marker':
            marker_idx = min(8, int(elapsed // 2))  # 2 sec per marker
            if marker_idx >= 9:
                seq_state = None

    # =========================
    # Overlay on Marker Screen (skip during perfect-match sequence)
    # =========================
    if seq_state is None:
        for marker_id in detected_centers:
            if marker_id in positions:
                x, y = positions[marker_id]
                mx = x + MARKER_SIZE // 2
                my = y + MARKER_SIZE // 2
                cv2.line(screen, (mx-30, my), (mx+30, my), (0,0,255), 2)
                cv2.line(screen, (mx, my-30), (mx, my+30), (0,0,255), 2)
                cv2.rectangle(screen,
                              (mx-50, my-50),
                              (mx+50, my+50),
                              (255, 0, 0), 2)
                cv2.putText(screen, f"LOCKED ID {marker_id}",
                            (mx-80, my+90),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.7,
                            (0,150,0), 2)

    # Draw guidance above center (skip during perfect-match sequence)
    if guidance and seq_state is None:
        cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 80
        color = (0, 180, 0) if "Perfect" in guidance else (0, 0, 255)
        (tw, th), _ = cv2.getTextSize(guidance, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 3)
        tx, ty = cx - tw // 2, cy - th // 2
        cv2.putText(screen, guidance, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 3)

    # =========================
    # Show Windows
    # =========================
    cv2.imshow("Marker Screen", screen)
    cv2.imshow("Camera View", cam_display)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

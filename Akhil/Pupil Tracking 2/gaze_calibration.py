"""
Gaze Calibration - Map pupil position (pupil camera) to world view (world camera).

Uses two cameras:
- World-facing: sees markers on screen, used for calibration targets and gaze overlay
- Pupil-facing: tracks pupil with YOLO

Flow: User moves to perfect distance -> countdown 3,2,1 -> markers shown one by one ->
record (pupil_x, pupil_y) <-> (world_x, world_y) for each -> polynomial mapping ->
display world view with gaze pointer overlay.
"""

from ultralytics import YOLO
import cv2
import numpy as np
import math
import time
from collections import deque

try:
    from scipy.interpolate import RBFInterpolator
    HAS_SCIPY_RBF = True
except ImportError:
    HAS_SCIPY_RBF = False

# =========================
# SETTINGS
# =========================
MARKER_SIZE = 100
SCREEN_W = 1920
SCREEN_H = 1080
CAM_WORLD = 1   # World-facing camera (sees markers/screen)
CAM_PUPIL = 2   # Pupil-facing camera

TARGET_VERTICAL = 260
TARGET_HORIZONTAL = 505
TOLERANCE = 25
SECS_PER_MARKER = 2.5  # more time = more samples per point

# =========================
# ArUco
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

markers = {}
for mid in range(9):
    img = aruco.generateImageMarker(dictionary, mid, MARKER_SIZE)
    markers[mid] = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

pad = 10
positions = {
    0: (pad, pad),
    1: (SCREEN_W - MARKER_SIZE - pad, pad),
    2: (SCREEN_W - MARKER_SIZE - pad, SCREEN_H - MARKER_SIZE - pad),
    3: (pad, SCREEN_H - MARKER_SIZE - pad),
    4: ((SCREEN_W - MARKER_SIZE) // 2, (SCREEN_H - MARKER_SIZE) // 2),
    5: ((SCREEN_W - MARKER_SIZE) // 2, pad),
    6: (pad, (SCREEN_H - MARKER_SIZE) // 2),
    7: (SCREEN_W - MARKER_SIZE - pad, (SCREEN_H - MARKER_SIZE) // 2),
    8: ((SCREEN_W - MARKER_SIZE) // 2, SCREEN_H - MARKER_SIZE - pad),
}

# =========================
# Cameras & Model
# =========================
model = YOLO("best.pt")
cap_world = cv2.VideoCapture(CAM_WORLD)
cap_pupil = cv2.VideoCapture(CAM_PUPIL)

if not cap_world.isOpened():
    print("World camera not opening")
    exit()
if not cap_pupil.isOpened():
    print("Pupil camera not opening")
    exit()

# =========================
# State
# =========================
CALIBRATION_ROUNDS = 1
calibration_complete = False
calibration_round = 0
calibration_points = []  # (pupil_x, pupil_y, world_x, world_y) current round
calibration_round1_points = []  # first round saved for merging
seq_state = None
seq_start_time = 0.0
countdown_val = 3
marker_idx = 0
samples_this_marker = []
mapping_params = None

# =========================
# Mapping (RBF thin-plate spline for accuracy, polynomial fallback)
# =========================
gaze_smooth_buffer = deque(maxlen=5)  # sliding avg for jitter reduction

def filter_outliers(samples, std_thresh=2.0):
    """Remove samples far from median (pupil and world coords)."""
    if len(samples) < 4:
        return samples
    arr = np.array(samples)
    p_med = np.median(arr[:, :2], axis=0)
    w_med = np.median(arr[:, 2:], axis=0)
    p_std = np.std(arr[:, :2], axis=0) + 1e-6
    w_std = np.std(arr[:, 2:], axis=0) + 1e-6
    keep = []
    for s in samples:
        dp = np.abs(np.array(s[:2]) - p_med) / p_std
        dw = np.abs(np.array(s[2:]) - w_med) / w_std
        if np.max(dp) < std_thresh and np.max(dw) < std_thresh:
            keep.append(s)
    return keep if len(keep) >= 2 else samples

def create_poly_features(x, y):
    return np.array([1, x, y, x**2, x*y, y**2, x**3, (x**2)*y, x*(y**2), y**3])

def compute_mapping(points):
    if len(points) < 6:
        return None
    eye_coords = np.array([[p[0], p[1]] for p in points], dtype=np.float64)
    world_coords = np.array([[p[2], p[3]] for p in points], dtype=np.float64)
    if HAS_SCIPY_RBF:
        try:
            rbf_x = RBFInterpolator(eye_coords, world_coords[:, 0], kernel='thin_plate_spline', smoothing=0.0)
            rbf_y = RBFInterpolator(eye_coords, world_coords[:, 1], kernel='thin_plate_spline', smoothing=0.0)
            # Verify fit
            pred = np.column_stack([rbf_x(eye_coords), rbf_y(eye_coords)])
            err = np.mean(np.sqrt(np.sum((pred - world_coords)**2, axis=1)))
            print(f"RBF mapping: avg error {err:.1f}px")
            return {'type': 'rbf', 'rbf_x': rbf_x, 'rbf_y': rbf_y}
        except Exception as e:
            print(f"RBF failed ({e}), using polynomial")
    eye_mean = eye_coords.mean(axis=0)
    eye_std = eye_coords.std(axis=0) + 1e-6
    eye_norm = (eye_coords - eye_mean) / eye_std
    A = np.array([create_poly_features(ex, ey) for ex, ey in eye_norm])
    lam = 1e-6
    try:
        coeffs_x = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ world_coords[:, 0])
        coeffs_y = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ world_coords[:, 1])
        return {'type': 'poly', 'coeffs_x': coeffs_x, 'coeffs_y': coeffs_y, 'mean': eye_mean, 'std': eye_std}
    except Exception:
        return None

def map_pupil_to_world(pupil_x, pupil_y):
    global mapping_params, gaze_smooth_buffer
    m = mapping_params
    if m is None:
        return None, None
    try:
        if m['type'] == 'rbf':
            pt = np.array([[float(pupil_x), float(pupil_y)]])
            wx = float(m['rbf_x'](pt)[0])
            wy = float(m['rbf_y'](pt)[0])
        else:
            ex = (pupil_x - m['mean'][0]) / m['std'][0]
            ey = (pupil_y - m['mean'][1]) / m['std'][1]
            f = create_poly_features(ex, ey)
            wx = float(np.dot(m['coeffs_x'], f))
            wy = float(np.dot(m['coeffs_y'], f))
        if not np.isfinite(wx) or not np.isfinite(wy):
            return None, None
    except Exception:
        return None, None
    gaze_smooth_buffer.append((wx, wy))
    if len(gaze_smooth_buffer) >= 2:
        wx = np.mean([g[0] for g in gaze_smooth_buffer])
        wy = np.mean([g[1] for g in gaze_smooth_buffer])
    return wx, wy

# =========================
# Windows
# =========================
cv2.namedWindow("Marker Screen", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("Marker Screen", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
cv2.namedWindow("World Camera", cv2.WINDOW_NORMAL)
cv2.resizeWindow("World Camera", 640, 480)
cv2.namedWindow("Pupil Camera", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Pupil Camera", 640, 480)

print("\n=== Gaze Calibration ===")
print("1. Move to perfect distance (green guidance)")
print("2. Countdown 3,2,1 then look at each marker as it appears")
print("3. After calibration: world view with gaze pointer")
print("R=recalibrate Q=quit\n")

while True:
    ret_w, frame_world = cap_world.read()
    ret_p, frame_pupil = cap_pupil.read()
    if not ret_w or not ret_p:
        break

    frame_pupil = cv2.flip(frame_pupil, 0)
    world_display = frame_world.copy()

    # =========================
    # World camera: detect markers (only during calibration)
    # =========================
    detected_centers = {}
    if not calibration_complete:
        corners, ids, _ = detector.detectMarkers(frame_world)
        if ids is not None:
            ids = ids.flatten()
            for i, did in enumerate(ids):
                pts = corners[i][0].astype(int)
                cv2.polylines(world_display, [pts], True, (0, 255, 0), 2)
                cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
                detected_centers[did] = (cx, cy)
                cv2.circle(world_display, (cx, cy), 6, (0, 0, 255), -1)
                cv2.putText(world_display, f"ID{did}", (cx-20, cy-15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    # =========================
    # Pupil camera: YOLO (always)
    # =========================
    results = model.predict(source=frame_pupil, device=0, conf=0.8)
    pupil_x, pupil_y = None, None
    for box in results[0].boxes:
        x1, y1, x2, y2 = box.xyxy[0]
        pupil_x = int((x1 + x2) / 2)
        pupil_y = int((y1 + y2) / 2)
        cv2.circle(frame_pupil, (pupil_x, pupil_y), 5, (0, 255, 0), -1)
        break

    # =========================
    # Guidance & sequence logic (only during calibration)
    # =========================
    if not calibration_complete:
        guidance = ""
        if 0 in detected_centers and 1 in detected_centers and 3 in detected_centers:
            tl = np.array(detected_centers[0])
            tr = np.array(detected_centers[1])
            bl = np.array(detected_centers[3])
            dv = int(np.linalg.norm(bl - tl))
            dh = int(np.linalg.norm(tr - tl))
            v_ok = TARGET_VERTICAL - TOLERANCE <= dv <= TARGET_VERTICAL + TOLERANCE
            h_ok = TARGET_HORIZONTAL - TOLERANCE <= dh <= TARGET_HORIZONTAL + TOLERANCE
            if v_ok and h_ok:
                guidance = "Perfect match!"
            elif dv < TARGET_VERTICAL - TOLERANCE or dh < TARGET_HORIZONTAL - TOLERANCE:
                guidance = "Move toward the screen"
            else:
                guidance = "Move away from the screen"
        else:
            left_m = {0, 3, 6}
            right_m = {1, 2, 7}
            top_m = {0, 1, 5}
            bottom_m = {2, 3, 8}
            ds = set(detected_centers.keys())
            if not ds:
                guidance = "Move head left or right to find markers"
            elif len(ds & {0, 1, 2, 3}) == 3:
                miss = ({0, 1, 2, 3} - ds).pop()
                d = {0: "left and up", 1: "right and up", 2: "right and down", 3: "left and down"}
                guidance = "Move head " + d[miss]
            else:
                parts = []
                if ds & left_m and not (ds & right_m):
                    parts.append("right")
                if ds & right_m and not (ds & left_m):
                    parts.append("left")
                if ds & top_m and not (ds & bottom_m):
                    parts.append("down")
                if ds & bottom_m and not (ds & top_m):
                    parts.append("up")
                guidance = "Move head " + " and ".join(parts) if parts else ""

        # Start sequence on perfect match
        if guidance == "Perfect match!" and seq_state is None:
            seq_state = 'countdown'
            seq_start_time = time.time()
            countdown_val = 3
            marker_idx = 0
            samples_this_marker = []

        if seq_state is not None:
            elapsed = time.time() - seq_start_time
            if seq_state == 'countdown':
                countdown_val = max(0, 3 - int(elapsed))
                if countdown_val == 0:
                    seq_state = 'show_marker'
                    seq_start_time = time.time()
                    marker_idx = 0
                    samples_this_marker = []
            elif seq_state == 'show_marker':
                mid = min(8, int(elapsed // SECS_PER_MARKER))
                done = elapsed >= 9 * SECS_PER_MARKER
                if mid != marker_idx:
                    if samples_this_marker and marker_idx < 9:
                        filtered = filter_outliers(samples_this_marker)
                        px = np.median([s[0] for s in filtered])
                        py = np.median([s[1] for s in filtered])
                        wx = np.median([s[2] for s in filtered])
                        wy = np.median([s[3] for s in filtered])
                        calibration_points.append((px, py, wx, wy))
                        print(f"Round {calibration_round+1} Marker {marker_idx+1} recorded")
                    marker_idx = mid
                    samples_this_marker = []
                if done:
                    if samples_this_marker:
                        filtered = filter_outliers(samples_this_marker)
                        px = np.median([s[0] for s in filtered])
                        py = np.median([s[1] for s in filtered])
                        wx = np.median([s[2] for s in filtered])
                        wy = np.median([s[3] for s in filtered])
                        calibration_points.append((px, py, wx, wy))
                        print(f"Round {calibration_round+1} Marker 9 recorded")
                    if calibration_round == 0 and CALIBRATION_ROUNDS >= 2:
                        calibration_round1_points = calibration_points.copy()
                        calibration_round = 1
                        calibration_points = []
                        seq_state = None
                        print("\nRound 1 done. Get to perfect match for Round 2...")
                    else:
                        if calibration_round == 1 and len(calibration_points) >= 9:
                            merged = []
                            for i in range(9):
                                p1 = calibration_round1_points[i]
                                p2 = calibration_points[i]
                                merged.append((
                                    (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2,
                                    (p1[2] + p2[2]) / 2, (p1[3] + p2[3]) / 2
                                ))
                            points_for_mapping = merged
                        else:
                            points_for_mapping = calibration_points
                        mapping_params = compute_mapping(points_for_mapping)
                        calibration_complete = True
                        seq_state = None
                        print("\nCalibration complete. Gaze pointer active.")
                elif pupil_x is not None and pupil_y is not None and mid in detected_centers:
                    wx, wy = detected_centers[mid]
                    samples_this_marker.append((float(pupil_x), float(pupil_y), float(wx), float(wy)))

    # =========================
    # Marker Screen (only during calibration)
    # =========================
    if not calibration_complete:
        screen = np.ones((SCREEN_H, SCREEN_W, 3), dtype=np.uint8) * 255
        if seq_state == 'countdown' and countdown_val > 0:
            for mid, (x, y) in positions.items():
                screen[y:y+MARKER_SIZE, x:x+MARKER_SIZE] = markers[mid]
            cd = str(countdown_val)
            (tw, th), _ = cv2.getTextSize(cd, cv2.FONT_HERSHEY_SIMPLEX, 8, 6)
            cv2.putText(screen, cd, ((SCREEN_W - tw) // 2, (SCREEN_H + th) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 8, (0, 180, 0), 6)
        elif seq_state == 'show_marker' and marker_idx < 9:
            mid = marker_idx
            x, y = positions[mid]
            screen[y:y+MARKER_SIZE, x:x+MARKER_SIZE] = markers[mid]
            cv2.putText(screen, f"Marker {mid+1}/9 - Look at marker",
                        (SCREEN_W//2 - 120, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
        else:
            for mid, (x, y) in positions.items():
                screen[y:y+MARKER_SIZE, x:x+MARKER_SIZE] = markers[mid]
        if guidance and seq_state is None:
            cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 80
            color = (0, 180, 0) if "Perfect" in guidance else (0, 0, 255)
            (tw, th), _ = cv2.getTextSize(guidance, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 3)
            cv2.putText(screen, guidance, (cx - tw//2, cy - th//2), cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 3)
        cv2.imshow("Marker Screen", screen)
    else:
        try:
            cv2.destroyWindow("Marker Screen")
        except cv2.error:
            pass

    # =========================
    # Post-calibration: gaze overlay on world view
    # =========================
    if mapping_params is not None and pupil_x is not None and pupil_y is not None:
        gx, gy = map_pupil_to_world(pupil_x, pupil_y)
        if gx is not None:
            gx, gy = int(gx), int(gy)
            h, w = world_display.shape[:2]
            # Clamp or allow extrapolation - keep for display but clip to frame for visibility
            gx_clip = int(np.clip(gx, 0, w - 1))
            gy_clip = int(np.clip(gy, 0, h - 1))
            cv2.circle(world_display, (gx_clip, gy_clip), 20, (0, 255, 255), 2)
            cv2.circle(world_display, (gx_clip, gy_clip), 5, (0, 255, 255), -1)
            cv2.line(world_display, (gx_clip - 30, gy_clip), (gx_clip + 30, gy_clip), (0, 255, 255), 2)
            cv2.line(world_display, (gx_clip, gy_clip - 30), (gx_clip, gy_clip + 30), (0, 255, 255), 2)
            cv2.putText(world_display, "Gaze", (gx_clip + 25, gy_clip - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    cv2.putText(world_display, "World Camera (gaze pointer when calibrated)",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(frame_pupil, "Pupil Camera", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    cv2.imshow("World Camera", world_display)
    pupil_display = results[0].plot()
    cv2.imshow("Pupil Camera", pupil_display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('r'):
        calibration_complete = False
        calibration_round = 0
        calibration_points.clear()
        calibration_round1_points.clear()
        seq_state = None
        samples_this_marker = []
        mapping_params = None
        gaze_smooth_buffer.clear()
        cv2.namedWindow("Marker Screen", cv2.WINDOW_NORMAL)
        cv2.setWindowProperty("Marker Screen", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        print("Recalibrating...")

cap_world.release()
cap_pupil.release()
cv2.destroyAllWindows()
print("Session ended.")

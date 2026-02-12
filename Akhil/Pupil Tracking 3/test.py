from ultralytics import YOLO
import cv2
import pyautogui
import numpy as np
from collections import deque
import time

# Disable pyautogui failsafe for smoother experience
pyautogui.FAILSAFE = False

# Load your trained model
model = YOLO("best.pt")

# Open webcam
cap = cv2.VideoCapture(2)

if not cap.isOpened():
    print("Camera not opening")
    exit()

# Get screen dimensions
screen_width, screen_height = pyautogui.size()

# Calibration variables
calibration_mode = True
calibration_complete = False
calibration_points = []  # Will store (eye_x, eye_y, screen_x, screen_y)
current_calibration_step = 0
calibration_samples = []  # Collect multiple samples per point
samples_per_point = 10  # Number of samples to collect per calibration point
current_sample_count = 0
collecting_samples = False  # Flag to track if we're actively collecting

# Motion analysis during calibration
calibration_motion_data = []  # Track pupil motion during calibration

# Define calibration target positions (screen coordinates)
# Using 9 points for better coverage: 4 corners, 4 edges, 1 center
# Using actual screen corners (0%, 100%) for accurate edge-to-edge mapping
calibration_targets = [
    (0, 0),                                                    # Top-left corner (actual corner)
    (int(screen_width * 0.5), 0),                             # Top edge
    (screen_width - 1, 0),                                    # Top-right corner (actual corner)
    (screen_width - 1, int(screen_height * 0.5)),            # Right edge
    (screen_width - 1, screen_height - 1),                   # Bottom-right corner (actual corner)
    (int(screen_width * 0.5), screen_height - 1),            # Bottom edge
    (0, screen_height - 1),                                   # Bottom-left corner (actual corner)
    (0, int(screen_height * 0.5)),                           # Left edge
    (int(screen_width * 0.5), int(screen_height * 0.5)),     # Center
]

# Mapping coefficients (calculated from calibration)
mapping_coeffs_x = None
mapping_coeffs_y = None
eye_normalization = None  # For normalizing eye coordinates

# For smooth cursor movement
eye_positions = deque(maxlen=3)  # Small buffer for smoothing
screen_positions = deque(maxlen=3)  # Screen position smoothing

def create_calibration_window(target_x, target_y, step, total_steps, pupil_detected=False, collecting=False, samples_collected=0, total_samples=10):
    """Create a full-screen calibration window with visual cue"""
    calib_img = np.zeros((screen_height, screen_width, 3), dtype=np.uint8)
    
    # Draw target circle at calibration point
    circle_color = (0, 255, 0) if collecting else (0, 0, 255)
    cv2.circle(calib_img, (target_x, target_y), 30, circle_color, 3)
    cv2.circle(calib_img, (target_x, target_y), 10, circle_color, -1)
    
    # Add text instructions
    text = f"Look at the circle - Point {step}/{total_steps}"
    cv2.putText(calib_img, text, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 
                1, (255, 255, 255), 2)
    
    if collecting:
        text2 = f"Collecting samples: {samples_collected}/{total_samples}"
        cv2.putText(calib_img, text2, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 
                    1, (0, 255, 0), 2)
        # Draw progress bar
        bar_width = 400
        bar_height = 30
        bar_x, bar_y = 50, 130
        cv2.rectangle(calib_img, (bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height), (255, 255, 255), 2)
        progress = int((samples_collected / total_samples) * bar_width)
        cv2.rectangle(calib_img, (bar_x, bar_y), (bar_x + progress, bar_y + bar_height), (0, 255, 0), -1)
    else:
        text2 = "Press SPACEBAR to start collecting"
        cv2.putText(calib_img, text2, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 
                    1, (255, 255, 255), 2)
    
    # Show pupil detection status
    if pupil_detected:
        status_text = "Pupil Detected: YES"
        status_color = (0, 255, 0)
    else:
        status_text = "Pupil Detected: NO"
        status_color = (0, 0, 255)
    cv2.putText(calib_img, status_text, (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 
                0.8, status_color, 2)
    
    return calib_img

def calculate_spherical_mapping(calibration_points):
    """
    Calculate non-linear mapping coefficients accounting for spherical eye geometry
    Uses 3rd order polynomial regression to handle curved pupil movement
    """
    if len(calibration_points) < 6:
        print("Not enough calibration points for polynomial mapping")
        return None, None, None
    
    # Extract eye positions and their corresponding screen positions
    eye_coords = np.array([[p[0], p[1]] for p in calibration_points], dtype=np.float64)
    screen_coords = np.array([[p[2], p[3]] for p in calibration_points], dtype=np.float64)
    
    # Normalize eye coordinates for numerical stability
    eye_mean = eye_coords.mean(axis=0)
    eye_std = eye_coords.std(axis=0) + 1e-6
    eye_coords_norm = (eye_coords - eye_mean) / eye_std
    
    normalization = {
        'mean': eye_mean,
        'std': eye_std,
        'eye_min': eye_coords.min(axis=0),
        'eye_max': eye_coords.max(axis=0)
    }
    
    # Create polynomial features accounting for spherical distortion
    # Using 3rd order polynomial: [1, x, y, x², xy, y², x³, x²y, xy², y³]
    def create_polynomial_features(x, y):
        return np.array([
            1,           # constant
            x, y,        # linear
            x**2, x*y, y**2,  # quadratic (handles curvature)
            x**3, (x**2)*y, x*(y**2), y**3  # cubic (handles spherical distortion)
        ])
    
    # Build design matrix
    A = np.array([create_polynomial_features(ex, ey) for ex, ey in eye_coords_norm])
    
    try:
        # Solve for screen X and Y coordinates separately
        # Using ridge regression for stability
        lambda_reg = 0.001  # Small regularization
        
        # For X coordinate
        AtA_x = A.T @ A + lambda_reg * np.eye(A.shape[1])
        Atb_x = A.T @ screen_coords[:, 0]
        coeffs_x = np.linalg.solve(AtA_x, Atb_x)
        
        # For Y coordinate
        AtA_y = A.T @ A + lambda_reg * np.eye(A.shape[1])
        Atb_y = A.T @ screen_coords[:, 1]
        coeffs_y = np.linalg.solve(AtA_y, Atb_y)
        
        # Verify mapping quality
        print(f"\n=== Spherical Mapping Calibration ===")
        errors = []
        for i, (ex, ey, sx, sy) in enumerate(calibration_points):
            ex_norm = (ex - eye_mean[0]) / eye_std[0]
            ey_norm = (ey - eye_mean[1]) / eye_std[1]
            features = create_polynomial_features(ex_norm, ey_norm)
            
            pred_x = np.dot(coeffs_x, features)
            pred_y = np.dot(coeffs_y, features)
            
            error = np.sqrt((pred_x - sx)**2 + (pred_y - sy)**2)
            errors.append(error)
            
            status = "✓" if error < 100 else "✗"
            print(f"{status} Point {i+1}: Target({sx:.0f},{sy:.0f}) Predicted({pred_x:.0f},{pred_y:.0f}) Error: {error:.0f}px")
        
        avg_error = np.mean(errors)
        max_error = np.max(errors)
        
        print(f"\nMapping Quality:")
        print(f"  Average error: {avg_error:.1f} pixels")
        print(f"  Max error: {max_error:.1f} pixels")
        
        if avg_error < 50:
            print("  ✓ Excellent mapping quality")
        elif avg_error < 100:
            print("  ✓ Good mapping quality")
        else:
            print("  ⚠ Consider recalibrating for better accuracy")
        
        print(f"Eye movement range: {normalization['eye_max'][0] - normalization['eye_min'][0]:.1f} x {normalization['eye_max'][1] - normalization['eye_min'][1]:.1f} pixels")
        print(f"=====================================\n")
        
        return coeffs_x, coeffs_y, normalization
        
    except Exception as e:
        print(f"Error calculating spherical mapping: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

def draw_calibration_visualization(frame, calibration_points, current_eye_pos=None):
    """
    Draw visualization showing calibration points and current pupil position
    Shows the non-linear, curved mapping pattern
    """
    if len(calibration_points) == 0:
        return frame
    
    # Draw all calibration points
    for i, (eye_x, eye_y, screen_x, screen_y) in enumerate(calibration_points):
        # Color based on which screen corner/edge it maps to
        if screen_x < screen_width * 0.2 and screen_y < screen_height * 0.2:
            color = (255, 0, 0)  # Blue for top-left
        elif screen_x > screen_width * 0.8 and screen_y < screen_height * 0.2:
            color = (0, 255, 0)  # Green for top-right
        elif screen_x < screen_width * 0.2 and screen_y > screen_height * 0.8:
            color = (0, 255, 255)  # Yellow for bottom-left
        elif screen_x > screen_width * 0.8 and screen_y > screen_height * 0.8:
            color = (0, 0, 255)  # Red for bottom-right
        else:
            color = (255, 255, 0)  # Cyan for edges/center
        
        cv2.circle(frame, (int(eye_x), int(eye_y)), 6, color, -1)
        cv2.putText(frame, str(i+1), (int(eye_x) + 10, int(eye_y) + 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    
    # Draw convex hull around calibration points to show the tracking area
    if len(calibration_points) >= 4:
        eye_points = np.array([[int(p[0]), int(p[1])] for p in calibration_points], dtype=np.int32)
        hull = cv2.convexHull(eye_points)
        cv2.polylines(frame, [hull], True, (0, 255, 0), 2)
    
    # Show current eye position if provided
    if current_eye_pos is not None:
        cv2.circle(frame, (int(current_eye_pos[0]), int(current_eye_pos[1])), 10, (255, 0, 255), 3)
        
        # Draw lines to nearest calibration points to visualize interpolation
        if len(calibration_points) >= 3:
            eye_coords = np.array([[p[0], p[1]] for p in calibration_points])
            distances = np.sqrt(((eye_coords - np.array(current_eye_pos))**2).sum(axis=1))
            nearest_indices = np.argsort(distances)[:3]
            
            for idx in nearest_indices:
                eye_x, eye_y = calibration_points[idx][0], calibration_points[idx][1]
                cv2.line(frame, (int(current_eye_pos[0]), int(current_eye_pos[1])),
                        (int(eye_x), int(eye_y)), (255, 128, 0), 1)
    
    # Add label
    cv2.putText(frame, "Spherical Mapping (Curved)", (10, frame.shape[0] - 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.putText(frame, "Blue=TL, Green=TR, Yellow=BL, Red=BR", (10, frame.shape[0] - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    return frame

def map_eye_to_screen(eye_x, eye_y):
    """
    Map eye coordinates to screen coordinates using polynomial transformation
    Accounts for spherical eye geometry and curved pupil movement
    """
    global mapping_coeffs_x, mapping_coeffs_y, eye_normalization
    
    if mapping_coeffs_x is None or mapping_coeffs_y is None or eye_normalization is None:
        return None, None
    
    try:
        # Normalize eye coordinates using calibration statistics
        eye_x_norm = (eye_x - eye_normalization['mean'][0]) / eye_normalization['std'][0]
        eye_y_norm = (eye_y - eye_normalization['mean'][1]) / eye_normalization['std'][1]
        
        # Create polynomial features (must match training)
        def create_polynomial_features(x, y):
            return np.array([
                1,           # constant
                x, y,        # linear
                x**2, x*y, y**2,  # quadratic
                x**3, (x**2)*y, x*(y**2), y**3  # cubic
            ])
        
        features = create_polynomial_features(eye_x_norm, eye_y_norm)
        
        # Apply polynomial transformation
        screen_x = np.dot(mapping_coeffs_x, features)
        screen_y = np.dot(mapping_coeffs_y, features)
        
        # Clamp to screen boundaries
        screen_x = int(np.clip(screen_x, 0, screen_width - 1))
        screen_y = int(np.clip(screen_y, 0, screen_height - 1))
        
        return screen_x, screen_y
        
    except Exception as e:
        print(f"Mapping error: {e}")
        return None, None


print("Starting Eye Tracking with Calibration...")
print("Follow the on-screen instructions.")

# Create calibration window
cv2.namedWindow("Calibration", cv2.WINDOW_NORMAL)
cv2.setWindowProperty("Calibration", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 0)
    results = model.predict(source=frame, device=0, conf=0.8)

    cx, cy = None, None
    
    # Process detection results
    for box in results[0].boxes:
        x1, y1, x2, y2 = box.xyxy[0]
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)

        # Draw dot at centroid
        cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)
    
    # Draw results
    annotated_frame = results[0].plot()

    # Calibration mode
    if calibration_mode and not calibration_complete:
        if current_calibration_step < len(calibration_targets):
            target_x, target_y = calibration_targets[current_calibration_step]
            
            calib_img = create_calibration_window(target_x, target_y, 
                                                  current_calibration_step + 1, 
                                                  len(calibration_targets),
                                                  pupil_detected=(cx is not None),
                                                  collecting=collecting_samples,
                                                  samples_collected=current_sample_count,
                                                  total_samples=samples_per_point)
            cv2.imshow("Calibration", calib_img)
            
            # Show webcam feed in small window with partial bounds
            small_frame = cv2.resize(annotated_frame, (640, 480))
            
            # Draw partial bounds if we have at least 2 calibration points
            if len(calibration_points) >= 2:
                # Calculate current bounds from collected points
                partial_eye_coords = np.array([[p[0], p[1]] for p in calibration_points])
                partial_bounds = {
                    'min_x': partial_eye_coords[:, 0].min(),
                    'max_x': partial_eye_coords[:, 0].max(),
                    'min_y': partial_eye_coords[:, 1].min(),
                    'max_y': partial_eye_coords[:, 1].max()
                }
                
                # Scale bounds to small frame
                scale_x = 640 / frame.shape[1]
                scale_y = 480 / frame.shape[0]
                
                scaled_bounds = {
                    'min_x': partial_bounds['min_x'] * scale_x,
                    'max_x': partial_bounds['max_x'] * scale_x,
                    'min_y': partial_bounds['min_y'] * scale_y,
                    'max_y': partial_bounds['max_y'] * scale_y
                }
                
                # Draw rectangle showing partial calibration
                pt1 = (int(scaled_bounds['min_x']), int(scaled_bounds['min_y']))
                pt2 = (int(scaled_bounds['max_x']), int(scaled_bounds['max_y']))
                cv2.rectangle(small_frame, pt1, pt2, (255, 255, 0), 2)
                
                # Mark calibrated points
                for eye_x, eye_y, _, _ in calibration_points:
                    pt = (int(eye_x * scale_x), int(eye_y * scale_y))
                    cv2.circle(small_frame, pt, 5, (0, 255, 255), -1)
                
                cv2.putText(small_frame, f"Building bounds... {len(calibration_points)}/{len(calibration_targets)}", 
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            
            # Show current pupil position if detected
            if cx is not None and cy is not None:
                scale_x = 640 / frame.shape[1]
                scale_y = 480 / frame.shape[0]
                current_pt = (int(cx * scale_x), int(cy * scale_y))
                cv2.circle(small_frame, current_pt, 8, (255, 0, 255), 2)
            
            cv2.imshow("Pupil Detection", small_frame)
            
            # Auto-collect samples when pupil is detected and collection started
            if collecting_samples and cx is not None and cy is not None:
                calibration_samples.append((cx, cy, target_x, target_y))
                calibration_motion_data.append((cx, cy))
                current_sample_count += 1
                
                # When we have enough samples for this point
                if current_sample_count >= samples_per_point:
                    # Average the samples for this calibration point
                    samples_array = np.array(calibration_samples)
                    avg_eye_x = np.median(samples_array[:, 0])  # Use median for robustness
                    avg_eye_y = np.median(samples_array[:, 1])
                    
                    calibration_points.append((avg_eye_x, avg_eye_y, target_x, target_y))
                    print(f"Calibration point {current_calibration_step + 1} recorded: "
                          f"Eye({avg_eye_x:.1f}, {avg_eye_y:.1f}) -> Screen({target_x}, {target_y})")
                    
                    # Move to next point
                    current_calibration_step += 1
                    calibration_samples = []
                    current_sample_count = 0
                    collecting_samples = False  # Stop collecting for next point
                    
                    # Check if calibration is complete
                    if current_calibration_step >= len(calibration_targets):
                        calibration_complete = True
                        calibration_mode = False
                        cv2.destroyWindow("Calibration")
                        
                        # Calculate spherical mapping coefficients
                        mapping_coeffs_x, mapping_coeffs_y, eye_normalization = calculate_spherical_mapping(calibration_points)
                        
                        if mapping_coeffs_x is not None:
                            print("\n✓ Calibration complete! You can now control the mouse with your eyes.")
                            print(f"✓ Using 3rd-order polynomial mapping to account for spherical eye geometry")
                            print("✓ Colored dots on video show calibration points (curved mapping)")
                            print("✓ Press 'R' to recalibrate | 'Q' to quit.\n")
                        else:
                            print("\n✗ Calibration failed! Press 'R' to try again.")
                        
                        # Test pyautogui
                        try:
                            current_pos = pyautogui.position()
                            print(f"✓ PyAutoGUI working! Current cursor: {current_pos}\n")
                        except Exception as e:
                            print(f"⚠ PyAutoGUI error: {e}")
                            print("You may need to run the script with administrator privileges on Windows.")
            
            key = cv2.waitKey(1) & 0xFF
            
            # Spacebar pressed to start collecting samples
            if key == 32:  # Spacebar key code is 32
                if cx is not None and cy is not None and not collecting_samples:
                    calibration_samples = []
                    current_sample_count = 0
                    collecting_samples = True  # Start collecting
                    print(f"✓ Spacebar pressed! Collecting samples for point {current_calibration_step + 1}...")
                elif cx is None or cy is None:
                    print("⚠ Pupil not detected! Make sure your eye is visible.")
                elif collecting_samples:
                    print("⚠ Already collecting samples, please wait...")
            
            # Press Q to quit
            if key == ord('q'):
                break
        
    # Mouse control mode (after calibration)
    else:
        if mapping_coeffs_x is not None and cx is not None and cy is not None:
            # Add current position to smoothing buffer
            eye_positions.append((cx, cy))
            
            # Simple averaging for smoothing
            if len(eye_positions) >= 2:
                recent_positions = list(eye_positions)
                avg_x = np.mean([pos[0] for pos in recent_positions])
                avg_y = np.mean([pos[1] for pos in recent_positions])
            else:
                avg_x, avg_y = cx, cy
            
            # Map eye position to screen coordinates using spherical mapping
            screen_x, screen_y = map_eye_to_screen(avg_x, avg_y)
            
            if screen_x is not None and screen_y is not None:
                # Add to screen position buffer for smoothing
                screen_positions.append((screen_x, screen_y))
                
                # Average screen positions for smooth cursor movement
                if len(screen_positions) >= 2:
                    recent_screen = list(screen_positions)
                    final_x = int(np.mean([pos[0] for pos in recent_screen]))
                    final_y = int(np.mean([pos[1] for pos in recent_screen]))
                else:
                    final_x, final_y = screen_x, screen_y
                
                # Move cursor
                try:
                    pyautogui.moveTo(final_x, final_y)
                    move_status = "✓ Tracking (Spherical)"
                except Exception as e:
                    move_status = f"✗ Error: {str(e)[:20]}"
                
                # Display debug information
                pos_text = f"Screen: ({final_x}, {final_y})"
                eye_text = f"Eye: ({int(avg_x)}, {int(avg_y)})"
                
                cv2.putText(annotated_frame, pos_text, (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(annotated_frame, eye_text, (10, 60), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                cv2.putText(annotated_frame, move_status, (10, 90), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0) if "✓" in move_status else (0, 0, 255), 2)
        
        # Draw calibration visualization showing curved mapping
        annotated_frame = draw_calibration_visualization(annotated_frame, calibration_points, 
                                                         (cx, cy) if cx is not None else None)
        
        # Add instructions
        cv2.putText(annotated_frame, "Press 'R' to recalibrate | 'Q' to quit", 
                   (10, annotated_frame.shape[0] - 60), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        cv2.imshow("Pupil Detection", annotated_frame)
        
        # Handle key presses
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            # Restart calibration
            print("\nRestarting calibration...")
            calibration_mode = True
            calibration_complete = False
            calibration_points = []
            calibration_samples = []
            calibration_motion_data = []
            current_calibration_step = 0
            current_sample_count = 0
            collecting_samples = False
            eye_positions.clear()
            screen_positions.clear()
            mapping_coeffs_x = None
            mapping_coeffs_y = None
            eye_normalization = None
            cv2.namedWindow("Calibration", cv2.WINDOW_NORMAL)
            cv2.setWindowProperty("Calibration", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

cap.release()
cv2.destroyAllWindows()
print("Eye tracking session ended.")
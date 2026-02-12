from ultralytics import SAM, YOLO
import cv2
import numpy as np
import torch
from datetime import datetime
import os
import sys
import time
from collections import deque
import threading
import subprocess
import google.generativeai as genai
from PIL import Image

try:
    from scipy.interpolate import RBFInterpolator
    HAS_SCIPY_RBF = True
except ImportError:
    HAS_SCIPY_RBF = False

CALIBRATION_FILE = "gaze_calibration_points.npy"

gaze_smooth_buffer = deque(maxlen=5)
mapping_params = None


def create_poly_features(x, y):
    return np.array(
        [1, x, y, x**2, x * y, y**2, x**3, (x**2) * y, x * (y**2), y**3],
        dtype=np.float64,
    )


def compute_mapping(points):
    """
    Reconstruct mapping from pupil (eye) coordinates to world coordinates,
    using the same logic as in gaze_calibration.py.
    """
    if len(points) < 6:
        return None

    eye_coords = np.array([[p[0], p[1]] for p in points], dtype=np.float64)
    world_coords = np.array([[p[2], p[3]] for p in points], dtype=np.float64)

    # Prefer RBF thin-plate spline if SciPy is available
    if HAS_SCIPY_RBF:
        try:
            rbf_x = RBFInterpolator(
                eye_coords, world_coords[:, 0], kernel="thin_plate_spline", smoothing=0.0
            )
            rbf_y = RBFInterpolator(
                eye_coords, world_coords[:, 1], kernel="thin_plate_spline", smoothing=0.0
            )
            return {"type": "rbf", "rbf_x": rbf_x, "rbf_y": rbf_y}
        except Exception as e:
            print(f"RBF mapping failed in segmentation ({e}), falling back to polynomial")

    # Polynomial fallback (same structure as calibration)
    eye_mean = eye_coords.mean(axis=0)
    eye_std = eye_coords.std(axis=0) + 1e-6
    eye_norm = (eye_coords - eye_mean) / eye_std
    A = np.array([create_poly_features(ex, ey) for ex, ey in eye_norm])

    lam = 1e-6
    try:
        coeffs_x = np.linalg.solve(
            A.T @ A + lam * np.eye(A.shape[1]), A.T @ world_coords[:, 0]
        )
        coeffs_y = np.linalg.solve(
            A.T @ A + lam * np.eye(A.shape[1]), A.T @ world_coords[:, 1]
        )
        return {
            "type": "poly",
            "coeffs_x": coeffs_x,
            "coeffs_y": coeffs_y,
            "mean": eye_mean,
            "std": eye_std,
        }
    except Exception as e:
        print(f"Polynomial mapping failed in segmentation ({e})")
        return None


def map_pupil_to_world(pupil_x, pupil_y):
    """
    Apply the mapping (if available) and smooth the gaze signal.
    Returns (world_x, world_y) or (None, None) on failure.
    """
    global mapping_params, gaze_smooth_buffer
    m = mapping_params
    if m is None:
        return None, None

    try:
        if m["type"] == "rbf":
            pt = np.array([[float(pupil_x), float(pupil_y)]], dtype=np.float64)
            wx = float(m["rbf_x"](pt)[0])
            wy = float(m["rbf_y"](pt)[0])
        else:
            ex = (pupil_x - m["mean"][0]) / m["std"][0]
            ey = (pupil_y - m["mean"][1]) / m["std"][1]
            f = create_poly_features(ex, ey)
            wx = float(np.dot(m["coeffs_x"], f))
            wy = float(np.dot(m["coeffs_y"], f))

        if not np.isfinite(wx) or not np.isfinite(wy):
            return None, None
    except Exception:
        return None, None

    gaze_smooth_buffer.append((wx, wy))
    if len(gaze_smooth_buffer) >= 2:
        wx = np.mean([g[0] for g in gaze_smooth_buffer])
        wy = np.mean([g[1] for g in gaze_smooth_buffer])

    return wx, wy

# Set your Gemini API key in an environment variable named GEMINI_API_KEY.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDgG-sQFfLt1-rBly7PJ7s9yQIQ2UvW-lY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

def main():
    global mapping_params, gaze_smooth_buffer

    # Check if CUDA is available
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"Using device: {device}")
    
    if device == 'cpu':
        print("WARNING: CUDA not available, running on CPU (will be slow)")
    
    print("Loading SAM2 model...")
    sam_model = SAM("sam2.1_s.pt")
    sam_model.to(device)  # Move model to CUDA if available

    # Load YOLO model for pupil detection (same as in calibration script)
    print("Loading YOLO pupil model...")
    yolo_device = device
    pupil_model = YOLO("best.pt")

    # Initialize Gemini (if API key is present)
    gemini_enabled = bool(GEMINI_API_KEY)
    gemini_model = None
    if gemini_enabled:
        genai.configure(api_key=GEMINI_API_KEY)
        # Choose a model that supports generateContent
        try:
            available = list(genai.list_models())
            supported = [
                m.name for m in available
                if hasattr(m, "supported_generation_methods")
                and "generateContent" in m.supported_generation_methods
            ]
            preferred = f"models/{GEMINI_MODEL_NAME}" if not GEMINI_MODEL_NAME.startswith("models/") else GEMINI_MODEL_NAME
            model_name = preferred if preferred in supported else (supported[0] if supported else preferred)
            if preferred not in supported and supported:
                print(f"Gemini model '{GEMINI_MODEL_NAME}' not available. Using {model_name}.")
            gemini_model = genai.GenerativeModel(model_name)
        except Exception as e:
            print(f"Gemini model listing failed: {e}. Falling back to {GEMINI_MODEL_NAME}.")
            gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
    else:
        print("Gemini API key not set. Set GEMINI_API_KEY to enable captions.")

    # Initialize text-to-speech (optional, using PowerShell System.Speech)
    print("Text-to-speech via PowerShell System.Speech is enabled; Gemini responses will be spoken.")

    # Open world camera (same index used during calibration for WORLD camera)
    cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        print("Error: Could not open camera")
        return

    # Open pupil camera (same index used during calibration for PUPIL camera)
    cap_pupil = cv2.VideoCapture(2)
    if not cap_pupil.isOpened():
        print("Warning: Could not open pupil camera. Falling back to keyboard/mouse control only.")
        cap_pupil = None

    # Get frame dimensions
    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read frame")
        return

    height, width = frame.shape[:2]

    # Try to load calibration points saved by gaze_calibration.py
    if os.path.exists(CALIBRATION_FILE):
        try:
            loaded_points = np.load(CALIBRATION_FILE)
            if loaded_points.ndim == 2 and loaded_points.shape[1] == 4:
                mapping_params = compute_mapping(loaded_points.tolist())
                if mapping_params is not None:
                    print(f"Gaze calibration loaded from {CALIBRATION_FILE}")
                else:
                    print("Failed to build mapping from calibration points; gaze control disabled.")
            else:
                print(f"Calibration file {CALIBRATION_FILE} has unexpected shape {loaded_points.shape}")
        except Exception as e:
            print(f"Could not load calibration file {CALIBRATION_FILE}: {e}")
    else:
        print(f"Calibration file {CALIBRATION_FILE} not found. Run gaze_calibration.py first to enable gaze control.")
    
    # Crosshair position (start at center)
    crosshair_x = width // 2
    crosshair_y = height // 2
    crosshair_size = 20
    move_step = 10  # pixels to move per key press
    
    # Segmentation variables
    current_mask = None
    segment_enabled = True
    
    # Flashing circle parameters
    flash_frequency = 2.0  # Hz (flashes per second) - ADJUST THIS TO CHANGE SPEED
    circle_radius = 15
    circle_offset_y = 40  # pixels above the object
    start_time = time.time()
    
    # Gemini response overlay
    last_gemini_text = ""
    last_gemini_time = 0.0
    gemini_display_seconds = 4.0

    window_name = "Crosshair Segmentation"

    # Helper: speak Gemini response without blocking camera loop
    def speak_text_async(text: str):
        if not text:
            return

        def _run():
            try:
                # Escape single quotes for PowerShell
                safe_text = text.replace("'", "''")
                ps_command = (
                    "[void] [Reflection.Assembly]::LoadWithPartialName('System.Speech');"
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                    "$s.Rate = 0;"
                    f"$s.Speak('{safe_text}');"
                )
                subprocess.Popen(
                    [
                        "powershell",
                        "-NoLogo",
                        "-NonInteractive",
                        "-Command",
                        ps_command,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                print(f"TTS error: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    # Mouse callback to move crosshair with the cursor
    def on_mouse(event, x, y, flags, param):
        nonlocal crosshair_x, crosshair_y
        if event == cv2.EVENT_MOUSEMOVE or event == cv2.EVENT_LBUTTONDOWN:
            crosshair_x = int(np.clip(x, crosshair_size, width - crosshair_size))
            crosshair_y = int(np.clip(y, crosshair_size, height - crosshair_size))

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setMouseCallback(window_name, on_mouse)

    print("Gaze (if calibrated) or Arrows/Mouse = Move crosshair | A = Save+Describe | Q = Quit")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not read frame")
            break

        display_frame = frame.copy()

        # =========================
        # Update crosshair from gaze (if calibration + pupil camera available)
        # =========================
        if mapping_params is not None and cap_pupil is not None:
            ret_p, frame_pupil = cap_pupil.read()
            if ret_p:
                # Match calibration pipeline: flip pupil frame vertically
                frame_pupil_flipped = cv2.flip(frame_pupil, 0)
                try:
                    results_pupil = pupil_model.predict(
                        source=frame_pupil_flipped,
                        device=yolo_device,
                        conf=0.8,
                        verbose=False,
                    )
                    pupil_x, pupil_y = None, None
                    for box in results_pupil[0].boxes:
                        x1, y1, x2, y2 = box.xyxy[0]
                        pupil_x = int((x1 + x2) / 2)
                        pupil_y = int((y1 + y2) / 2)
                        break

                    if pupil_x is not None and pupil_y is not None:
                        gx, gy = map_pupil_to_world(pupil_x, pupil_y)
                        if gx is not None and gy is not None:
                            gx_int = int(np.clip(gx, crosshair_size, width - crosshair_size))
                            gy_int = int(np.clip(gy, crosshair_size, height - crosshair_size))
                            crosshair_x = gx_int
                            crosshair_y = gy_int
                except Exception as e:
                    # If gaze pipeline fails, keep previous crosshair and continue
                    print(f"Gaze update error: {e}")

        # Continuously segment at crosshair position when enabled
        if segment_enabled:
            results = sam_model.predict(frame, points=[[crosshair_x, crosshair_y]], labels=[1], verbose=False)
            
            if results and results[0].masks is not None and len(results[0].masks.data) > 0:
                current_mask = results[0].masks.data[0].cpu().numpy()
            else:
                current_mask = None

        # Draw the segmentation mask overlay
        if current_mask is not None and segment_enabled:
            # Resize mask to frame size if needed
            mask_resized = cv2.resize(current_mask.astype(np.uint8), 
                                      (frame.shape[1], frame.shape[0]))
            
            # Create colored overlay (semi-transparent green)
            overlay = display_frame.copy()
            overlay[mask_resized > 0] = [0, 255, 0]
            
            # Blend with original
            display_frame = cv2.addWeighted(display_frame, 0.6, overlay, 0.4, 0)
            
            # Draw contour
            contours, _ = cv2.findContours(mask_resized, cv2.RETR_EXTERNAL, 
                                           cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(display_frame, contours, -1, (0, 255, 0), 2)
            
            # Draw flashing circle above the segmented object
            # Calculate flashing state based on time
            elapsed_time = time.time() - start_time
            flash_cycle = elapsed_time * flash_frequency
            is_visible = (flash_cycle % 1.0) < 0.5  # On for 50% of cycle, off for 50%
            
            if is_visible:
                # Find bounding box of the mask to position circle
                y_coords, x_coords = np.where(mask_resized > 0)
                
                if len(x_coords) > 0 and len(y_coords) > 0:
                    # Get top center of the bounding box
                    x_center = int((x_coords.min() + x_coords.max()) / 2)
                    y_top = y_coords.min()
                    
                    # Position circle above the object
                    circle_x = x_center
                    circle_y = max(circle_radius, y_top - circle_offset_y)
                    
                    # Draw filled red circle
                    cv2.circle(display_frame, (circle_x, circle_y), circle_radius, 
                              (0, 0, 255), -1)  # -1 for filled circle
                    
                    # Optional: Add white outline for better visibility
                    cv2.circle(display_frame, (circle_x, circle_y), circle_radius, 
                              (255, 255, 255), 2)

        # Draw crosshair
        crosshair_color = (0, 255, 255) if segment_enabled else (128, 128, 128)
        # Horizontal line
        cv2.line(display_frame, 
                (crosshair_x - crosshair_size, crosshair_y), 
                (crosshair_x + crosshair_size, crosshair_y), 
                crosshair_color, 2)
        # Vertical line
        cv2.line(display_frame, 
                (crosshair_x, crosshair_y - crosshair_size), 
                (crosshair_x, crosshair_y + crosshair_size), 
                crosshair_color, 2)
        # Center dot
        cv2.circle(display_frame, (crosshair_x, crosshair_y), 3, crosshair_color, -1)

        # Draw Gemini response overlay if recent
        if last_gemini_text and (time.time() - last_gemini_time) <= gemini_display_seconds:
            cv2.putText(display_frame, f"Gemini: {last_gemini_text}",
                        (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # Draw instructions
        status = "SEGMENTING" if segment_enabled else "PAUSED"
        status_color = (0, 255, 0) if segment_enabled else (128, 128, 128)
        cv2.putText(display_frame, status, 
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
        cv2.putText(display_frame, f"Crosshair: ({crosshair_x}, {crosshair_y})", 
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(display_frame, "Arrows/Mouse=Move | A=Save+Describe | Q=Quit", 
                    (10, height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Show the frame
        cv2.imshow(window_name, display_frame)

        # Handle key presses
        key = cv2.waitKey(1) & 0xFF
        
        # Debug: print key code (comment out after testing)
        if key != 255:
            print(f"Key pressed: {key}")
        
        if key == ord('q'):
            break
        elif key == ord('a') or key == ord('A'):  # A key saves image with red box
            if current_mask is not None:
                # Copy the original frame
                output_image = frame.copy()
                
                # Resize mask to frame size
                mask_resized = cv2.resize(current_mask.astype(np.uint8), 
                                         (frame.shape[1], frame.shape[0]))
                
                # Find bounding box of the mask
                y_coords, x_coords = np.where(mask_resized > 0)
                
                if len(x_coords) > 0 and len(y_coords) > 0:
                    # Get bounding box coordinates
                    x_min, x_max = x_coords.min(), x_coords.max()
                    y_min, y_max = y_coords.min(), y_coords.max()
                    
                    # Add padding (20 pixels on each side)
                    padding = 20
                    x_min = max(0, x_min - padding)
                    y_min = max(0, y_min - padding)
                    x_max = min(frame.shape[1], x_max + padding)
                    y_max = min(frame.shape[0], y_max + padding)
                    
                    # Draw red rectangle (BGR format, so red is (0, 0, 255))
                    cv2.rectangle(output_image, (x_min, y_min), (x_max, y_max), 
                                 (0, 0, 255), 3)
                    
                    # Create output directory if it doesn't exist
                    os.makedirs("segmented_outputs", exist_ok=True)
                    
                    # Generate filename with timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"segmented_outputs/boxed_{timestamp}.png"
                    
                    # Save the image
                    cv2.imwrite(filename, output_image)
                    print(f"Saved: {filename}")

                    # Send to Gemini for a short description
                    if gemini_enabled and gemini_model is not None:
                        try:
                            prompt = "What is in the red box? Reply in a few words."
                            image = Image.open(filename)
                            response = gemini_model.generate_content([prompt, image])
                            if response and response.text:
                                last_gemini_text = response.text.strip()
                                last_gemini_time = time.time()
                                print(f"Gemini: {last_gemini_text}")
                                # Speak the response out loud (non-blocking)
                                speak_text_async(last_gemini_text)
                            else:
                                print("Gemini: No response text.")
                        except Exception as e:
                            print(f"Gemini error: {e}")
                    else:
                        print("Gemini disabled: set GEMINI_API_KEY to enable captions.")
                else:
                    print("No valid mask to create box!")
            else:
                print("No object segmented to save!")
        # Arrow keys
        elif key == 82 or key == 0:  # Up arrow
            crosshair_y = max(crosshair_size, crosshair_y - move_step)
        elif key == 84 or key == 1:  # Down arrow
            crosshair_y = min(height - crosshair_size, crosshair_y + move_step)
        elif key == 81 or key == 2:  # Left arrow
            crosshair_x = max(crosshair_size, crosshair_x - move_step)
        elif key == 83 or key == 3:  # Right arrow
            crosshair_x = min(width - crosshair_size, crosshair_x + move_step)

    cap.release()
    if cap_pupil is not None:
        cap_pupil.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopping...")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

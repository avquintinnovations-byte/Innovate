from ultralytics import SAM
import cv2
import numpy as np
import torch
from datetime import datetime
import os
import time
import google.generativeai as genai
from PIL import Image

# Set your Gemini API key in an environment variable named GEMINI_API_KEY.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyC4pPfmcWzN98BNg-EPCyYqv0GpPxy_MKw")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

def main():
    # Check if CUDA is available
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"Using device: {device}")
    
    if device == 'cpu':
        print("WARNING: CUDA not available, running on CPU (will be slow)")
    
    print("Loading SAM2 model...")
    sam_model = SAM("sam2.1_s.pt")
    sam_model.to(device)  # Move model to CUDA if available

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

    # Open camera
    cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        print("Error: Could not open camera")
        return

    # Get frame dimensions
    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read frame")
        return
    
    height, width = frame.shape[:2]
    
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

    # Mouse callback to move crosshair with the cursor
    def on_mouse(event, x, y, flags, param):
        nonlocal crosshair_x, crosshair_y
        if event == cv2.EVENT_MOUSEMOVE or event == cv2.EVENT_LBUTTONDOWN:
            crosshair_x = int(np.clip(x, crosshair_size, width - crosshair_size))
            crosshair_y = int(np.clip(y, crosshair_size, height - crosshair_size))

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setMouseCallback(window_name, on_mouse)

    print("Arrows or Mouse = Move crosshair | A = Save+Describe | Q = Quit")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not read frame")
            break

        display_frame = frame.copy()

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

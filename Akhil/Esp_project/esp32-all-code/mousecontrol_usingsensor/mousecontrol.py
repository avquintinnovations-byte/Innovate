import serial
import pyautogui
import time
import sys

# Configuration
SERIAL_PORT = 'COM9'  # Change this to your ESP32's COM port (e.g., COM3, COM4 on Windows)
BAUD_RATE = 115200
ANGLE_RANGE = 40.0  # Angle range in degrees (±40°)
SMOOTHING = 0.5  # Smoothing factor (0 = no smoothing, 1 = maximum smoothing)

# Disable PyAutoGUI's failsafe (DISABLED - use Ctrl+C to stop)
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0  # Remove delay between PyAutoGUI calls for faster response

def map_angle_to_position(angle, screen_dimension, angle_range=ANGLE_RANGE):
    """
    Map angle to absolute screen position
    Angles are constrained to ±angle_range degrees
    -angle_range maps to 0, +angle_range maps to screen_dimension
    """
    # Constrain angle to the specified range
    angle = max(-angle_range, min(angle_range, angle))
    
    # Normalize angle from [-angle_range, +angle_range] to [0, 1]
    normalized = (angle + angle_range) / (2 * angle_range)
    
    # Map to screen position
    position = int(normalized * screen_dimension)
    
    # Ensure position is within screen bounds
    return max(0, min(screen_dimension - 1, position))

def main():
    print("IMU Mouse Controller - Absolute Position Mode")
    print("=" * 50)
    print(f"Tilt ±{ANGLE_RANGE}° to move cursor across screen")
    print(f"Connecting to {SERIAL_PORT} at {BAUD_RATE} baud...")
    
    try:
        # Open serial connection
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)  # Wait for connection to stabilize
        
        # Clear the initial buffer (discard first few readings)
        for _ in range(10):
            ser.readline()
        
        print("Connected! Calibrating yaw reference...")
        
        # Calibrate - get initial yaw and pitch values
        reference_yaw = 0
        reference_pitch = 0
        calibration_samples = 0
        
        for _ in range(30):
            line = ser.readline().decode('utf-8').strip()
            if line and ',' in line:
                parts = line.split(',')
                if len(parts) == 2:
                    try:
                        reference_yaw += float(parts[0])
                        reference_pitch += float(parts[1])
                        calibration_samples += 1
                    except ValueError:
                        continue
            time.sleep(0.02)
        
        if calibration_samples > 0:
            reference_yaw /= calibration_samples
            reference_pitch /= calibration_samples
        
        print(f"Calibration complete! Reference Yaw: {reference_yaw:.2f}°, Pitch: {reference_pitch:.2f}°")
        print("Press Ctrl+C to stop (failsafe disabled)")
        print(f"Angle Range: ±{ANGLE_RANGE}° | Smoothing: {SMOOTHING}")
        print("-" * 50)
        
        # Get screen size
        screen_width, screen_height = pyautogui.size()
        
        # Smoothing variables for absolute positions
        smooth_x = screen_width // 2
        smooth_y = screen_height // 2
        
        # Additional yaw smoothing for drift compensation
        smooth_yaw = 0.0
        smooth_pitch = 0.0
        
        while True:
            try:
                # Read line from serial
                line = ser.readline().decode('utf-8').strip()
                
                if line and ',' in line:
                    # Parse yaw and pitch
                    parts = line.split(',')
                    if len(parts) == 2:
                        raw_yaw = float(parts[0])
                        pitch = float(parts[1])
                        
                        # Calculate relative yaw (difference from reference)
                        relative_yaw = raw_yaw - reference_yaw
                        
                        # Handle yaw wraparound (-180 to +180)
                        if relative_yaw > 180:
                            relative_yaw -= 360
                        elif relative_yaw < -180:
                            relative_yaw += 360
                        
                        # Calculate relative pitch
                        relative_pitch = pitch - reference_pitch
                        
                        # Apply smoothing to angles to reduce jitter
                        smooth_yaw = smooth_yaw * SMOOTHING + relative_yaw * (1 - SMOOTHING)
                        smooth_pitch = smooth_pitch * SMOOTHING + relative_pitch * (1 - SMOOTHING)
                        
                        # Map angles to absolute screen positions
                        # Yaw (rotation) controls horizontal (X) position (inverted for natural feel)
                        # Pitch (tilt) controls vertical (Y) position (flipped)
                        target_x = map_angle_to_position(-smooth_yaw, screen_width)
                        target_y = map_angle_to_position(smooth_pitch, screen_height)
                        
                        # Apply additional smoothing to the final positions for smoother cursor movement
                        smooth_x = smooth_x * 0.3 + target_x * 0.7
                        smooth_y = smooth_y * 0.3 + target_y * 0.7
                        
                        # Get final integer positions
                        new_x = int(smooth_x)
                        new_y = int(smooth_y)
                        
                        # Move mouse to absolute position
                        pyautogui.moveTo(new_x, new_y, duration=0)
                        print(f"Yaw: {smooth_yaw:6.2f}° | Pitch: {smooth_pitch:6.2f}° | "
                              f"Position: ({new_x:4d}, {new_y:4d}) | "
                              f"Screen: ({screen_width}x{screen_height})", end='\r')
                
            except ValueError:
                # Skip malformed lines
                continue
            except KeyboardInterrupt:
                print("\n\nStopping mouse controller...")
                break
    
    except serial.SerialException as e:
        print(f"\nError: Could not open serial port {SERIAL_PORT}")
        print(f"Details: {e}")
        print("\nAvailable COM ports:")
        print("Run this command to list ports: python -m serial.tools.list_ports")
        sys.exit(1)
    
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
    
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Serial connection closed.")

if __name__ == "__main__":
    main()
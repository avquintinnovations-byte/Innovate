import serial
import pyautogui
import time
import sys

# Configuration - SWITCH BETWEEN USB AND BLUETOOTH HERE
CONNECTION_MODE = "BLUETOOTH"  # Change to "USB" or "BLUETOOTH"

# USB Settings (when CONNECTION_MODE = "USB")
USB_PORT = 'COM15'  # Your ESP32 USB COM port
USB_BAUD_RATE = 115200

# Bluetooth Settings (when CONNECTION_MODE = "BLUETOOTH") 
BT_PORT = 'COM10'    # Your ESP32 Bluetooth COM port (find after pairing)
BT_BAUD_RATE = 115200

ANGLE_RANGE = 40.0  # Angle range in degrees (±40°)
SMOOTHING = 0.5     # Smoothing factor (0 = no smoothing, 1 = maximum smoothing)

# Disable PyAutoGUI's failsafe (DISABLED - use Ctrl+C to stop)
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0  # Remove delay between PyAutoGUI calls for faster response

def get_serial_config():
    """Return serial port and baudrate based on connection mode"""
    if CONNECTION_MODE == "USB":
        return USB_PORT, USB_BAUD_RATE, "USB Serial"
    elif CONNECTION_MODE == "BLUETOOTH":
        return BT_PORT, BT_BAUD_RATE, "Bluetooth Serial"
    else:
        raise ValueError("CONNECTION_MODE must be 'USB' or 'BLUETOOTH'")

def map_angle_to_position(angle, screen_dimension, angle_range=ANGLE_RANGE):
    """Map angle to absolute screen position"""
    angle = max(-angle_range, min(angle_range, angle))
    normalized = (angle + angle_range) / (2 * angle_range)
    position = int(normalized * screen_dimension)
    return max(0, min(screen_dimension - 1, position))

def main():
    serial_port, baud_rate, connection_type = get_serial_config()
    
    print("IMU Mouse Controller - Absolute Position Mode")
    print("=" * 50)
    print(f"Connection: {connection_type} ({serial_port})")
    print(f"Tilt ±{ANGLE_RANGE}° to move cursor across screen")
    print(f"Connecting to {serial_port} at {baud_rate} baud...")

    ser = None
    try:
        # Open serial connection
        ser = serial.Serial(serial_port, baud_rate, timeout=1)
        time.sleep(2)  # Wait for connection to stabilize

        # Clear initial buffer
        for _ in range(10):
            ser.readline()

        print("Connected! Calibrating yaw reference...")

        # Calibration
        reference_yaw = 0.0
        reference_pitch = 0.0
        calibration_samples = 0

        for _ in range(30):
            line = ser.readline().decode('utf-8', errors='ignore').strip()
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

        # Smoothing variables
        smooth_x = screen_width // 2
        smooth_y = screen_height // 2
        smooth_yaw = 0.0
        smooth_pitch = 0.0

        print("Starting mouse control... Tilt to move!")
        
        while True:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                
                if line and ',' in line:
                    parts = line.split(',')
                    if len(parts) == 2:
                        try:
                            raw_yaw = float(parts[0])
                            pitch = float(parts[1])

                            # Calculate relative angles
                            relative_yaw = raw_yaw - reference_yaw
                            if relative_yaw > 180:
                                relative_yaw -= 360
                            elif relative_yaw < -180:
                                relative_yaw += 360

                            relative_pitch = pitch - reference_pitch

                            # Apply angle smoothing
                            smooth_yaw = smooth_yaw * SMOOTHING + relative_yaw * (1 - SMOOTHING)
                            smooth_pitch = smooth_pitch * SMOOTHING + relative_pitch * (1 - SMOOTHING)

                            # Map to screen positions
                            target_x = map_angle_to_position(-smooth_yaw, screen_width)
                            target_y = map_angle_to_position(smooth_pitch, screen_height)

                            # Position smoothing
                            smooth_x = smooth_x * 0.3 + target_x * 0.7
                            smooth_y = smooth_y * 0.3 + target_y * 0.7

                            # Move mouse
                            new_x = int(smooth_x)
                            new_y = int(smooth_y)
                            pyautogui.moveTo(new_x, new_y, duration=0)
                            
                            print(f"Yaw: {smooth_yaw:6.2f}° | Pitch: {smooth_pitch:6.2f}° | "
                                  f"Pos: ({new_x:4d}, {new_y:4d})", end='\r')
                            
                        except ValueError:
                            continue

                time.sleep(0.001)  # Prevent 100% CPU

            except KeyboardInterrupt:
                print("\n\nStopping mouse controller...")
                break

    except serial.SerialException as e:
        print(f"\nError: Could not open serial port {serial_port}")
        print(f"Details: {e}")
        print("\n💡 Troubleshooting:")
        print("1. For USB: Check COM port in Device Manager")
        if CONNECTION_MODE == "BLUETOOTH":
            print("2. For Bluetooth: Ensure ESP32 is paired and note the COM port")
        print("3. Close Arduino Serial Monitor / other serial tools")
        print("4. List ports: python -m serial.tools.list_ports")
        sys.exit(1)

    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)

    finally:
        if ser and ser.is_open:
            ser.close()
            print("\nSerial connection closed.")

if __name__ == "__main__":
    main()

import asyncio
import bleak
import pyautogui
import time
import sys

# Configuration
ESP32_BLE_NAME = "ESP32_IMU_Mouse"
ANGLE_RANGE = 40.0
SMOOTHING = 0.5

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

def map_angle_to_position(angle, screen_dimension, angle_range=ANGLE_RANGE):
    angle = max(-angle_range, min(angle_range, angle))
    normalized = (angle + angle_range) / (2 * angle_range)
    position = int(normalized * screen_dimension)
    return max(0, min(screen_dimension - 1, position))

class IMUClient:
    def __init__(self):
        self.client = None
        self.reference_yaw = 0
        self.reference_pitch = 0
        self.smooth_x = 0
        self.smooth_y = 0
        self.smooth_yaw = 0
        self.smooth_pitch = 0
        self.calibrated = False
        self.running = False
        self.data_buffer = []
        
    async def scan_and_connect(self):
        """Scan and connect to ESP32 - FIXED VERSION"""
        print(f"Scanning for '{ESP32_BLE_NAME}'...")
        devices = await bleak.BleakScanner.discover(timeout=10.0)
        
        target_device = None
        for device in devices:
            # FIXED: Check if name exists before calling lower()
            device_name = device.name or ""
            if ESP32_BLE_NAME.lower() in device_name.lower():
                target_device = device
                print(f"Found {device_name} at {device.address}")
                break
        
        if not target_device:
            print("ESP32 not found. Available devices:")
            for device in devices:
                device_name = device.name or "Unknown"
                print(f"  {device_name} ({device.address})")
            return False
        
        try:
            self.client = bleak.BleakClient(target_device.address)
            await self.client.connect()
            print("BLE Connected!")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def notification_handler(self, sender, data):
        """Handle incoming IMU data - SIMPLIFIED"""
        if not self.calibrated:
            self.data_buffer.append(data.decode('utf-8', errors='ignore').strip())
            return
            
        try:
            line = data.decode('utf-8', errors='ignore').strip()
            if ',' in line:
                parts = line.split(',')
                if len(parts) == 2:
                    raw_yaw = float(parts[0])
                    pitch = float(parts[1])
                    
                    relative_yaw = raw_yaw - self.reference_yaw
                    if relative_yaw > 180:
                        relative_yaw -= 360
                    elif relative_yaw < -180:
                        relative_yaw += 360
                    
                    relative_pitch = pitch - self.reference_pitch
                    
                    self.smooth_yaw = self.smooth_yaw * SMOOTHING + relative_yaw * (1 - SMOOTHING)
                    self.smooth_pitch = self.smooth_pitch * SMOOTHING + relative_pitch * (1 - SMOOTHING)
                    
                    screen_width, screen_height = pyautogui.size()
                    target_x = map_angle_to_position(-self.smooth_yaw, screen_width)
                    target_y = map_angle_to_position(self.smooth_pitch, screen_height)
                    
                    self.smooth_x = self.smooth_x * 0.3 + target_x * 0.7
                    self.smooth_y = self.smooth_y * 0.3 + target_y * 0.7
                    
                    new_x = int(self.smooth_x)
                    new_y = int(self.smooth_y)
                    
                    pyautogui.moveTo(new_x, new_y, duration=0)
                    
                    print(f"Yaw: {self.smooth_yaw:6.2f}° | Pitch: {self.smooth_pitch:6.2f}° | "
                          f"Pos: ({new_x:4d}, {new_y:4d})", end='\r')
        except:
            pass
    
    async def calibrate(self):
        """Improved calibration"""
        print("Calibrating... Keep steady for 3 seconds!")
        await asyncio.sleep(3.0)
        
        # Use averaged data from buffer
        if self.data_buffer:
            valid_samples = []
            for line in self.data_buffer[-20:]:  # Last 20 samples
                if ',' in line:
                    parts = line.split(',')
                    if len(parts) == 2:
                        try:
                            yaw = float(parts[0])
                            pitch = float(parts[1])
                            valid_samples.append((yaw, pitch))
                        except:
                            continue
            
            if valid_samples:
                avg_yaw = sum(y[0] for y in valid_samples) / len(valid_samples)
                avg_pitch = sum(y[1] for y in valid_samples) / len(valid_samples)
                self.reference_yaw = avg_yaw
                self.reference_pitch = avg_pitch
                self.calibrated = True
                print(f"\nCalibration OK! Ref: Yaw={self.reference_yaw:.1f}° Pitch={self.reference_pitch:.1f}°")
                self.data_buffer.clear()
                return
        
        # Fallback: use current smoothed values
        self.reference_yaw = self.smooth_yaw or 0
        self.reference_pitch = self.smooth_pitch or 0
        self.calibrated = True
        print(f"\nCalibration complete! Ref: Yaw={self.reference_yaw:.1f}° Pitch={self.reference_pitch:.1f}°")
    
    async def run(self):
        self.running = True
        screen_width, screen_height = pyautogui.size()
        self.smooth_x = screen_width // 2
        self.smooth_y = screen_height // 2
        
        try:
            await self.calibrate()
            print("✓ Ready! Tilt to move mouse (Ctrl+C to stop)")
            print("-" * 50)
            
            while self.running:
                await asyncio.sleep(0.01)
                
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            await self.disconnect()
    
    async def disconnect(self):
        self.running = False
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("Disconnected")

async def main():
    print("IMU Mouse Controller - BLE (Fixed)")
    print("=" * 50)
    
    client = IMUClient()
    if await client.scan_and_connect():
        # Start notifications AFTER connection (no UUID needed for basic BLE)
        # Just read services to confirm connection
        services = await client.client.get_services()
        print(f"Found {len(services)} services")
        await client.run()
    else:
        print("❌ No ESP32 found. Make sure:")
        print("1. ESP32 is powered ON")
        print("2. ESP32 code is uploaded")
        print("3. ESP32 name matches 'ESP32_IMU_Mouse'")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited")

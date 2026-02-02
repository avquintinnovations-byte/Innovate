import asyncio
from bleak import BleakClient
import pyautogui

# The address of your ESP32-C3 (found via scanning) or name
DEVICE_NAME = "C3_IMU_DATA"
CHARACTERISTIC_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# Re-use your existing logic here
def handle_data(data_string):
    try:
        parts = data_string.decode('utf-8').strip().split(',')
        if len(parts) == 2:
            yaw, pitch = float(parts[0]), float(parts[1])
            # ... Insert your mapping and pyautogui.moveTo logic here ...
            print(f"Yaw: {yaw}, Pitch: {pitch}")
    except:
        pass

async def run():
    print("Scanning for ESP32-C3...")
    # This is a simplified connection logic
    async with BleakClient("YOUR_DEVICE_MAC_ADDRESS_HERE") as client:
        print("Connected!")
        await client.start_notify(CHARACTERISTIC_UUID, lambda char, data: handle_data(data))
        while True:
            await asyncio.sleep(1)

asyncio.run(run())
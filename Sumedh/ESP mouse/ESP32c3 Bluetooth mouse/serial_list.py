import serial.tools.list_ports

print("Available Serial Ports:")
print("=" * 60)

ports = serial.tools.list_ports.comports()

if not ports:
    print("No serial ports found!")
else:
    for i, port in enumerate(ports, 1):
        print(f"{i:2d}. {port.device:10s} | {port.description}")
        print(f"     HWID: {port.hwid}")
        print()

print("\n💡 Look for:")
print("- 'Bluetooth' or 'Standard Serial over Bluetooth link'")
print("- Your ESP32 USB port (e.g., 'Silicon Labs CP210x', 'CH340', etc.)")

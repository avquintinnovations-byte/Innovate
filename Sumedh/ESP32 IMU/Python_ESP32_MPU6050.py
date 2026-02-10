import serial
import time
import serial.tools.list_ports
import socket

# --- CONFIGURATION ---
SERIAL_PORT = 'COM17' 
BAUD_RATE = 115200

# UDP Destination (Where the data is going)
UDP_IP = "192.168.1.58" 
UDP_PORT = 4210

def find_ports():
    ports = serial.tools.list_ports.comports()
    print("Available ports:")
    for port in ports:
        print(f"- {port.device}")

# Initialize UDP Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

try:
    # Initialize Serial Connection
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    
    # Reset ESP32/Arduino to sync stream
    ser.setDTR(False)
    time.sleep(0.1)
    ser.setDTR(True)

    print(f"Connected to {SERIAL_PORT}.")
    print(f"Forwarding data to {UDP_IP}:{UDP_PORT} via UDP...")

    while True:
        if ser.in_waiting > 0:
            try:
                # Read line from serial
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                
                if line:
                    # Print locally for debugging
                    print(f"Serial Data: {line}")
                    
                    # Send over UDP
                    sock.sendto(line.encode('utf-8'), (UDP_IP, UDP_PORT))
                    
            except Exception as e:
                print(f"Data error: {e}")

except serial.SerialException as e:
    print(f"\n[ERROR] Could not open {SERIAL_PORT}.")
    find_ports()

except KeyboardInterrupt:
    print("\nClosing connections...")
finally:
    if 'ser' in locals() and ser.is_open:
        ser.close()
    sock.close()
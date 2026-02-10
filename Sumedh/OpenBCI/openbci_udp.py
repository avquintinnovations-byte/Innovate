import socket
import time
import json
import sys

# Set up UDP listening server
UDP_IP = "127.0.0.1"
UDP_PORT = 5555
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print(f"Listening for data on {UDP_IP}:{UDP_PORT}...")
print("EMG threshold: 0.81262234 | Single-line updates")
print(" " * 80)  # Reserve space for live updates

threshold = 0.81262234
last_print = 0
print_interval = 0.1  # 100ms updates - smooth but readable

try:
    while True:
        data, addr = sock.recvfrom(1024)
        now = time.time()
        
        # Only update display every 100ms to prevent flicker
        if now - last_print < print_interval:
            continue
            
        # Decode and parse JSON data
        try:
            json_data = json.loads(data.decode())
        except json.JSONDecodeError:
            continue

        current_data = json_data.get("data", [])
        if not current_data or len(current_data) < 3:
            continue

        # Check threshold and prepare output
        if current_data[2] > threshold:
            output = f"🎯 HELLO WORLD - EMG Ch3: {current_data[2]:.6f} > {threshold}"
        else:
            output = f"EMG Ch3: {current_data[2]:.6f} | From {addr[1]} | {data.decode()[-60:]}"

        # CLEAR & REPLACE single line (FIXED)
        print(f"\r{' ' * 100}\r{output}", end="")  # Clear 100 chars then print new
        sys.stdout.flush()
        last_print = now

except KeyboardInterrupt:
    print("\n\nStream stopped by user.")
finally:
    sock.close()

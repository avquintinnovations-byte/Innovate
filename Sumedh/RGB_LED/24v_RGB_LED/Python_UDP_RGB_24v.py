import socket
import serial
import time
import threading
import sys

# --- Configuration ---
# 1. Serial Settings
SERIAL_PORT = "COM17"   # CHECK YOUR PORT!
BAUD_RATE = 115200

# 2. UDP Listening (Incoming commands TO ESP32)
LISTEN_IP = "0.0.0.0"   # Listen on all available network interfaces
LISTEN_PORT = 4210      # Port others use to send color data to you

# 3. UDP Sending (Outgoing data FROM ESP32)
# Change "127.0.0.1" to the specific IP of the user you want to send to,
# or use "255.255.255.255" to broadcast it to the whole network.
DEST_IP = "192.168.1.58"   
DEST_PORT = 4211        # Port where the output data will be sent

# Global serial object
ser = None

def serial_reader_thread():
    """
    Thread A: Reads data FROM ESP32 and broadcasts it over UDP.
    """
    global ser
    print(f"[Thread] Serial Reader Started. Sending to {DEST_IP}:{DEST_PORT}")
    
    # Create a dedicated socket for sending data
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Enable broadcast if you are using 255.255.255.255
    if DEST_IP == "255.255.255.255":
        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    try:
        while True:
            if ser and ser.is_open:
                try:
                    # Read line from ESP32
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    
                    if line:
                        # 1. Print locally for your own debugging
                        print(f"{line}") 
                        
                        # 2. Transmit over UDP
                        send_sock.sendto(line.encode('utf-8'), (DEST_IP, DEST_PORT))
                        
                except Exception as e:
                    print(f"Serial Read Error: {e}")
                    break
    except KeyboardInterrupt:
        pass
    finally:
        send_sock.close()

def udp_listener_thread():
    """
    Thread B: Listens for UDP packets and forwards them TO the ESP32.
    """
    global ser
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, UDP_PORT))
    
    print(f"[Thread] UDP Listener Active on Port {UDP_PORT}")
    
    try:
        while True:
            data, addr = sock.recvfrom(1024) 
            message = data.decode('utf-8').strip()
            
            print(f"\n[UDP] Received '{message}' from {addr}")

            if ser and ser.is_open:
                command = f"{message}\n"
                ser.write(command.encode('utf-8'))
                print(f"[UDP] Forwarded color to ESP32")
                
    except Exception as e:
        print(f"UDP Error: {e}")
    finally:
        sock.close()

def main():
    global ser
    
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2) 
        print(f"Connected to Serial: {SERIAL_PORT}")
    except Exception as e:
        print(f"Could not open Serial port {SERIAL_PORT}: {e}")
        return

    t_serial = threading.Thread(target=serial_reader_thread, daemon=True)
    t_udp = threading.Thread(target=udp_listener_thread, daemon=True)

    t_serial.start()
    t_udp.start()

    print("Gateway Running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        if ser:
            ser.close()
        sys.exit()

if __name__ == "__main__":
    UDP_PORT = 4210 # Ensuring local variable matches config
    main()
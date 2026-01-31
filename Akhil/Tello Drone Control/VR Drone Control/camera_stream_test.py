from djitellopy import Tello
import time
import socket
import threading

# ----------------------------
# Stream config
# ----------------------------
UDP_PORT = 5000
UDP_HOST = "127.0.0.1"
TELLO_VIDEO_PORT = 11111
BUFFER_SIZE = 65536  # 64KB buffer for UDP packets

def main():

    # ----------------------------
    # Tello
    # ----------------------------
    tello = Tello()
    print("Connecting to drone...")
    tello.connect()
    print("Battery:", tello.get_battery(), "%")

    print("\nStarting video stream...")
    print("Note: The Tello will stream H.264 video to UDP port 11111")
    tello.streamon()
    
    # Wait for stream to start (Tello needs a moment to begin streaming)
    print("Waiting for stream to start...")
    time.sleep(3)
    
    # ----------------------------
    # Direct UDP relay (zero-latency packet forwarding)
    # ----------------------------
    # Create UDP sockets
    # Input: receive from Tello on port 11111
    # Output: forward to port 5000
    
    print(f"\nSetting up direct UDP relay (zero processing overhead)...")
    
    # Socket to receive from Tello
    recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
    recv_socket.bind(('0.0.0.0', TELLO_VIDEO_PORT))
    recv_socket.settimeout(1.0)  # 1 second timeout for checking stop condition
    
    # Socket to forward to receiver
    send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)
    
    packet_count = 0
    bytes_relayed = 0
    relay_active = True
    
    # Relay thread
    def udp_relay():
        nonlocal packet_count, bytes_relayed, relay_active
        print("UDP relay thread started")
        
        while relay_active:
            try:
                # Receive packet from Tello (blocking with timeout)
                data, addr = recv_socket.recvfrom(BUFFER_SIZE)
                
                # Forward immediately to output port (zero processing)
                send_socket.sendto(data, (UDP_HOST, UDP_PORT))
                
                packet_count += 1
                bytes_relayed += len(data)
                
            except socket.timeout:
                # Timeout is normal, just continue
                continue
            except Exception as e:
                if relay_active:  # Only print if we haven't stopped intentionally
                    print(f"[Relay] Error: {e}")
                break
        
        print("UDP relay thread stopped")
    
    # Start relay thread
    relay_thread = threading.Thread(target=udp_relay, daemon=True)
    relay_thread.start()
    
    # Give relay a moment to start
    time.sleep(0.5)
    
    print(f"Direct UDP relay active!")
    print(f"Tello H.264 (UDP:{TELLO_VIDEO_PORT}) -> Direct Forward (UDP:{UDP_PORT})")
    print("\nZERO OVERHEAD MODE:")
    print("  - Raw packet forwarding (no processing)")
    print("  - No compression/decompression")
    print("  - No buffering or delays")
    print("  - Same quality as Tello's original stream")
    print("\nYour GStreamer receiver can now connect with:")
    print(f"  gst-launch-1.0 udpsrc port={UDP_PORT} \\")
    print("    ! h264parse ! avdec_h264 \\")
    print("    ! videoconvert ! autovideosink sync=false")
    print("\nStreaming in progress...")
    print("Press Ctrl+C to stop.\n")

    # ----------------------------
    # Main loop - Monitor relay and wait for Ctrl+C
    # ----------------------------
    start_time = time.time()
    last_packet_count = 0
    
    try:
        while True:
            time.sleep(5)
            
            # Check if relay thread is still alive
            if not relay_thread.is_alive():
                print("\nWARNING: Relay thread died unexpectedly!")
                break
            
            # Print status
            runtime = int(time.time() - start_time)
            packets_per_sec = (packet_count - last_packet_count) / 5.0
            mbps = (bytes_relayed * 8) / (runtime * 1_000_000) if runtime > 0 else 0
            
            print(f"[{runtime}s] Battery: {tello.get_battery()}% | "
                  f"Packets: {packet_count} ({packets_per_sec:.1f}/s) | "
                  f"Data: {bytes_relayed / 1_000_000:.1f} MB ({mbps:.2f} Mbps)")
            
            last_packet_count = packet_count
                
    except KeyboardInterrupt:
        print("\n\nStopping stream (Ctrl+C detected)...")

    # ----------------------------
    # Cleanup
    # ----------------------------
    print("\nCleaning up...")
    
    # Stop relay thread
    relay_active = False
    print("Stopping UDP relay...")
    relay_thread.join(timeout=2)
    
    # Close sockets
    recv_socket.close()
    send_socket.close()
    
    print("Stopping Tello video stream...")
    tello.streamoff()
    tello.end()
    
    print(f"\nSession stats:")
    print(f"  Total packets relayed: {packet_count}")
    print(f"  Total data relayed: {bytes_relayed / 1_000_000:.2f} MB")
    print("Done. Drone disconnected.")


if __name__ == "__main__":
    main()

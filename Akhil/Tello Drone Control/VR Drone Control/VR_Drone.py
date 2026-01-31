from djitellopy import Tello
import time
import socket
import threading

# ----------------------------
# UDP config
# ----------------------------
YAW_UDP_IP = "0.0.0.0"  # Listen on all interfaces for yaw input
YAW_UDP_PORT = 5000      # Port to receive yaw values on

VELOCITY_UDP_IP = "0.0.0.0"  # Listen for velocity control
VELOCITY_UDP_PORT = 5005     # Port to receive velocity commands (4-digit format)

COMMAND_UDP_IP = "0.0.0.0"   # Listen for takeoff/land commands
COMMAND_UDP_PORT = 5015      # Port to receive flight commands

STREAM_UDP_HOST = "127.0.0.1"  # Where to send camera stream
STREAM_UDP_PORT = 5001         # Port to forward camera stream to (for GStreamer/Unity)

TELLO_VIDEO_PORT = 11111  # Tello's video output port
BUFFER_SIZE = 65536       # 64KB buffer for UDP packets

# ----------------------------
# Rates (IMPORTANT)
# ----------------------------
CONTROL_HZ = 40
RC_HZ = 20
YAW_HZ = 20

# ----------------------------
# PID (for yaw control)
# ----------------------------
KP = 0.6
KI = 0.0
KD = 0.3

MAX_SPEED = 80
MIN_SPEED = 12
DEADBAND = 1.0

CMD_SMOOTHING = 0.3
MAX_CMD_STEP = 6
INTEGRAL_LIMIT = 120

# ----------------------------
# Velocity Control
# ----------------------------
BASE_VELOCITY = 20  # Base velocity for directional movement

# ----------------------------
# Angle unwrap
# ----------------------------
def unwrap_angle(prev, current):
    d = current - prev
    if d > 180:
        current -= 360
    elif d < -180:
        current += 360
    return current


def main():
    global KP, KI, KD

    # Shared state for RC control thread
    control_state = {
        'fb_velocity': 0,
        'lr_velocity': 0,
        'yaw_cmd': 0,
        'is_flying': False,
        'running': True
    }
    state_lock = threading.Lock()

    # ----------------------------
    # UDP Socket for yaw input (non-blocking)
    # ----------------------------
    yaw_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    yaw_sock.bind((YAW_UDP_IP, YAW_UDP_PORT))
    yaw_sock.setblocking(False)  # Non-blocking mode
    print(f"Yaw UDP listener started on {YAW_UDP_IP}:{YAW_UDP_PORT}")

    # ----------------------------
    # UDP Socket for velocity control (non-blocking)
    # ----------------------------
    velocity_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    velocity_sock.bind((VELOCITY_UDP_IP, VELOCITY_UDP_PORT))
    velocity_sock.setblocking(False)  # Non-blocking mode
    print(f"Velocity UDP listener started on {VELOCITY_UDP_IP}:{VELOCITY_UDP_PORT}")

    # ----------------------------
    # UDP Socket for flight commands (non-blocking)
    # ----------------------------
    command_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    command_sock.bind((COMMAND_UDP_IP, COMMAND_UDP_PORT))
    command_sock.setblocking(False)  # Non-blocking mode
    print(f"Command UDP listener started on {COMMAND_UDP_IP}:{COMMAND_UDP_PORT}")

    # ----------------------------
    # Tello
    # ----------------------------
    tello = Tello()
    print("Connecting to drone...")
    tello.connect()
    print("Battery:", tello.get_battery(), "%")

    print("\nStarting video stream...")
    tello.streamon()
    
    # Wait for stream to start
    time.sleep(2)

    # ----------------------------
    # Video relay setup
    # ----------------------------
    print(f"\nSetting up video UDP relay...")
    
    # Socket to receive from Tello
    recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
    recv_socket.bind(('0.0.0.0', TELLO_VIDEO_PORT))
    recv_socket.settimeout(1.0)  # 1 second timeout
    
    # Socket to forward to receiver
    send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)
    
    packet_count = 0
    bytes_relayed = 0
    relay_active = True
    
    # Relay thread
    def video_relay():
        nonlocal packet_count, bytes_relayed, relay_active
        print("Video relay thread started")
        
        while relay_active:
            try:
                # Receive packet from Tello
                data, addr = recv_socket.recvfrom(BUFFER_SIZE)
                
                # Forward immediately to output port
                send_socket.sendto(data, (STREAM_UDP_HOST, STREAM_UDP_PORT))
                
                packet_count += 1
                bytes_relayed += len(data)
                
            except socket.timeout:
                continue
            except Exception as e:
                if relay_active:
                    print(f"[Video Relay] Error: {e}")
                break
        
        print("Video relay thread stopped")
    
    # Start relay thread
    relay_thread = threading.Thread(target=video_relay, daemon=True)
    relay_thread.start()
    
    print(f"Video relay active: Tello (UDP:{TELLO_VIDEO_PORT}) -> GStreamer (UDP:{STREAM_UDP_PORT})")
    print("\nYour GStreamer receiver can connect with:")
    print(f"  gst-launch-1.0 udpsrc port={STREAM_UDP_PORT} \\")
    print("    ! h264parse ! avdec_h264 \\")
    print("    ! videoconvert ! autovideosink sync=false\n")

    # ----------------------------
    # RC Control Thread (prevents drifting with continuous commands)
    # ----------------------------
    def rc_control_thread():
        """Continuously send RC commands at steady rate to keep drone stable"""
        print("[RC Control] Thread started - sending commands at 20Hz")
        last_send_time = time.time()
        
        while control_state['running']:
            now = time.time()
            
            # Rate limiting
            if now - last_send_time >= 1 / RC_HZ:
                with state_lock:
                    is_flying = control_state['is_flying']
                    fb = control_state['fb_velocity']
                    lr = control_state['lr_velocity']
                    yaw = control_state['yaw_cmd']
                
                # Only send RC commands if drone is flying
                if is_flying:
                    # Send RC control: (left_right, forward_back, up_down, yaw)
                    tello.send_rc_control(lr, fb, 0, yaw)
                
                last_send_time = now
            
            time.sleep(0.01)  # Small sleep to prevent CPU spinning
        
        # Stop the drone when thread exits
        tello.send_rc_control(0, 0, 0, 0)
        print("[RC Control] Thread stopped")
    
    # Start RC control thread
    rc_thread = threading.Thread(target=rc_control_thread, daemon=True)
    rc_thread.start()

    # ----------------------------
    # Flight state tracking
    # ----------------------------
    is_flying = False  # Track if drone is currently in the air
    
    print("\nDrone ready. Waiting for commands...")
    print("Send '1' on port 5015 to takeoff")
    print("Video stream is active")

    # ----------------------------
    # State
    # ----------------------------
    prev_raw_udp = None
    target_yaw = 0.0

    prev_raw_drone = tello.get_yaw()
    drone_yaw = prev_raw_drone

    prev_error = 0.0
    integral = 0.0
    last_cmd = 0.0

    # Velocity state
    forward_velocity = 0
    back_velocity = 0
    left_velocity = 0
    right_velocity = 0

    # Timers
    last_yaw_time = 0
    last_status_time = 0

    running = True
    
    print("\nSystem active! Video streaming to Unity/GStreamer")
    print("Send commands to control the drone:")
    print("  Port 5000: Yaw control")
    print("  Port 5005: Velocity control")
    print("  Port 5015: Flight commands (1=takeoff, 2=land)")
    print("Press Ctrl+C to stop.\n")
    
    try:
        while running:
            now = time.time()
            
            # Sleep briefly to prevent CPU spinning
            time.sleep(0.01)  # 100Hz loop is sufficient for reading UDP and computing

            # ----------------------------
            # UDP yaw input (NON-BLOCKING)
            # ----------------------------
            try:
                while True:  # Process all available packets
                    data, addr = yaw_sock.recvfrom(1024)
                    try:
                        line = data.decode().strip()
                        raw = float(line)

                        if prev_raw_udp is None:
                            prev_raw_udp = raw
                            target_yaw = raw
                        else:
                            raw = unwrap_angle(prev_raw_udp, raw)
                            target_yaw += (raw - prev_raw_udp)
                            prev_raw_udp = raw
                    except ValueError:
                        pass
            except BlockingIOError:
                pass

            # ----------------------------
            # UDP velocity input (NON-BLOCKING)
            # Format: 4-digit string "FBRL" (Forward, Back, Left, Right)
            # Example: "1000" = forward, "0100" = back, "0010" = left, "0001" = right
            # Example: "0000" = stop all
            # ----------------------------
            try:
                while True:  # Process all available packets (keep latest)
                    data, addr = velocity_sock.recvfrom(1024)
                    try:
                        command = data.decode().strip()
                        if len(command) == 4 and command.isdigit():
                            # Parse the 4 digits
                            forward = int(command[0])
                            back = int(command[1])
                            left = int(command[2])
                            right = int(command[3])
                            
                            # Set velocities based on input
                            forward_velocity = BASE_VELOCITY if forward == 1 else 0
                            back_velocity = BASE_VELOCITY if back == 1 else 0
                            left_velocity = BASE_VELOCITY if left == 1 else 0
                            right_velocity = BASE_VELOCITY if right == 1 else 0
                    except (ValueError, IndexError):
                        pass
            except BlockingIOError:
                pass

            # ----------------------------
            # UDP flight commands (NON-BLOCKING)
            # Commands: 1=takeoff, 2=land, 3=emergency
            # ----------------------------
            try:
                while True:  # Process all available packets
                    data, addr = command_sock.recvfrom(1024)
                    try:
                        command_str = data.decode().strip()
                        command_num = int(command_str)
                        
                        if command_num == 1:  # Takeoff
                            if is_flying:
                                print("\n→ Takeoff (1): Already in flight, ignoring")
                            else:
                                print("\n→ Takeoff command (1) received!")
                                tello.takeoff()
                                is_flying = True
                                with state_lock:
                                    control_state['is_flying'] = True
                                print("→ Drone is now flying")
                                time.sleep(2)
                        
                        elif command_num == 2:  # Land
                            if is_flying:
                                print("\n→ Land command (2) received!")
                                # Stop all movement first
                                with state_lock:
                                    control_state['fb_velocity'] = 0
                                    control_state['lr_velocity'] = 0
                                    control_state['yaw_cmd'] = 0
                                time.sleep(0.5)
                                tello.land()
                                is_flying = False
                                with state_lock:
                                    control_state['is_flying'] = False
                                print("→ Drone has landed. Send '1' to takeoff again.")
                            else:
                                print("\n→ Land (2): Already on ground, ignoring")
                        
                        elif command_num == 3:  # Emergency
                            print("\n→ EMERGENCY STOP (3)!")
                            tello.emergency()
                            is_flying = False
                            with state_lock:
                                control_state['is_flying'] = False
                            print("→ Emergency stop executed. Send '1' to takeoff again.")
                        
                        elif command_num == 0:  # No-op / idle
                            pass  # Ignore 0 (can be used as heartbeat)
                        
                        else:
                            print(f"\n→ Unknown command number: {command_num}")
                            
                    except (ValueError, UnicodeDecodeError):
                        pass  # Ignore invalid data
            except BlockingIOError:
                pass

            # ----------------------------
            # Drone yaw (rate-limited)
            # ----------------------------
            if now - last_yaw_time > 1 / YAW_HZ:
                raw = tello.get_yaw()
                raw = unwrap_angle(prev_raw_drone, raw)
                drone_yaw = raw
                prev_raw_drone = raw
                last_yaw_time = now

            # ----------------------------
            # PID
            # ----------------------------
            error = target_yaw - drone_yaw
            derivative = (error - prev_error) * CONTROL_HZ
            prev_error = error

            integral += error / CONTROL_HZ
            integral = max(-INTEGRAL_LIMIT, min(INTEGRAL_LIMIT, integral))

            cmd = KP * error + KD * derivative + KI * integral

            if abs(error) < DEADBAND:
                cmd = 0
                integral *= 0.9

            cmd = max(-MAX_SPEED, min(MAX_SPEED, cmd))

            if cmd > 0:
                cmd = max(MIN_SPEED, cmd)
            elif cmd < 0:
                cmd = min(-MIN_SPEED, cmd)

            if cmd > last_cmd + MAX_CMD_STEP:
                cmd = last_cmd + MAX_CMD_STEP
            elif cmd < last_cmd - MAX_CMD_STEP:
                cmd = last_cmd - MAX_CMD_STEP

            cmd = (1 - CMD_SMOOTHING) * last_cmd + CMD_SMOOTHING * cmd
            last_cmd = cmd

            # ----------------------------
            # Update control state for RC thread
            # ----------------------------
            # Calculate net forward/back and left/right velocities
            fb_velocity = forward_velocity - back_velocity
            lr_velocity = right_velocity - left_velocity
            
            # Update shared state (RC thread will send these values)
            with state_lock:
                control_state['fb_velocity'] = fb_velocity
                control_state['lr_velocity'] = lr_velocity
                control_state['yaw_cmd'] = int(cmd)
            
            # Print status every 5 seconds
            if now - last_status_time > 5:
                mb_relayed = bytes_relayed / (1024 * 1024)
                fb_vel = forward_velocity - back_velocity
                lr_vel = right_velocity - left_velocity
                battery = tello.get_battery()
                flight_status = "FLYING" if is_flying else "LANDED"
                print(f"[{flight_status}] Battery:{battery}% | Yaw T:{target_yaw:5.1f}° D:{drone_yaw:5.1f}° | Vel FB:{fb_vel:3d} LR:{lr_vel:3d} | Video:{packet_count}pkts {mb_relayed:.1f}MB")
                last_status_time = now
    
    except KeyboardInterrupt:
        print("\n\nStopping (Ctrl+C detected)...")
        running = False

    # ----------------------------
    # Cleanup
    # ----------------------------
    print("\nCleaning up...")
    
    # Stop control state
    with state_lock:
        control_state['running'] = False
        control_state['fb_velocity'] = 0
        control_state['lr_velocity'] = 0
        control_state['yaw_cmd'] = 0
    
    # Wait for threads to finish
    relay_active = False
    relay_thread.join(timeout=2)
    rc_thread.join(timeout=2)
    
    # Land if still flying
    if is_flying:
        print("Landing drone...")
        tello.send_rc_control(0, 0, 0, 0)
        tello.land()
    else:
        print("Drone already on ground")
    
    print("Stopping video stream...")
    tello.streamoff()
    tello.end()
    
    yaw_sock.close()
    velocity_sock.close()
    command_sock.close()
    recv_socket.close()
    send_socket.close()
    
    print("Done.")


if __name__ == "__main__":
    main()

import socket
import sys

# UDP configuration
TARGET_IP = "127.0.0.1"  # Change to drone controller's IP if on different machine
TARGET_PORT = 5010       # Port that the receiver is listening on

# Create UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print("Velocity Command Sender")
print("=" * 60)
print(f"Sending commands to: {TARGET_IP}:{TARGET_PORT}")
print("\nFormat: 4 digits [Forward][Back][Left][Right]")
print("Each digit is 0 or 1")
print("\nCommand Guide:")
print("  1000 = Forward     |  0100 = Back")
print("  0010 = Left        |  0001 = Right")
print("  0000 = Stop        |  1001 = Forward + Right")
print("  1010 = Forward + Left | 0101 = Back + Right")
print("\nType 'quit' or 'q' to exit")
print("=" * 60)
print()

def send_command(command):
    """Send a 4-digit velocity command via UDP"""
    try:
        sock.sendto(command.encode(), (TARGET_IP, TARGET_PORT))
        print(f"✓ Sent: {command}")
        return True
    except Exception as e:
        print(f"✗ Error sending command: {e}")
        return False

# Main loop
try:
    while True:
        user_input = input("Enter command: ").strip().lower()
        
        # Check for quit command
        if user_input in ['quit', 'q', 'exit']:
            print("\n→ Sending stop command before exiting...")
            send_command("0000")
            print("✓ Exiting")
            break
        
        # Validate velocity command
        if len(user_input) == 4 and user_input.isdigit():
            # Check that each digit is 0 or 1
            valid = all(c in '01' for c in user_input)
            if valid:
                send_command(user_input)
            else:
                print("✗ Error: Each digit must be 0 or 1")
        else:
            print("✗ Invalid format. Enter 4 digits (0 or 1) or 'quit'")

except KeyboardInterrupt:
    print("\n\n→ Ctrl+C detected, sending stop command...")
    send_command("0000")
    print("✓ Exiting")

except EOFError:
    print("\n\n→ EOF detected, sending stop command...")
    send_command("0000")
    print("✓ Exiting")

finally:
    sock.close()
    print("✓ Socket closed")

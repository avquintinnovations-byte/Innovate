# UDP Velocity Control Guide

## Overview

This system separates the drone control (receiver) from command input (sender), allowing you to control the drone via UDP messages.

## Architecture

```
┌─────────────────────┐         UDP          ┌──────────────────────┐
│ send_velocity_udp.py│   Port 5010         │ test_velocity_sender.py│
│  (Command Sender)   │ ─────────────────> │  (Drone Controller)   │
│  Terminal Input     │   4-digit commands  │   Controls Tello      │
└─────────────────────┘                      └──────────────────────┘
```

## Port Configuration

- **Port 5010**: Receives velocity commands (4-digit format)

## Files

1. **test_velocity_sender.py** - Drone controller (receiver)
   - Connects to Tello drone
   - Takes off
   - Listens for UDP commands on port 5010
   - Continuously sends RC commands at 20Hz
   - Displays status every 5 seconds

2. **send_velocity_udp.py** - Command sender
   - Provides terminal interface for entering commands
   - Sends UDP messages to port 5010
   - Can run on same or different machine

## How to Use

### Step 1: Start the Drone Controller

Open a terminal and run:
```bash
python test_velocity_sender.py
```

You should see:
```
Connecting to Tello drone...
Connected! Battery: 95%
Taking off...
Takeoff complete!
[UDP Receiver] Started - listening for commands...
[RC Control] Started - sending commands at 20Hz

============================================================
✓ Drone is hovering - Waiting for UDP commands
============================================================

Listening on UDP port 5010
Use the sender program to send 4-digit velocity commands

Press Ctrl+C to land and exit
```

### Step 2: Start the Command Sender

Open a **second terminal** and run:
```bash
python send_velocity_udp.py
```

You should see:
```
Velocity Command Sender
============================================================
Sending commands to: 127.0.0.1:5010

Format: 4 digits [Forward][Back][Left][Right]
Each digit is 0 or 1

Command Guide:
  1000 = Forward     |  0100 = Back
  0010 = Left        |  0001 = Right
  0000 = Stop        |  1001 = Forward + Right

Type 'quit' or 'q' to exit
============================================================

Enter command: _
```

### Step 3: Send Commands

Type commands in the sender terminal:

```
Enter command: 1000
✓ Sent: 1000

Enter command: 0000
✓ Sent: 0000

Enter command: 0001
✓ Sent: 0001

Enter command: quit
→ Sending stop command before exiting...
✓ Sent: 0000
✓ Exiting
```

In the receiver terminal, you'll see:
```
→ Command: 1000
→ Command: 0000
[Status] Battery: 94% | Command: 0000
→ Command: 0001
```

### Step 4: Landing

To land the drone:
1. In the sender: Type `quit` or press Ctrl+C (sends stop command)
2. In the receiver: Press **Ctrl+C** to land and exit

## Command Reference

### Velocity Commands (4-digit format)

Each digit represents a direction: `[Forward][Back][Left][Right]`

| Command | Movement |
|---------|----------|
| `1000` | Forward |
| `0100` | Back |
| `0010` | Left |
| `0001` | Right |
| `0000` | Stop |
| `1001` | Forward + Right |
| `1010` | Forward + Left |
| `0101` | Back + Right |
| `0110` | Back + Left |
| `1100` | Invalid (Forward + Back conflict) |
| `0011` | Invalid (Left + Right conflict) |

**Note:** The BASE_VELOCITY is set to 40 in `test_velocity_sender.py`

## Running on Different Machines

If you want to run the sender on a different computer:

1. **On the drone controller machine:**
   - Get the machine's IP address (e.g., `192.168.1.100`)
   - Run `test_velocity_sender.py` (listens on all interfaces: 0.0.0.0)

2. **On the sender machine:**
   - Edit `send_velocity_udp.py`
   - Change `TARGET_IP = "127.0.0.1"` to the controller's IP
   - For example: `TARGET_IP = "192.168.1.100"`
   - Run `send_velocity_udp.py`

## Status Updates

The receiver prints status every 5 seconds:
```
[Status] Battery: 92% | Command: 1000
[Status] Battery: 91% | Command: 0000
```

## Safety Features

1. **Continuous RC Commands**: Sends commands at 20Hz to keep drone stable
2. **Auto-stop on Exit**: Sender sends `0000` when quitting
3. **Emergency Landing**: Ctrl+C on receiver lands the drone safely
4. **Battery Monitoring**: Status updates include battery level

## Troubleshooting

### Receiver not receiving commands
- Check firewall settings (allow UDP port 5010)
- Verify sender is targeting correct IP
- Check that receiver is running and listening

### Drone drifting
- Normal for Tello indoors
- BASE_VELOCITY might be too high/low
- Check for air currents

### Commands not responding
- Make sure receiver is running first
- Verify format is exactly 4 digits (0 or 1)
- Check terminal output for error messages

## Integration with Unity

You can also send commands from Unity using the same UDP format:

```csharp
// In Unity C#
UdpClient client = new UdpClient();
IPEndPoint endpoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), 5010);

// Send forward command
byte[] data = Encoding.UTF8.GetBytes("1000");
client.Send(data, data.Length, endpoint);
```

## Next Steps

- Combine with yaw control from VR headset
- Add up/down control (modify RC command to include vertical velocity)
- Add speed adjustment commands
- Create automated flight patterns

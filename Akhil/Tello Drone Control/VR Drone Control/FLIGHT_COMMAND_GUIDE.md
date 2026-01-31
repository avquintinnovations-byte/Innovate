# Flight Command System Guide

## Overview

The flight command system allows you to send takeoff, land, and emergency stop commands to the drone via UDP on port **5015**.

## Port: 5015 - Flight Commands

### Supported Commands

| Command | Description | Safety |
|---------|-------------|--------|
| `takeoff` | Take off the drone | Safe |
| `land` | Land the drone gracefully | Safe |
| `emergency` | Emergency stop (cuts motors immediately) | ⚠️ DANGEROUS - drone will fall! |

## Integration with VR_Drone.py

The main VR control script (`VR_Drone.py`) now listens on port 5015 for flight commands.

### Behavior:

1. **On Startup**: Waits 5 seconds for a takeoff command, then auto-takeoffs
2. **During Flight**: Continuously monitors for commands
3. **Land Command**: Stops control loop and lands gracefully
4. **Emergency**: Cuts motors immediately (use only in emergency!)

## Usage Methods

### Method 1: Python Command Sender

Use the included Python script:

```bash
python send_flight_command.py
```

**Example session:**
```
Flight Command Sender
============================================================
Sending commands to: 127.0.0.1:5015

Available Commands:
  takeoff   - Take off the drone
  land      - Land the drone
  emergency - Emergency stop (cuts motors immediately!)
  quit / q  - Exit this program
============================================================

Enter command: takeoff
✓ Sent: takeoff

Enter command: land
✓ Sent: land

Enter command: quit
✓ Exiting
```

### Method 2: Unity C# Script

Add the `FlightCommander.cs` script to a GameObject in Unity:

```csharp
// In Unity Inspector:
Target IP: 127.0.0.1
Command Port: 5015
Takeoff Key: T
Land Key: L
Emergency Key: E

// Keyboard controls:
T = Takeoff
L = Land
Shift + E = Emergency Stop (requires Shift for safety)
```

**Or use via code:**
```csharp
// Get the component
FlightCommander commander = GetComponent<FlightCommander>();

// Send commands programmatically
commander.Takeoff();
commander.Land();
commander.Emergency();  // Use with caution!
```

### Method 3: Manual UDP (Python)

Send commands directly via Python:

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(b"takeoff", ("127.0.0.1", 5015))
sock.sendto(b"land", ("127.0.0.1", 5015))
```

### Method 4: Manual UDP (Command Line)

On Linux/Mac, use netcat:
```bash
echo "takeoff" | nc -u 127.0.0.1 5015
echo "land" | nc -u 127.0.0.1 5015
```

On Windows (PowerShell):
```powershell
$udpClient = New-Object System.Net.Sockets.UdpClient
$endpoint = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse("127.0.0.1"), 5015)
$bytes = [System.Text.Encoding]::ASCII.GetBytes("takeoff")
$udpClient.Send($bytes, $bytes.Length, $endpoint)
```

## Complete System Workflow

### Starting the Drone

**Terminal 1 - Start VR_Drone.py:**
```bash
python VR_Drone.py
```
Output:
```
Yaw UDP listener started on 0.0.0.0:5000
Velocity UDP listener started on 0.0.0.0:5005
Command UDP listener started on 0.0.0.0:5015
Connecting to drone...
Battery: 95%

Waiting for takeoff command on port 5015...
Send 'takeoff' via UDP or press Enter to takeoff now
```

**Terminal 2 - Send Takeoff Command:**
```bash
python send_flight_command.py
```
```
Enter command: takeoff
✓ Sent: takeoff
```

### During Flight

Control the drone using:
- **Yaw (Port 5000)**: HeadYaw.cs from Unity
- **Velocity (Port 5005)**: VelocityController.cs or send_velocity_udp.py
- **Commands (Port 5015)**: FlightCommander.cs or send_flight_command.py

### Landing the Drone

**Option 1: UDP Command**
```bash
python send_flight_command.py
```
```
Enter command: land
✓ Sent: land
```

**Option 2: Unity Key**
Press `L` key (if FlightCommander.cs is active)

**Option 3: Ctrl+C**
Press Ctrl+C in the VR_Drone.py terminal (always works)

## All Ports Summary

| Port | Purpose | Command Format | Example |
|------|---------|----------------|---------|
| 5000 | Yaw Control | Float (degrees) | `45.5` |
| 5005 | Velocity Control | 4-digit string | `1000` |
| 5015 | Flight Commands | String | `takeoff`, `land` |
| 5001 | Video Stream | H.264 (output) | - |

## Safety Features

### Auto-Takeoff
If no takeoff command is received within 5 seconds, the drone will automatically takeoff. This prevents leaving the drone waiting indefinitely.

### Land vs Emergency

**Land (Recommended):**
- Gracefully descends
- Maintains stability
- Safe landing
- Use: `land` command or Ctrl+C

**Emergency (Use Only in Emergency):**
- Cuts motors immediately
- Drone will fall
- Can damage drone
- Use only if drone is out of control
- Requires Shift+E in Unity (safety confirmation)

## Troubleshooting

### Command not received
- Check that VR_Drone.py shows "Command UDP listener started"
- Verify port 5015 is not blocked by firewall
- Check target IP is correct

### Takeoff not working
- Ensure drone has sufficient battery (>20%)
- Check drone is on level surface
- Verify drone is connected (battery status shown)

### Multiple takeoff commands
- Script ignores takeoff if already in flight
- Safe to send multiple times

## VR Integration Example

Complete Unity setup with all controls:

```csharp
// GameObject: "DroneControl"
// - HeadYaw.cs (attached to VR Camera)
// - VelocityController.cs
// - FlightCommander.cs

// In your VR controller script:
public class VRDroneController : MonoBehaviour
{
    private FlightCommander flightCommander;
    private VelocityController velocityController;
    
    void Start()
    {
        flightCommander = GetComponent<FlightCommander>();
    }
    
    void Update()
    {
        // Trigger button on right controller = takeoff
        if (OVRInput.GetDown(OVRInput.Button.One))
        {
            flightCommander.Takeoff();
        }
        
        // B button = land
        if (OVRInput.GetDown(OVRInput.Button.Two))
        {
            flightCommander.Land();
        }
        
        // Thumbstick controls velocity
        Vector2 stick = OVRInput.Get(OVRInput.Axis2D.PrimaryThumbstick);
        velocityController.moveForward = stick.y > 0.5f;
        velocityController.moveBack = stick.y < -0.5f;
        velocityController.moveLeft = stick.x < -0.5f;
        velocityController.moveRight = stick.x > 0.5f;
    }
}
```

## Best Practices

1. **Always test in open area** - Ensure safe flying space
2. **Monitor battery** - Land at 20% or below
3. **Keep line of sight** - Don't fly where you can't see drone
4. **Have landing plan** - Know how to land quickly
5. **Emergency awareness** - Only use emergency in true emergencies

## Command Logging

VR_Drone.py logs all commands received:
```
→ Takeoff command received!
Taking off...

[During flight...]

→ Land command received!
Landing...
```

This helps debug if commands aren't working as expected.

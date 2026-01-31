# Tello Drone VR Control System Guide

## Overview

This system allows you to control a Tello drone using VR headset rotation (yaw) and directional movement commands from Unity, while streaming the drone's camera feed back to Unity/GStreamer.

## System Architecture

```
┌─────────────────┐
│  Unity VR App   │
└────────┬────────┘
         │
         ├─ Port 5000 → Yaw Values (HeadYaw.cs)
         ├─ Port 5005 → Velocity Commands (VelocityController.cs)
         │
         ↓
┌──────────────────────────┐
│  yaw_camera_combined.py  │
│  (Python Control Script) │
└──────────┬───────────────┘
           │
           ├─ Control → Tello Drone
           ├─ Port 5001 → Video Stream (H.264)
           │
           ↓
    ┌─────────────┐
    │ Unity/      │
    │ GStreamer   │
    └─────────────┘
```

## Port Configuration

| Port | Direction | Data Type | Purpose |
|------|-----------|-----------|---------|
| 5000 | Unity → Python | Float (Yaw angle) | VR headset rotation control |
| 5005 | Unity → Python | 4-digit string | Velocity commands (FBRL) |
| 5015 | Unity → Python | String | Flight commands (takeoff/land/emergency) |
| 5001 | Python → Unity | H.264 video | Camera stream from drone |

## Files Description

### Python Scripts

1. **VR_Drone.py** (Main VR control script)
   - Receives yaw values on port 5000
   - Receives velocity commands on port 5005
   - Receives flight commands on port 5015 (takeoff/land/emergency)
   - Controls drone using PID for yaw
   - Streams camera to port 5001
   - Anti-drift: Continuous RC commands at 20Hz

2. **yaw_camera_combined.py** (Alternative control script)
   - Receives yaw values on port 5000
   - Receives velocity commands on port 5005
   - Controls drone using PID for yaw
   - Streams camera to port 5001

3. **yaw_udp_receiver.py** (Yaw control only, no camera)
   - Lightweight version for yaw control only
   - No video streaming or display

4. **test_velocity_sender.py** (UDP receiver for testing)
   - Receives velocity commands on port 5010
   - Direct drone control for testing

5. **send_velocity_udp.py** (Velocity command sender)
   - Sends velocity commands to test receiver
   - Terminal-based control

6. **send_flight_command.py** (Flight command sender)
   - Sends takeoff/land commands to port 5015
   - Simple command interface

### Unity C# Scripts

1. **HeadYaw.cs**
   - Reads VR headset yaw rotation
   - Sends yaw values to Python (port 5000)
   - Rate: 20 Hz

2. **VelocityController.cs**
   - Controls drone movement (forward/back/left/right)
   - Sends 4-digit commands to Python (port 5005)
   - Can be controlled via keyboard or VR controllers

## Velocity Command Format

The velocity control uses a 4-digit string where each digit is 0 or 1:

**Format:** `[Forward][Back][Left][Right]`

### Examples:

| Command | Movement |
|---------|----------|
| `1000` | Forward only |
| `0100` | Back only |
| `0010` | Left only |
| `0001` | Right only |
| `0000` | Stop all movement |
| `1001` | Forward + Right (diagonal) |
| `1010` | Forward + Left (diagonal) |

### Base Velocity

The `BASE_VELOCITY` is set to **40** by default in the Python script. This means:
- When you send `1000`, the drone moves forward at velocity 40
- When you send `0000`, all velocities are set to 0 (stop)

You can adjust `BASE_VELOCITY` in `yaw_camera_combined.py` to change the movement speed.

## Setup Instructions

### 1. Python Setup

Install required packages:
```bash
pip install djitellopy opencv-python
```

### 2. Unity Setup

#### Add HeadYaw.cs to your VR Camera:

1. Attach `HeadYaw.cs` to a GameObject
2. In Inspector, set:
   - **Headset Transform**: Your VR camera transform
   - **Target IP**: "127.0.0.1" (or Python script IP)
   - **Target Port**: 5000
   - **Send Rate**: 20

#### Add VelocityController.cs to a GameObject:

1. Create an empty GameObject called "DroneController"
2. Attach `VelocityController.cs`
3. In Inspector, set:
   - **Target IP**: "127.0.0.1"
   - **Velocity Port**: 5005
   - **Send Rate**: 10

### 3. GStreamer Video Reception (Optional)

To receive video in Unity, use the GStreamer plugin with:

```bash
gst-launch-1.0 udpsrc port=5001 ! h264parse ! avdec_h264 ! videoconvert ! autovideosink sync=false
```

Or configure your GStreamer Unity integration to receive from UDP port 5001.

## Running the System

### Step 1: Start the Python Control Script

```bash
python yaw_camera_combined.py
```

Expected output:
```
Yaw UDP listener started on 0.0.0.0:5000
Velocity UDP listener started on 0.0.0.0:5005
Connecting to drone...
Battery: 95%
Starting video stream...
Video relay active: Tello (UDP:11111) -> GStreamer (UDP:5001)
Taking off...
Yaw control active! Streaming video to Unity/GStreamer
Press Ctrl+C to land and stop.
```

### Step 2: Start Unity VR Application

- The drone will respond to your headset rotation
- Use keyboard or VR controllers to move

### Step 3: Test Without Unity (Optional)

Use the test script to verify velocity control:

```bash
python test_velocity_sender.py
```

## Control Mapping

### Default Keyboard Controls (in Unity)

| Key | Direction |
|-----|-----------|
| W / ↑ | Forward |
| S / ↓ | Back |
| A / ← | Left |
| D / → | Right |

### VR Controller Integration

To integrate VR controllers, modify `VelocityController.cs`:

```csharp
void Update()
{
    // Example: Oculus/Meta Quest controllers
    moveForward = OVRInput.Get(OVRInput.Button.PrimaryThumbstickUp);
    moveBack = OVRInput.Get(OVRInput.Button.PrimaryThumbstickDown);
    moveLeft = OVRInput.Get(OVRInput.Button.PrimaryThumbstickLeft);
    moveRight = OVRInput.Get(OVRInput.Button.PrimaryThumbstickRight);
}
```

## Tuning Parameters

### Python (yaw_camera_combined.py)

```python
# PID tuning for yaw control
KP = 0.6          # Proportional gain
KI = 0.0          # Integral gain
KD = 0.3          # Derivative gain

# Velocity control
BASE_VELOCITY = 40  # Increase for faster movement (max 100)

# Control rates
CONTROL_HZ = 40   # Main loop frequency
RC_HZ = 20        # RC command send rate
YAW_HZ = 20       # Yaw reading rate
```

### Unity (C# Scripts)

```csharp
// HeadYaw.cs
public float sendRate = 20f;  // Yaw update frequency

// VelocityController.cs
public float sendRate = 10f;  // Velocity command frequency
```

## Troubleshooting

### Drone not responding to yaw commands
- Check that Unity is sending to port 5000
- Verify Python script shows "Yaw UDP listener started"
- Check firewall settings

### Drone not responding to velocity commands
- Check that Unity is sending to port 5005
- Run `test_velocity_sender.py` to test Python reception
- Verify BASE_VELOCITY is not 0

### No video stream
- Check that port 5001 is not blocked
- Verify GStreamer is configured for port 5001
- Check that Tello video stream is active

### Drone movements are too fast/slow
- Adjust `BASE_VELOCITY` in Python script
- Reduce if drone is too aggressive
- Increase if drone is too sluggish

### Yaw control is unstable
- Adjust PID parameters (KP, KD)
- Reduce KP if oscillating
- Increase KD for damping

## Safety Notes

⚠️ **Important Safety Reminders:**

1. Always have clear space around the drone
2. Keep emergency landing access ready (Ctrl+C in Python)
3. Test in a safe environment first
4. Monitor battery level
5. The drone will land automatically when the script stops

## Emergency Stop

To stop the drone immediately:

1. Press **Ctrl+C** in the Python terminal
2. The script will:
   - Stop all movement
   - Land the drone
   - Close all connections

## Status Display

The Python script prints status every 2 seconds:

```
Yaw T:45.0° D:43.2° E:1.8° | Vel FB:40 LR:0 | YawCmd:12 | Video:1234pkts 5.2MB
```

- **T**: Target yaw (from VR headset)
- **D**: Drone current yaw
- **E**: Error (difference)
- **FB**: Forward/Back velocity
- **LR**: Left/Right velocity
- **YawCmd**: PID yaw command
- **Video**: Stream statistics

## Advanced Usage

### Multiple Drones

To control multiple drones, use different ports:

**Drone 1:**
- Yaw: 5000, Velocity: 5005, Video: 5001

**Drone 2:**
- Yaw: 6000, Velocity: 6005, Video: 6001

### Autonomous Waypoints

You can extend `VelocityController.cs` to send programmed sequences:

```csharp
IEnumerator MoveSequence()
{
    // Forward for 3 seconds
    SetForward(true);
    yield return new WaitForSeconds(3);
    StopAll();
    
    // Right for 2 seconds
    SetRight(true);
    yield return new WaitForSeconds(2);
    StopAll();
}
```

## License

This project uses the DJITelloPy library and follows its licensing terms.

## Credits

- DJITelloPy: https://github.com/damiafuentes/DJITelloPy
- Unity VR integration
- GStreamer video streaming

# Tello Low-Latency Streaming Setup

This setup streams the Tello drone camera feed with minimal latency using FFmpeg and GStreamer.

## Files

- **camera_stream_test.py** - Sender (captures from Tello and streams via RTP)
- **stream_receiver.py** - Python receiver using GStreamer (optional)

## Low-Latency Optimizations

### Sender (FFmpeg)
- **No buffering**: `-fflags nobuffer -flags low_delay`
- **Instant probing**: `-probesize 32 -analyzeduration 0`
- **Zero delay**: `-max_delay 0`
- **Packet flushing**: `-flush_packets 1`
- **Optimized MTU**: `-pkt_size 1200` (prevents fragmentation)
- **Stream copy**: `-c:v copy` (no re-encoding)

### Receiver (GStreamer)
- **Zero latency jitter buffer**: `latency=0 drop-on-latency=true`
- **No sync**: `sync=false` (don't sync to clock)
- **Multi-threaded decode**: `max-threads=4`

## Usage

### 1. Start the sender (on machine connected to Tello)
```bash
python camera_stream_test.py
```

### 2. Start the receiver

**Option A: Using Python script (requires PyGObject)**
```bash
python stream_receiver.py
```

**Option B: Using gst-launch-1.0 command line**
```bash
gst-launch-1.0 udpsrc port=5000 ! application/x-rtp,payload=96 ! rtpjitterbuffer latency=0 drop-on-latency=true ! rtph264depay ! avdec_h264 max-threads=4 ! videoconvert ! autovideosink sync=false
```

**Option C: For even lower latency (decode on GPU if available)**
```bash
gst-launch-1.0 udpsrc port=5000 ! application/x-rtp,payload=96 ! rtpjitterbuffer latency=0 drop-on-latency=true ! rtph264depay ! d3d11h264dec ! videoconvert ! autovideosink sync=false
```

## Expected Latency

With these optimizations:
- **Network latency**: ~5-20ms (depends on network)
- **Decode latency**: ~10-30ms
- **Total latency**: ~50-100ms (typical)

Compare to:
- Default settings: 200-500ms latency
- Non-optimized: 500-1000ms+ latency

## Troubleshooting

### Video is choppy/stuttering
- Try increasing jitter buffer slightly: `latency=10` (10ms)
- Check network quality and WiFi signal strength

### Still too much latency
- Use hardware decoder (GPU): `d3d11h264dec` on Windows, `nvh264dec` on NVIDIA GPUs
- Reduce Tello video resolution if possible
- Use 5GHz WiFi if available

### Lost frames/artifacts
- Increase buffer size in FFmpeg command
- Check WiFi interference
- Move closer to drone

## Network Requirements

- **Bandwidth**: ~2-4 Mbps
- **WiFi**: 2.4GHz (Tello limitation)
- **Latency**: <50ms network latency recommended

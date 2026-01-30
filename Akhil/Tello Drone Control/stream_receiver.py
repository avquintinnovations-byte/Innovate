"""
Low-latency GStreamer receiver for Tello camera stream
Run this on the same or different machine to receive the RTP stream
"""

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import sys

# Port to receive stream on (must match sender)
UDP_PORT = 5000

def main():
    # Initialize GStreamer
    Gst.init(None)
    
    print(f"Starting low-latency GStreamer receiver on port {UDP_PORT}...")
    
    # Build low-latency pipeline
    pipeline_str = (
        f'udpsrc port={UDP_PORT} '
        '! application/x-rtp,payload=96,encoding-name=H264 '
        '! rtpjitterbuffer latency=0 drop-on-latency=true '
        '! rtph264depay '
        '! avdec_h264 max-threads=4 '
        '! videoconvert '
        '! autovideosink sync=false'
    )
    
    print(f"Pipeline: {pipeline_str}\n")
    
    # Create pipeline
    pipeline = Gst.parse_launch(pipeline_str)
    
    # Start playing
    pipeline.set_state(Gst.State.PLAYING)
    
    print("Receiver started!")
    print("Waiting for stream... Press Ctrl+C to stop.\n")
    
    # Run main loop
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n\nStopping receiver...")
    
    # Cleanup
    pipeline.set_state(Gst.State.NULL)
    print("Done.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        print("\nMake sure you have GStreamer Python bindings installed:")
        print("  pip install PyGObject")
        sys.exit(1)

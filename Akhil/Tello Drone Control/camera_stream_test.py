from djitellopy import Tello
import time
import subprocess
import threading

# ----------------------------
# Stream config
# ----------------------------
UDP_PORT = 5000
UDP_HOST = "127.0.0.1"
TELLO_VIDEO_PORT = 11111

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
    # FFmpeg subprocess for re-streaming to RTP (optimized for low latency)
    # ----------------------------
    # Tello streams raw H.264 over UDP to port 11111
    # We'll capture that and re-stream it as RTP to port 5000
    # Optimized for real-time streaming with minimal latency
    ffmpeg_cmd = [
        'ffmpeg',
        '-hide_banner',
        '-loglevel', 'warning',
        
        # Input options - minimize buffering
        '-fflags', 'nobuffer',
        '-flags', 'low_delay',
        '-probesize', '32',
        '-analyzeduration', '0',
        '-max_delay', '0',
        
        # UDP input
        '-i', f'udp://0.0.0.0:{TELLO_VIDEO_PORT}?overrun_nonfatal=1&buffer_size=8192000',
        
        # Video codec - copy stream without re-encoding
        '-c:v', 'copy',
        
        # RTP output options - low latency
        '-f', 'rtp',
        '-payload_type', '96',
        '-ssrc', '1',
        '-cname', 'tello',
        '-buffer_size', '8192000',
        '-pkt_size', '1200',  # MTU size for network packets
        '-flush_packets', '1',
        
        # Optional SDP file
        '-sdp_file', 'stream.sdp',
        
        # Output
        f'rtp://{UDP_HOST}:{UDP_PORT}'
    ]
    
    print(f"\nStarting FFmpeg to re-stream Tello video to RTP port {UDP_PORT}")
    print(f"This RTP stream is compatible with your GStreamer receiver!")
    print(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
    
    # Thread to read FFmpeg stderr
    ffmpeg_errors = []
    def read_ffmpeg_stderr(process):
        for line in iter(process.stderr.readline, b''):
            msg = line.decode('utf-8', errors='ignore').strip()
            if msg:
                ffmpeg_errors.append(msg)
                print(f"[FFmpeg] {msg}")
    
    try:
        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Start stderr reader thread
        stderr_thread = threading.Thread(target=read_ffmpeg_stderr, args=(ffmpeg_process,), daemon=True)
        stderr_thread.start()
        
        # Give FFmpeg a moment to start
        time.sleep(1)
        
        # Check if it's still running
        if ffmpeg_process.poll() is not None:
            print("\nERROR: FFmpeg terminated immediately!")
            print("Recent FFmpeg errors:")
            for err in ffmpeg_errors[-10:]:
                print(f"  {err}")
            tello.streamoff()
            tello.end()
            pygame.quit()
            return
        
        print("FFmpeg process started successfully!")
        print(f"Tello H.264 stream (UDP:{TELLO_VIDEO_PORT}) -> RTP stream (UDP:{UDP_PORT})")
        print("\nLow-latency optimizations enabled:")
        print("  - No buffering (nobuffer, low_delay)")
        print("  - Instant probing (probesize=32, analyzeduration=0)")
        print("  - Packet flushing enabled")
        print("  - Optimized MTU size (1200 bytes)")
        print("\nYour GStreamer receiver can now connect with:")
        print(f"  gst-launch-1.0 udpsrc port={UDP_PORT} ! application/x-rtp,payload=96 \\")
        print("    ! rtpjitterbuffer latency=0 drop-on-latency=true \\")
        print("    ! rtph264depay ! avdec_h264 max-threads=4 \\")
        print("    ! videoconvert ! autovideosink sync=false")
        print("\nStreaming in progress...")
        print("Press Ctrl+C to stop.\n")
    except FileNotFoundError:
        print("ERROR: FFmpeg not found!")
        print("Please install FFmpeg:")
        print("  - Download from https://ffmpeg.org/download.html")
        print("  - Or use: winget install ffmpeg")
        print("  - Or use: choco install ffmpeg")
        tello.streamoff()
        tello.end()
        pygame.quit()
        return
    except Exception as e:
        print(f"ERROR: Failed to start FFmpeg: {e}")
        tello.streamoff()
        tello.end()
        pygame.quit()
        return

    # ----------------------------
    # Main loop - Monitor FFmpeg and wait for Ctrl+C
    # ----------------------------
    ffmpeg_start_time = time.time()
    
    try:
        while True:
            time.sleep(1)
            
            # Check if FFmpeg process is still running
            if ffmpeg_process.poll() is not None:
                print("\nWARNING: FFmpeg process terminated unexpectedly!")
                if ffmpeg_errors:
                    print("Last FFmpeg errors:")
                    for err in ffmpeg_errors[-5:]:
                        print(f"  {err}")
                break
            
            # Print status every 10 seconds
            runtime = int(time.time() - ffmpeg_start_time)
            if runtime % 10 == 0 and runtime > 0:
                print(f"[{runtime}s] Streaming... Battery: {tello.get_battery()}%")
                
    except KeyboardInterrupt:
        print("\n\nStopping stream (Ctrl+C detected)...")

    # ----------------------------
    # Cleanup
    # ----------------------------
    print("\nCleaning up...")
    
    # Terminate FFmpeg process
    if ffmpeg_process.poll() is None:
        print("Stopping FFmpeg...")
        ffmpeg_process.terminate()
        try:
            ffmpeg_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            print("Force stopping FFmpeg...")
            ffmpeg_process.kill()
    
    print("Stopping Tello video stream...")
    tello.streamoff()
    tello.end()
    print("Done. Drone disconnected.")


if __name__ == "__main__":
    main()

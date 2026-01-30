import subprocess
import numpy as np

WIDTH = 960
HEIGHT = 720

class H264Decoder(object):
    def __init__(self):
        self.cmd = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            "-loglevel", "quiet",
            "-i", "pipe:0",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "pipe:1"
        ]

        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0
        )

    def decode(self, packet_data):
        frames = []

        try:
            # Send H264 data to ffmpeg
            self.proc.stdin.write(packet_data)

            # Read one frame worth of bytes
            frame_size = WIDTH * HEIGHT * 3
            raw = self.proc.stdout.read(frame_size)

            if len(raw) == frame_size:
                frame = np.fromstring(raw, dtype=np.uint8)
                frame = frame.reshape((HEIGHT, WIDTH, 3))
                frames.append(frame)

        except:
            pass

        return frames

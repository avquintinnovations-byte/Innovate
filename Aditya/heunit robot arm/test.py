import serial
import time

# CHANGE THIS TO YOUR COM PORT
PORT = "COM6"      # e.g. COM3, COM5
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)  # wait for controller reset

def send(cmd):
    ser.write((cmd + "\n").encode())
    time.sleep(0.1)
    reply = ser.readline().decode(errors="ignore").strip()
    print(">>", cmd)
    print("<<", reply)

# ---- BASIC TEST SEQUENCE ----

send("G90")                    # absolute positioning

send("G0 X100 Y200 Z50")        # fast move
time.sleep(1)

send("G0 X100 Y-200 Z50")        # slow precise move
time.sleep(1)

send("G0 X30 Y200 Z80")           # back to safe

ser.close()
print("Done.")

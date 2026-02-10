import serial
import time
import keyboard

PORT = "COM6"      # CHANGE THIS
BAUD = 115200
STEP = 10          # mm per key press
ZSTEP = 5

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)

# current pose (start safe)
x, y, z = 0, 180, 80

def send(cmd):
    ser.write((cmd + "\n").encode())
    time.sleep(0.05)
    ser.readline()

send("G90")
send(f"G0 X{x} Y{y} Z{z}")

print("""
Controls:
W/S : Y + / -
A/D : X - / +
R/F : Z + / -
C   : Gripper close
O   : Gripper open
V   : Suction ON
B   : Suction OFF
ESC : Quit
""")

while True:
    if keyboard.is_pressed("esc"):
        break

    moved = False

    if keyboard.is_pressed("w"):
        y += STEP; moved = True
    if keyboard.is_pressed("s"):
        y -= STEP; moved = True
    if keyboard.is_pressed("a"):
        x -= STEP; moved = True
    if keyboard.is_pressed("d"):
        x += STEP; moved = True
    if keyboard.is_pressed("r"):
        z += ZSTEP; moved = True
    if keyboard.is_pressed("f"):
        z -= ZSTEP; moved = True

    if moved:
        send(f"G1 X{x} Y{y} Z{z}")
        print(f"Move -> X:{x} Y:{y} Z:{z}")
        time.sleep(0.15)

    if keyboard.is_pressed("c"):
        send("M1007 2")   # gripper close
        time.sleep(0.3)

    if keyboard.is_pressed("o"):
        send("M1007 1")   # gripper open
        time.sleep(0.3)

    if keyboard.is_pressed("v"):
        send("M1006 1")   # suction ON
        time.sleep(0.3)

    if keyboard.is_pressed("b"):
        send("M1006 0")   # suction OFF
        time.sleep(0.3)

ser.close()
print("Disconnected")

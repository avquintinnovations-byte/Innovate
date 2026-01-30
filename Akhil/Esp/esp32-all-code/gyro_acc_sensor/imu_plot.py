import serial
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
from collections import deque
import sys, time
from collections import deque
import time

imu_buffer = deque(maxlen=50)  # holds recent samples

# ===== CHANGE PORT =====
PORT = "COM9"
BAUD = 115200
# ========================

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)

# ---------------- Rotation ----------------
def rotation_matrix(roll, pitch, yaw):
    r, p, y = np.deg2rad([roll, pitch, yaw])

    Rx = np.array([[1,0,0],[0,np.cos(r),-np.sin(r)],[0,np.sin(r),np.cos(r)]])
    Ry = np.array([[np.cos(p),0,np.sin(p)],[0,1,0],[-np.sin(p),0,np.cos(p)]])
    Rz = np.array([[np.cos(y),-np.sin(y),0],[np.sin(y),np.cos(y),0],[0,0,1]])

    return Rz @ Ry @ Rx

def quat_to_rotmat(q):
    q0, q1, q2, q3 = q  # w, x, y, z

    R = np.array([
        [1 - 2*(q2*q2 + q3*q3),     2*(q1*q2 - q0*q3),     2*(q1*q3 + q0*q2)],
        [    2*(q1*q2 + q0*q3), 1 - 2*(q1*q1 + q3*q3),     2*(q2*q3 - q0*q1)],
        [    2*(q1*q3 - q0*q2),     2*(q2*q3 + q0*q1), 1 - 2*(q1*q1 + q2*q2)]
    ])

    return R


# ---------------- Cube ----------------
cube = np.array([
    [-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
    [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]
])

edges = [
    (0,1),(1,2),(2,3),(3,0),
    (4,5),(5,6),(6,7),(7,4),
    (0,4),(1,5),(2,6),(3,7)
]

# ---------------- Qt App ----------------
app = QtWidgets.QApplication([])
win = pg.GraphicsLayoutWidget(title="IMU Dashboard (CPU Cube)")
win.resize(1200, 700)
win.show()

# Left: cube
cube_plot = win.addPlot(title="3D Cube (CPU Rendered)")
cube_plot.setAspectLocked(True)
cube_plot.setRange(xRange=(-3,3), yRange=(-3,3))
cube_plot.hideAxis('bottom')
cube_plot.hideAxis('left')

lines = [cube_plot.plot(pen=pg.mkPen('c', width=2)) for _ in edges]

win.nextColumn()

# Right: graphs
graphs = []
curves = []
buffers = [deque([0]*200, maxlen=200) for _ in range(10)]

titles = ["Linear Acc", "Gyro", "Angles"]
indexes = [(0,1,2), (3,4,5), (6,7,8)]

labels = [
    "AccX", "AccY", "AccZ",
    "GyroX", "GyroY", "GyroZ",
    "Roll", "Pitch", "Yaw"
]

colors = ['r','g','b','c','m','y','w','orange','pink']


for i in range(3):
    p = win.addPlot(title=titles[i])
    p.showGrid(x=True, y=True)
    p.addLegend()   # <<< THIS enables the label box
    graphs.append(p)

    for j in indexes[i]:
        curve = p.plot(
            buffers[j],
            pen=pg.mkPen(colors[j], width=2),
            name=labels[j]   # <<< THIS is the label text
        )
        curves.append(curve)

    win.nextRow()


# ---------------- Update ----------------
def update():
    # 1. Read all available serial lines into buffer
    while ser.in_waiting:
        line = ser.readline().decode(errors="ignore").strip()
        parts = line.split()
        if len(parts) == 11:
            try:
                vals = list(map(float, parts))
                imu_buffer.append(vals)
            except:
                pass

    if len(imu_buffer) < 3:
        return

    # 2. Choose target render time (small intentional delay)
    now = time.time() * 1000  # ms
    target_time = now - 30    # render 30ms behind real-time (smoothest point)

    # 3. Find closest sample by timestamp
    closest = min(imu_buffer, key=lambda s: abs(s[0] - target_time))

    t, linX, linY, linZ, gx, gy, gz, q0, q1, q2, q3 = closest

    # Update graphs
    for i, v in enumerate([linX, linY, linZ, gx, gy, gz, q0, q1, q2]):
        buffers[i].append(v)
        curves[i].setData(buffers[i])

    # Normalize quaternion
    norm = np.sqrt(q0*q0 + q1*q1 + q2*q2 + q3*q3)
    q0, q1, q2, q3 = q0/norm, q1/norm, q2/norm, q3/norm

    # Rotate cube
    R = quat_to_rotmat([q0, q1, q2, q3])
    rotated = cube @ R.T
    proj = rotated[:, :2] / (rotated[:, 2] + 4)[:, None]

    for i, (a, b) in enumerate(edges):
        lines[i].setData([proj[a][0], proj[b][0]],
                         [proj[a][1], proj[b][1]])



timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(10)

sys.exit(app.exec_())

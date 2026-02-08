import requests
import os
import tkinter as tk
from tkinter import messagebox

ESP32_IP = "http://192.168.4.1"
SYNC_DIR = "esp32_sync"

os.makedirs(SYNC_DIR, exist_ok=True)

def sync_files():
    status_label.config(text="Syncing...")
    root.update_idletasks()

    try:
        files = requests.get(f"{ESP32_IP}/list", timeout=5).json()
        new_files = 0

        for f in files:
            path = os.path.join(SYNC_DIR, f)

            if f == "index.txt" or not os.path.exists(path):

                r = requests.get(
                    f"{ESP32_IP}/download",
                    params={"file": f},
                    timeout=15
                )
                with open(path, "wb") as file:
                    file.write(r.content)
                new_files += 1

        status_label.config(text="Idle")
        messagebox.showinfo(
            "Sync Complete",
            f"New files downloaded: {new_files}"
        )

    except Exception:
        status_label.config(text="Idle")
        messagebox.showerror(
            "Error",
            "ESP32 not reachable.\n\nConnect to ESP32_CAM WiFi."
        )

# ================= GUI =================
root = tk.Tk()
root.title("ESP32 Manual Sync")
root.geometry("320x180")
root.resizable(False, False)

tk.Label(
    root,
    text="ESP32 SD Card Sync",
    font=("Arial", 14)
).pack(pady=10)

sync_button = tk.Button(
    root,
    text="SYNC FILES",
    font=("Arial", 12),
    width=18,
    height=2,
    command=sync_files
)
sync_button.pack(pady=10)

status_label = tk.Label(
    root,
    text="Idle",
    font=("Arial", 10),
    fg="green"
)
status_label.pack()

root.mainloop()

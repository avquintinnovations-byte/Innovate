"""
ESP32 Auto-Sync Client - Runs on Computer
Continuously monitors ESP32 AP for new files and syncs them to the server.

Architecture:
1. Computer connects to ESP32_CAM WiFi (192.168.4.1)
2. Client polls ESP32 for new files
3. Downloads files to local folder
4. Uploads to server for processing
5. Shows real-time sync and processing status
"""

import os
import sys
import json
import time
import requests
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime
from pathlib import Path

# ==================== CONFIGURATION ====================
ESP32_IP = "http://192.168.4.1"
SERVER_URL = "https://localhost:5000"
SYNC_FOLDER = "esp32_sync"
SYNC_LOG = os.path.join(SYNC_FOLDER, ".synced.json")
CHECK_INTERVAL = 3  # Check every 3 seconds
REQUEST_TIMEOUT = 10

# Disable SSL warnings for self-signed certificates
requests.packages.urllib3.disable_warnings()

# ==================== STATE MANAGEMENT ====================
class SyncState:
    def __init__(self):
        self.synced_files = self.load_synced()
        self.is_running = True
        self.esp32_connected = False
        self.server_connected = False
        self.last_sync_time = None
        self.sync_count = 0
        self.error_count = 0
        self.pending_processing = 0
        
    def load_synced(self):
        if os.path.exists(SYNC_LOG):
            try:
                with open(SYNC_LOG, 'r') as f:
                    return set(json.load(f))
            except:
                return set()
        return set()
    
    def save_synced(self):
        os.makedirs(SYNC_FOLDER, exist_ok=True)
        with open(SYNC_LOG, 'w') as f:
            json.dump(list(self.synced_files), f)
    
    def mark_synced(self, file_pair):
        self.synced_files.add(file_pair)
        self.save_synced()

state = SyncState()

# ==================== ESP32 COMMUNICATION ====================
def check_esp32_connection():
    """Check if ESP32 is reachable."""
    try:
        response = requests.get(f"{ESP32_IP}/list", timeout=2)
        return response.status_code == 200
    except:
        return False

def get_esp32_files():
    """Get list of files from ESP32."""
    try:
        response = requests.get(f"{ESP32_IP}/list", timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        log_message(f"Error getting file list: {e}", "ERROR")
        return []

def download_file(filename):
    """Download a file from ESP32."""
    try:
        response = requests.get(
            f"{ESP32_IP}/download",
            params={"file": filename},
            timeout=REQUEST_TIMEOUT
        )
        if response.status_code == 200:
            filepath = os.path.join(SYNC_FOLDER, filename)
            os.makedirs(SYNC_FOLDER, exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return filepath
        return None
    except Exception as e:
        log_message(f"Error downloading {filename}: {e}", "ERROR")
        return None

# ==================== SERVER COMMUNICATION ====================
def check_server_connection():
    """Check if server is reachable."""
    try:
        response = requests.get(f"{SERVER_URL}/sync_status", verify=False, timeout=2)
        return response.status_code == 200
    except:
        return False

def upload_to_server(image_path, audio_path, index):
    """Upload file pair to server."""
    try:
        with open(image_path, 'rb') as img, open(audio_path, 'rb') as aud:
            files = {
                'image': (os.path.basename(image_path), img, 'image/jpeg'),
                'audio': (os.path.basename(audio_path), aud, 'audio/wav')
            }
            data = {'index': index}
            
            response = requests.post(
                f"{SERVER_URL}/upload_esp32",
                files=files,
                data=data,
                verify=False,
                timeout=30
            )
            
            return response.status_code == 200
    except Exception as e:
        log_message(f"Error uploading pair {index}: {e}", "ERROR")
        return False

def get_processing_status():
    """Get processing status from server."""
    try:
        response = requests.get(f"{SERVER_URL}/sync_status", verify=False, timeout=5)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

# ==================== FILE PAIRING ====================
def find_file_pairs(files):
    """Find image/audio pairs from file list."""
    pairs = {}
    
    # Find all image files
    for filename in files:
        if filename.startswith("image") and filename.endswith(".jpg"):
            # Extract index: image1.jpg -> 1
            try:
                index = filename[5:-4]  # Remove "image" and ".jpg"
                audio_name = f"audio{index}.wav"
                
                if audio_name in files:
                    pairs[index] = {
                        'image': filename,
                        'audio': audio_name,
                        'index': index
                    }
            except:
                pass
    
    return pairs

# ==================== SYNC LOGIC ====================
def sync_cycle():
    """Main sync cycle - runs continuously."""
    log_message("🔄 Sync client started", "INFO")
    
    while state.is_running:
        try:
            # Check ESP32 connection
            esp32_connected = check_esp32_connection()
            state.esp32_connected = esp32_connected
            update_connection_status()
            
            if not esp32_connected:
                log_message("⚠️ ESP32 not connected. Waiting...", "WARNING")
                time.sleep(CHECK_INTERVAL)
                continue
            
            # Check server connection
            server_connected = check_server_connection()
            state.server_connected = server_connected
            update_connection_status()
            
            if not server_connected:
                log_message("⚠️ Server not running. Start server.py first!", "WARNING")
                time.sleep(CHECK_INTERVAL)
                continue
            
            # Get files from ESP32
            files = get_esp32_files()
            if not files:
                time.sleep(CHECK_INTERVAL)
                continue
            
            # Find pairs
            pairs = find_file_pairs(files)
            unsynced_pairs = {k: v for k, v in pairs.items() if k not in state.synced_files}
            
            if unsynced_pairs:
                log_message(f"📦 Found {len(unsynced_pairs)} new file pair(s)", "INFO")
                
                # Sort by index
                sorted_pairs = sorted(unsynced_pairs.items(), key=lambda x: int(x[0]) if x[0].isdigit() else x[0])
                
                for index, pair in sorted_pairs:
                    log_message(f"⬇️ Downloading pair #{index}...", "SYNC")
                    
                    # Download image
                    image_path = download_file(pair['image'])
                    if not image_path:
                        state.error_count += 1
                        continue
                    
                    # Download audio
                    audio_path = download_file(pair['audio'])
                    if not audio_path:
                        state.error_count += 1
                        continue
                    
                    log_message(f"⬆️ Uploading pair #{index} to server...", "SYNC")
                    
                    # Upload to server
                    if upload_to_server(image_path, audio_path, index):
                        state.mark_synced(index)
                        state.sync_count += 1
                        state.last_sync_time = datetime.now()
                        log_message(f"✅ Pair #{index} synced successfully!", "SUCCESS")
                        update_stats()
                    else:
                        state.error_count += 1
                        log_message(f"❌ Failed to upload pair #{index}", "ERROR")
                    
                    time.sleep(0.5)  # Brief pause between uploads
            
            # Check processing status
            status = get_processing_status()
            if status:
                state.pending_processing = status.get('unprocessed_count', 0)
                update_processing_status(status)
            
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            log_message(f"❌ Sync error: {e}", "ERROR")
            time.sleep(CHECK_INTERVAL)

# ==================== GUI ====================
root = None
log_text = None
status_labels = {}

def log_message(message, level="INFO"):
    """Log message with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # Color coding
    colors = {
        "INFO": "black",
        "SUCCESS": "green",
        "ERROR": "red",
        "WARNING": "orange",
        "SYNC": "blue"
    }
    
    formatted = f"[{timestamp}] {message}\n"
    print(formatted.strip())
    
    if log_text:
        try:
            log_text.insert(tk.END, formatted, level)
            log_text.tag_config("INFO", foreground=colors.get("INFO"))
            log_text.tag_config("SUCCESS", foreground=colors.get("SUCCESS"))
            log_text.tag_config("ERROR", foreground=colors.get("ERROR"))
            log_text.tag_config("WARNING", foreground=colors.get("WARNING"))
            log_text.tag_config("SYNC", foreground=colors.get("SYNC"))
            log_text.see(tk.END)
        except:
            pass

def update_connection_status():
    """Update connection status indicators."""
    if root and status_labels:
        try:
            esp32_status = "🟢 Connected" if state.esp32_connected else "🔴 Disconnected"
            server_status = "🟢 Running" if state.server_connected else "🔴 Offline"
            
            status_labels['esp32'].config(text=f"ESP32: {esp32_status}")
            status_labels['server'].config(text=f"Server: {server_status}")
        except:
            pass

def update_stats():
    """Update statistics display."""
    if root and status_labels:
        try:
            status_labels['synced'].config(text=f"Synced: {state.sync_count}")
            status_labels['errors'].config(text=f"Errors: {state.error_count}")
            if state.last_sync_time:
                time_str = state.last_sync_time.strftime("%H:%M:%S")
                status_labels['last_sync'].config(text=f"Last Sync: {time_str}")
        except:
            pass

def update_processing_status(status):
    """Update processing status."""
    if root and status_labels:
        try:
            unprocessed = status.get('unprocessed_count', 0)
            stats = status.get('processing_stats', {})
            total = stats.get('total_processed', 0)
            
            status_labels['processing'].config(
                text=f"Processing Queue: {unprocessed} pending | {total} processed"
            )
        except:
            pass

def create_gui():
    """Create the GUI window."""
    global root, log_text, status_labels
    
    root = tk.Tk()
    root.title("ESP32 Auto-Sync Client")
    root.geometry("800x600")
    
    # Header
    header = tk.Frame(root, bg="#2c3e50", padx=10, pady=10)
    header.pack(fill=tk.X)
    
    title = tk.Label(
        header,
        text="📡 ESP32 → Computer → Server Sync",
        font=("Arial", 16, "bold"),
        bg="#2c3e50",
        fg="white"
    )
    title.pack()
    
    # Status Panel
    status_frame = tk.Frame(root, bg="#ecf0f1", padx=10, pady=10)
    status_frame.pack(fill=tk.X)
    
    # Connection Status
    conn_frame = tk.Frame(status_frame, bg="#ecf0f1")
    conn_frame.pack(side=tk.LEFT, padx=10)
    
    status_labels['esp32'] = tk.Label(
        conn_frame,
        text="ESP32: 🔴 Disconnected",
        font=("Arial", 10),
        bg="#ecf0f1"
    )
    status_labels['esp32'].pack(anchor=tk.W)
    
    status_labels['server'] = tk.Label(
        conn_frame,
        text="Server: 🔴 Offline",
        font=("Arial", 10),
        bg="#ecf0f1"
    )
    status_labels['server'].pack(anchor=tk.W)
    
    # Stats
    stats_frame = tk.Frame(status_frame, bg="#ecf0f1")
    stats_frame.pack(side=tk.LEFT, padx=20)
    
    status_labels['synced'] = tk.Label(
        stats_frame,
        text="Synced: 0",
        font=("Arial", 10, "bold"),
        bg="#ecf0f1",
        fg="green"
    )
    status_labels['synced'].pack(anchor=tk.W)
    
    status_labels['errors'] = tk.Label(
        stats_frame,
        text="Errors: 0",
        font=("Arial", 10),
        bg="#ecf0f1",
        fg="red"
    )
    status_labels['errors'].pack(anchor=tk.W)
    
    status_labels['last_sync'] = tk.Label(
        stats_frame,
        text="Last Sync: Never",
        font=("Arial", 10),
        bg="#ecf0f1"
    )
    status_labels['last_sync'].pack(anchor=tk.W)
    
    # Processing Status
    proc_frame = tk.Frame(root, bg="#e8f5e9", padx=10, pady=5)
    proc_frame.pack(fill=tk.X)
    
    status_labels['processing'] = tk.Label(
        proc_frame,
        text="Processing Queue: Checking...",
        font=("Arial", 10),
        bg="#e8f5e9"
    )
    status_labels['processing'].pack()
    
    # Instructions
    instructions = tk.Label(
        root,
        text="💡 Connect to ESP32_CAM WiFi, then this client will automatically sync files to the server.",
        font=("Arial", 9),
        fg="gray",
        pady=5
    )
    instructions.pack()
    
    # Log Area
    log_frame = tk.Frame(root)
    log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    log_label = tk.Label(log_frame, text="📋 Activity Log:", font=("Arial", 10, "bold"))
    log_label.pack(anchor=tk.W)
    
    log_text = scrolledtext.ScrolledText(
        log_frame,
        font=("Consolas", 9),
        bg="#f8f9fa",
        wrap=tk.WORD
    )
    log_text.pack(fill=tk.BOTH, expand=True)
    
    # Footer
    footer = tk.Frame(root, bg="#ecf0f1", padx=10, pady=5)
    footer.pack(fill=tk.X)
    
    footer_text = tk.Label(
        footer,
        text="ESP32 IP: 192.168.4.1 | Server: localhost:5000",
        font=("Arial", 8),
        bg="#ecf0f1",
        fg="gray"
    )
    footer_text.pack()
    
    def on_closing():
        state.is_running = False
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    return root

# ==================== MAIN ====================
def main():
    """Main entry point."""
    # Create sync folder
    os.makedirs(SYNC_FOLDER, exist_ok=True)
    
    # Start sync thread
    sync_thread = threading.Thread(target=sync_cycle, daemon=True)
    sync_thread.start()
    
    # Create and run GUI
    gui = create_gui()
    gui.mainloop()

if __name__ == "__main__":
    main()

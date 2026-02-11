"""
Run the Memorable backend with Waitress (HTTP).

Use this when processing ESP32 sync: the Flask dev server often closes connections
during long Whisper/embedding requests; Waitress keeps connections open.

  python run_backend_waitress.py

Then run the sync tool and click PROCESS FILES. Backend runs at http://localhost:5000.

For the phone/web app (HTTPS), use: python server.py
"""

import os
import sys

# Ensure app is loaded (init_db, Whisper, etc.)
from server import app

if __name__ == "__main__":
    try:
        from waitress import serve
    except ImportError:
        print("Install waitress: pip install waitress")
        sys.exit(1)
    host = "0.0.0.0"
    port = 5001
    print(f"Memorable backend (Waitress) on http://{host}:{port}")
    print("Use this when running the ESP32 sync tool (Process Files).")
    print("Press Ctrl+C to stop.")
    serve(app, host=host, port=port, threads=2)

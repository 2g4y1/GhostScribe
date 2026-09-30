"""
Main launcher for GhostScribe.
Starts the modern Web UI by default, or accepts '--cli' flag for terminal mode.
"""

import sys
import threading
import time
import webbrowser

import uvicorn

from cli import main as run_cli
from utils import APP_URL, HOST, PORT, ensure_utf8_console


def open_browser():
    time.sleep(1.2)
    webbrowser.open(APP_URL)


if __name__ == "__main__":
    ensure_utf8_console()
    if "--cli" in sys.argv:
        run_cli()
    else:
        print("\n" + "=" * 60)
        print("🎙️  GHOSTSCRIBE - BOT-FREE AI MEETING RECORDER (Gemini)")
        print("=" * 60)
        print(f"🚀 Öffne Web-Oberfläche auf {APP_URL} ...")
        print("   Beenden: Strg+C drücken oder dieses Fenster schließen.")
        print("   Tipp: Du kannst das Tool auch im Terminal starten mit: python main.py --cli\n")

        # Browser nach kurzem Start automatisch öffnen
        threading.Thread(target=open_browser, daemon=True).start()
        uvicorn.run("app:app", host=HOST, port=PORT, reload=False)

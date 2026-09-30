"""
Main launcher for GhostScribe.
Starts the modern Web UI by default, or accepts '--cli' flag for terminal mode.
"""

import sys
import webbrowser

import uvicorn

from cli import main as run_cli

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli()
    else:
        print("\n" + "=" * 60)
        print("🎙️  GHOSTSCRIBE - BOT-FREE AI MEETING RECORDER (Gemini)")
        print("=" * 60)
        print("🚀 Öffne Web-Oberfläche auf http://localhost:8765 ...")
        print("   Tipp: Du kannst das Tool auch im Terminal starten mit: python main.py --cli\n")

        # Browser nach kurzem Start automatisch öffnen
        import threading
        import time

        def open_browser():
            time.sleep(1.2)
            webbrowser.open("http://localhost:8765")

        threading.Thread(target=open_browser, daemon=True).start()
        uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)

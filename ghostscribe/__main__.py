"""
Entry point: "python -m ghostscribe" starts the web interface, "python -m ghostscribe --cli" the terminal version.
"""

import sys
import threading
import time
import webbrowser

import uvicorn
from dotenv import load_dotenv

from ghostscribe.cli import main as run_cli
from ghostscribe.i18n import translate
from ghostscribe.utils import APP_URL, BANNER, HOST, PORT, ensure_utf8_console, print_banner


def open_browser():
    time.sleep(1.2)
    webbrowser.open(APP_URL)


def main():
    ensure_utf8_console()
    load_dotenv(".env")
    if "--cli" in sys.argv:
        run_cli()
        return

    print_banner(
        BANNER,
        translate("terminal.opening_ui", url=APP_URL),
        "   " + translate("terminal.stop_hint"),
        "   " + translate("terminal.cli_tip", command="python -m ghostscribe --cli"),
    )
    # Open the browser once the server had a moment to start
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("ghostscribe.app:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()

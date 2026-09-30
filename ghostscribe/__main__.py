"""
Entry point: "python -m ghostscribe" starts the web interface, "python -m ghostscribe --cli" the terminal version.
The web server itself runs in a child process ("--server") that the console window restarts with R.
"""

import sys
import threading

import uvicorn
from dotenv import load_dotenv

from ghostscribe import console
from ghostscribe.cli import main as run_cli
from ghostscribe.utils import HOST, PORT, ensure_utf8_console


def run_server():
    """The web server; the line "stop" or the end of its standard input (console closed) shuts it down."""
    server = uvicorn.Server(uvicorn.Config("ghostscribe.app:app", host=HOST, port=PORT, reload=False))

    def watch_stdin():
        for line in sys.stdin:
            if line.strip() == "stop":
                break
        server.should_exit = True

    threading.Thread(target=watch_stdin, daemon=True).start()
    server.run()


def main():
    ensure_utf8_console()
    load_dotenv(".env")
    if "--cli" in sys.argv:
        run_cli()
    elif "--server" in sys.argv:
        run_server()
    else:
        sys.exit(console.run())


if __name__ == "__main__":
    main()

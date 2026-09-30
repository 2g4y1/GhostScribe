"""
Entry point: "python -m ghostscribe" starts the web interface, "python -m ghostscribe --cli" the terminal version.
The web server itself runs in a child process ("--server") that the console window restarts with R.
"""

import os
import sys
import threading

import uvicorn
from dotenv import load_dotenv

from ghostscribe import console
from ghostscribe.cli import main as run_cli
from ghostscribe.utils import HOST, PORT, ensure_utf8_console


def take_stdin():
    """Takes the standard input (the pipe from the console window) for the stop line alone. New processes such as
    the voice workers and ffmpeg get NUL instead: on Windows they would share the pipe and hang at their start
    while the server waits for a line on it."""
    commands = os.fdopen(os.dup(sys.stdin.fileno()), encoding="utf-8", errors="replace")
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, sys.stdin.fileno())
    os.close(nul)
    return commands


def run_server():
    """The web server; the line "stop" or the end of its standard input (console closed) shuts it down."""
    # Selector loop instead of the Proactor loop that is the default on Windows: that one prints a ConnectionResetError
    # traceback whenever the browser aborts a request, e.g. while jumping around in the audio player
    config = uvicorn.Config("ghostscribe.app:app", host=HOST, port=PORT, reload=False, loop="asyncio:SelectorEventLoop")
    server = uvicorn.Server(config)
    commands = take_stdin()

    def watch_stdin():
        for line in commands:
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

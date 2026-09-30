"""
Entry point: "python -m ghostscribe" starts the web interface, "python -m ghostscribe --cli" the terminal version.
The web server itself runs in a child process ("--server") that the console window restarts with R.
"""

import argparse
import os
import sys
import threading

from dotenv import load_dotenv

from ghostscribe import __version__
from ghostscribe.utils import HOST, PORT, configure_logging, ensure_utf8_console


def take_stdin():
    """Takes the standard input (the pipe from the console window) for the stop line alone. New processes such as
    the voice workers and ffmpeg get NUL instead: on Windows they would share the pipe and hang at their start
    while the server waits for a line on it."""
    commands = os.fdopen(os.dup(sys.stdin.fileno()), encoding="utf-8", errors="replace")
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, sys.stdin.fileno())
    os.close(nul)
    return commands


def run_server() -> None:
    """The web server; the line "stop" or the end of its standard input (console closed) shuts it down."""
    import uvicorn

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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ghostscribe",
        description="Bot-free meeting recorder that turns Teams and Zoom calls into structured minutes.",
    )
    parser.add_argument("--cli", action="store_true", help="terminal version without the web interface")
    parser.add_argument("--server", action="store_true", help=argparse.SUPPRESS)  # started by the console window
    parser.add_argument("--version", action="version", version=f"GhostScribe {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    ensure_utf8_console()
    args = parse_args(argv)
    configure_logging()
    load_dotenv(".env")
    if args.cli:
        from ghostscribe.cli import main as run_cli

        run_cli()
    elif args.server:
        run_server()
    else:
        from ghostscribe import console

        sys.exit(console.run())


if __name__ == "__main__":
    main()

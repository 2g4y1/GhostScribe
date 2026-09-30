"""
Shared helpers and constants for GhostScribe.
"""

import contextlib
import json
import logging
import ntpath
import os
import subprocess
import sys
import tempfile
from typing import Any

HOST = "127.0.0.1"
PORT = 8765
APP_URL = f"http://localhost:{PORT}"
BANNER = "🎙️  GHOSTSCRIBE - BOT-FREE AI MEETING RECORDER (Gemini)"


def configure_logging() -> None:
    """Warnings and errors of all libraries, plus the info messages of GhostScribe itself, go to the console."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")
    logging.getLogger("ghostscribe").setLevel(logging.INFO)


def ensure_utf8_console() -> None:
    """Switches stdout/stderr to UTF-8 so emoji output works in every console and pipe."""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            with contextlib.suppress(OSError, ValueError):  # e.g. a stream that was replaced or already closed
                stream.reconfigure(encoding="utf-8", errors="replace")


def print_banner(*lines: str, width: int = 68) -> None:
    """Prints a framed block of lines to the terminal."""
    print("\n" + "=" * width)
    for line in lines:
        print(line)
    print("=" * width + "\n")


def format_duration(seconds: float) -> str:
    """Formats a duration in seconds as HH:MM:SS."""
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def open_file(path: str) -> None:
    """Opens a file in the default application of the system; does nothing if that is not possible."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 (opens the file like a double click)
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen(
                [opener, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    except OSError as e:
        logging.getLogger(__name__).info("Could not open %s: %s", path, e)


def file_name(path: str) -> str:
    """Last component of a path that may have been written on another operating system (/ or \\ separators)."""
    return ntpath.basename(path)


def write_text_atomic(path: str | os.PathLike, text: str) -> None:
    """Replaces the file in one step: a crash while writing leaves the old or the new content, never a mix."""
    directory = os.path.dirname(os.fspath(path)) or "."
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


def write_json_atomic(path: str | os.PathLike, data: Any, indent: int = 2) -> None:
    write_text_atomic(path, json.dumps(data, indent=indent, ensure_ascii=False))


def update_env_file(updates: dict[str, str], path: str = ".env") -> None:
    """Sets KEY=value entries in the .env file (replacing existing lines) and in os.environ."""
    for key, value in updates.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"Invalid value for {key}: line breaks are not allowed.")

    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

    written = set()
    for i, line in enumerate(lines):
        for key, value in updates.items():
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                written.add(key)

    missing = [key for key in updates if key not in written]
    if missing and lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.extend(f"{key}={updates[key]}\n" for key in missing)

    write_text_atomic(path, "".join(lines))
    os.environ.update(updates)

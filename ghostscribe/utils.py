"""
Shared helpers and constants for GhostScribe.
"""

import os
import sys

HOST = "127.0.0.1"
PORT = 8765
APP_URL = f"http://localhost:{PORT}"
BANNER = "🎙️  GHOSTSCRIBE - BOT-FREE AI MEETING RECORDER (Gemini)"


def ensure_utf8_console() -> None:
    """Switches stdout/stderr to UTF-8 so emoji output works in every Windows console and pipe."""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


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

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.environ.update(updates)

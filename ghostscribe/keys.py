"""
Single key presses in the console without Enter: msvcrt on Windows, termios on Linux and macOS.
"""

import contextlib
import os
import sys
import time
from collections.abc import Iterator


def supported() -> bool:
    """Keys can only be read from an interactive console."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):  # no standard input at all, or it was closed
        return False


if sys.platform == "win32":
    import msvcrt

    @contextlib.contextmanager
    def reading_keys() -> Iterator[None]:
        yield  # the Windows console delivers single keys anyway

    def wait_for_key(timeout: float | None = None) -> str | None:
        """The next key (lowercase), or None if none was pressed within the timeout."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while deadline is None or time.monotonic() < deadline:
            if msvcrt.kbhit():
                return msvcrt.getwch().lower()
            time.sleep(0.05)
        return None

else:
    import select
    import termios
    import tty

    @contextlib.contextmanager
    def reading_keys() -> Iterator[None]:
        """Delivers keys without Enter and without echo while active; Ctrl+C keeps working."""
        fd = sys.stdin.fileno()
        previous = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)

    def wait_for_key(timeout: float | None = None) -> str | None:
        """The next key (lowercase), or None if none was pressed within the timeout."""
        fd = sys.stdin.fileno()
        if not select.select([fd], [], [], timeout)[0]:
            return None
        return os.read(fd, 8).decode("utf-8", errors="ignore")[:1].lower()

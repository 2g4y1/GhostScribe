"""
Console window of the web version: the server runs in a child process, its output scrolls above a banner that
always stays at the bottom, and R restarts the server (new code and .env) without closing the window.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from dotenv import load_dotenv

from ghostscribe.i18n import translate
from ghostscribe.utils import APP_URL, BANNER, HOST, PORT

SEPARATOR = "=" * 68
STOP_TIMEOUT = 15  # seconds the server gets to shut down before it is terminated
CONFIRM_SECONDS = 10  # time to confirm a restart
BUSY_MESSAGES = {"recording": "terminal.restart_busy_recording", "processing": "terminal.restart_busy_processing"}


def _enable_escape_sequences() -> bool:
    """Lets the console move the cursor (needed to keep the banner at the bottom)."""
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # standard output
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False
    return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING


class Footer:
    """Prints lines above a banner that stays at the bottom of the window (printed once without escape sequences)."""

    def __init__(self):
        self.lines = []
        self._drawn = False
        self._shown = False
        self._moves = _enable_escape_sequences()
        self._lock = threading.Lock()

    def show(self, lines: list[str]) -> None:
        with self._lock:
            self._clear()
            self.lines = lines
            self._draw()

    def print(self, text: str) -> None:
        with self._lock:
            self._clear()
            sys.stdout.write(text + "\n")
            self._draw()

    def _rows(self) -> int:
        width = max(1, shutil.get_terminal_size().columns)
        return sum(max(1, -(-len(line) // width)) for line in self.lines)

    def _clear(self) -> None:
        if self._drawn:
            sys.stdout.write(f"\x1b[{self._rows()}F\x1b[J")  # to the first banner row, erase to the end
            self._drawn = False

    def _draw(self) -> None:
        if self._moves or not self._shown:
            sys.stdout.write("\n".join(self.lines) + "\n")
            self._shown = True
            self._drawn = self._moves
        sys.stdout.flush()


def _keys_supported() -> bool:
    return os.name == "nt" and sys.stdin.isatty()


def footer_lines() -> list[str]:
    keys = translate("terminal.keys") if _keys_supported() else translate("terminal.stop_hint")
    return [SEPARATOR, BANNER, translate("terminal.web_ui_footer", url=APP_URL), keys, SEPARATOR]


def server_status() -> str | None:
    """Status of the running server ("idle", "recording", ...) or None if it does not answer."""
    request = urllib.request.Request(f"http://{HOST}:{PORT}/api/status", headers={"Host": f"localhost:{PORT}"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.load(response).get("status")
    except (OSError, ValueError):
        return None


def _open_browser_when_ready(footer: Footer) -> None:
    for _ in range(40):
        if server_status():
            footer.print(translate("terminal.opening_ui", url=APP_URL))
            webbrowser.open(APP_URL)
            return
        time.sleep(0.25)


def _listen_for_keys(on_restart) -> None:
    import msvcrt

    while True:
        if msvcrt.getwch().lower() == "r":
            on_restart()


def _confirm(footer: Footer) -> bool:
    """R is pressed quickly by mistake: the restart needs J (or Y) within CONFIRM_SECONDS."""
    import msvcrt

    footer.print(translate("terminal.restart_confirm", seconds=CONFIRM_SECONDS))
    deadline = time.monotonic() + CONFIRM_SECONDS
    while time.monotonic() < deadline:
        if msvcrt.kbhit():
            return msvcrt.getwch().lower() in ("j", "y")
        time.sleep(0.05)
    return False


def _start_server() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "ghostscribe", "--server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _relay(output, footer: Footer) -> None:
    for line in output:
        footer.print(line.rstrip("\n"))


def _stop(server: subprocess.Popen) -> None:
    """Asks the server to shut down (a line on its standard input) and terminates it if it hangs."""
    try:
        if server.stdin:
            server.stdin.write("stop\n")
            server.stdin.flush()
    except OSError:
        pass  # the server has already ended
    try:
        server.wait(STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        server.terminate()
        server.wait()


def run() -> int:
    """Runs the server until Ctrl+C or until it ends by itself; returns its exit code."""
    footer = Footer()
    footer.show(footer_lines())
    footer.print(translate("terminal.cli_tip", command="python -m ghostscribe --cli"))
    if not os.getenv("GEMINI_API_KEY", "").strip():
        footer.print(translate("terminal.no_api_key"))
    restart = threading.Event()

    def request_restart():
        busy = BUSY_MESSAGES.get(server_status() or "")
        if busy:
            footer.print(translate(busy))
        elif _confirm(footer):
            restart.set()
        else:
            footer.print(translate("terminal.restart_cancelled"))

    if _keys_supported():
        threading.Thread(target=_listen_for_keys, args=(request_restart,), daemon=True).start()
    threading.Thread(target=_open_browser_when_ready, args=(footer,), daemon=True).start()

    while True:
        server = _start_server()
        relay = threading.Thread(target=_relay, args=(server.stdout, footer), daemon=True)
        relay.start()
        try:
            while server.poll() is None and not restart.wait(0.2):
                pass
        except KeyboardInterrupt:  # Ctrl+C reaches the server too, it shuts down by itself
            try:
                server.wait(STOP_TIMEOUT)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                server.terminate()
            relay.join(2)
            return 0
        if not restart.is_set():  # the server ended by itself, e.g. because the port is in use
            relay.join(2)
            return server.returncode
        restart.clear()
        footer.print(translate("terminal.restarting"))
        _stop(server)
        relay.join(2)
        load_dotenv(".env", override=True)  # e.g. another interface language
        footer.show(footer_lines())

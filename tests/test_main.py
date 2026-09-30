import io
import subprocess
import sys
from pathlib import Path

import uvicorn

from ghostscribe import __main__ as entry

SERVER = """
import subprocess, sys
from ghostscribe.__main__ import take_stdin
commands = take_stdin()
child = subprocess.run([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], capture_output=True, text=True, timeout=30)
print(child.stdout.strip())
print(commands.readline().strip())
"""


def test_new_processes_do_not_share_the_server_pipe():
    """Only the stop thread reads the pipe from the console window; a new process gets NUL as standard input
    (on Windows the voice workers hung at their start while the server waited on the shared pipe)."""
    root = Path(__file__).resolve().parents[1]
    server = subprocess.run(
        [sys.executable, "-c", SERVER],
        input="stop\n",
        capture_output=True,
        text=True,
        timeout=60,
        cwd=root,
        check=False,
    )
    assert server.stdout.split() == ["''", "stop"], server.stderr


def test_version_and_help_on_the_command_line():
    root = Path(__file__).resolve().parents[1]
    run = [sys.executable, "-m", "ghostscribe"]

    version = subprocess.run([*run, "--version"], capture_output=True, text=True, timeout=60, cwd=root, check=True)
    usage = subprocess.run([*run, "--help"], capture_output=True, text=True, timeout=60, cwd=root, check=True)

    assert version.stdout.startswith("GhostScribe ")
    assert "--cli" in usage.stdout and "--server" not in usage.stdout  # started by the console window only


def test_ctrl_c_ends_the_server_without_a_traceback(monkeypatch):
    """Uvicorn shuts down on Ctrl+C and then raises it again; the console window should not show that as a crash."""

    def interrupted(server):
        raise KeyboardInterrupt

    monkeypatch.setattr(uvicorn.Server, "run", interrupted)
    monkeypatch.setattr(entry, "take_stdin", lambda: io.StringIO(""))

    entry.run_server()  # returns normally

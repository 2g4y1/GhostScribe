import subprocess
import sys
from pathlib import Path

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
        [sys.executable, "-c", SERVER], input="stop\n", capture_output=True, text=True, timeout=60, cwd=root
    )
    assert server.stdout.split() == ["''", "stop"], server.stderr

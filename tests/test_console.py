"""The console window of the web version: the banner at the bottom, the restart question and the shortcut key."""

import os
import shutil
import sys
from pathlib import Path

import pytest

from ghostscribe import console, shortcut
from ghostscribe.i18n import LocalizedError, translate


class RecordingFooter:
    """Stands in for the banner and records what it shows."""

    def __init__(self, live=True):
        self.live = live
        self.shown = []
        self.printed = []

    def show(self, lines):
        self.shown.append(lines)

    def print(self, text):
        self.printed.append(text)


def press(monkeypatch, *keys):
    """The keys that keys.wait_for_key returns one after the other; None stands for a timeout."""
    pending = list(keys)
    monkeypatch.setattr(console.keys, "wait_for_key", lambda timeout=None: pending.pop(0))


def question(seconds):
    return translate("terminal.restart_confirm", seconds=seconds)


def test_the_restart_question_takes_the_place_of_the_keys_with_a_countdown(monkeypatch):
    press(monkeypatch, None, None, "j")
    footer = RecordingFooter()

    assert console._confirm(footer)

    assert [lines[3] for lines in footer.shown[:3]] == [
        f"{console.HIGHLIGHT} {question(seconds)} {console.RESET}" for seconds in (10, 9, 8)
    ]
    assert all(lines[1] == console.BANNER for lines in footer.shown)
    assert footer.shown[-1] == console.footer_lines()  # the keys are back
    assert footer.printed == []  # nothing that could scroll away


@pytest.mark.parametrize("keys", [("n",), (" ",), (None,) * console.CONFIRM_SECONDS])
def test_another_key_or_the_timeout_cancels_the_restart(monkeypatch, keys):
    press(monkeypatch, *keys)
    footer = RecordingFooter()

    assert not console._confirm(footer)
    assert footer.shown[-1] == console.footer_lines()


def test_without_cursor_movements_the_question_is_a_line(monkeypatch):
    press(monkeypatch, "y")
    footer = RecordingFooter(live=False)

    assert console._confirm(footer)
    assert footer.printed == [question(console.CONFIRM_SECONDS)] and footer.shown == []


def test_the_banner_stays_below_new_lines_and_is_cleared_by_its_width(monkeypatch, capsys):
    monkeypatch.setattr(console, "_enable_escape_sequences", lambda: True)
    monkeypatch.setattr(shutil, "get_terminal_size", lambda fallback=None: os.terminal_size((10, 20)))
    footer = console.Footer()

    footer.show(["=" * 10, f"{console.HIGHLIGHT} 🔄 Restart? {console.RESET}"])  # 1 + 2 rows of 10 columns
    footer.print("server line")

    output = capsys.readouterr().out
    assert output.endswith("\x1b[3F\x1b[Jserver line\n==========\n\x1b[30;43m 🔄 Restart? \x1b[0m\n")


@pytest.mark.parametrize(
    ("text", "columns"),
    [
        ("GhostScribe", 11),
        ("🔄 Restart", 10),  # the emoji takes two columns
        ("⌨️  R", 5),  # a character in emoji style too
        (f"{console.HIGHLIGHT} ok {console.RESET}", 4),  # colors take none
        ("Größe", 5),
    ],
)
def test_display_width(text, columns):
    assert console.display_width(text) == columns


def test_the_keys_start_their_actions(monkeypatch):
    pending = ["d", "x", "r"]
    done = []

    def next_key(timeout=None):
        if not pending:
            raise KeyboardInterrupt  # ends the endless loop of the test
        return pending.pop(0)

    monkeypatch.setattr(console.keys, "wait_for_key", next_key)

    with pytest.raises(KeyboardInterrupt):
        console._listen_for_keys({"r": lambda: done.append("restart"), "d": lambda: done.append("shortcut")})
    assert done == ["shortcut", "restart"]


def test_d_reports_every_shortcut_it_created(monkeypatch):
    written = [Path("Desktop", "ghostscribe.desktop"), Path("applications", "ghostscribe.desktop")]
    monkeypatch.setattr(shortcut, "create", lambda: written)
    footer = RecordingFooter()

    console._create_shortcut(footer)

    assert footer.printed == [translate("terminal.shortcut_created", path=path) for path in written]


@pytest.mark.parametrize(
    "error", [OSError("PowerShell: access denied"), LocalizedError("error.start_script_missing", path="start.sh")]
)
def test_d_reports_why_no_shortcut_was_created(monkeypatch, error):
    def fail():
        raise error

    monkeypatch.setattr(shortcut, "create", fail)
    footer = RecordingFooter()

    console._create_shortcut(footer)

    assert footer.printed == [translate("terminal.shortcut_failed", error=error)]


def test_d_explains_a_desktop_that_may_not_be_written(monkeypatch):
    def refuse():
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(shortcut, "create", refuse)
    footer = RecordingFooter()

    console._create_shortcut(footer)

    if sys.platform == "darwin":  # macOS asks whether the Terminal may use the desktop folder
        assert footer.printed == [translate("terminal.shortcut_denied_macos")]
    else:
        assert footer.printed == [translate("terminal.shortcut_failed", error="[Errno 1] Operation not permitted")]

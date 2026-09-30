"""Desktop shortcuts for Windows, macOS and Linux, written into temporary folders."""

import base64
import hashlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ghostscribe import shortcut
from ghostscribe.i18n import LocalizedError, translate

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="launchers of macOS and Linux")
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows shell")

# Stands in for start.sh: tells where it ran and exits with GHOSTSCRIBE_TEST_STATUS
FAKE_START = (
    '#!/bin/sh\ncd "$(dirname "$0")" || exit 1\necho "started in $(pwd -P)"\nexit "${GHOSTSCRIBE_TEST_STATUS:-0}"\n'
)


def portable_folder(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "start.sh").write_text(FAKE_START, encoding="utf-8", newline="\n")
    (path / "start.bat").write_text("@echo off\r\n", encoding="utf-8")
    return path


@pytest.fixture
def app_dir(tmp_path):
    return portable_folder(tmp_path / "Ghost Scribe")


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    """Keeps the settings and launchers of the desktop environment in the temporary folder."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def helpers(monkeypatch):
    """Records PowerShell, osascript and gio instead of running them, as if they were installed."""
    calls = []
    monkeypatch.setattr(shortcut, "_run", lambda command, **options: calls.append(command))
    monkeypatch.setattr(shortcut.shutil, "which", lambda name: f"/usr/bin/{name}")
    return calls


def desktop_entry(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "[Desktop Entry]"
    return dict(line.split("=", 1) for line in lines[1:])


def exec_arguments(value: str) -> list[str]:
    """Splits an Exec value as the Desktop Entry Specification describes it: string escapes first, then arguments in
    double quotes with \\", \\`, \\$ and \\\\ as escapes, finally %% as a literal %."""
    escapes = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
    unescaped = re.sub(r"\\(.)", lambda m: escapes.get(m.group(1), m.group(0)), value)
    arguments = []
    for quoted, plain in re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', unescaped):
        arguments.append(plain or re.sub(r'\\(["`$\\])', r"\1", quoted))
    return [argument.replace("%%", "%") for argument in arguments]


def test_windows_shortcut_is_made_by_powershell_with_the_paths_in_the_environment(app_dir, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(shortcut, "_run", lambda command, env: calls.append((command, env)))

    path = shortcut.windows_shortcut(app_dir, tmp_path)

    [(command, env)] = calls
    assert path == tmp_path / "GhostScribe.lnk"
    assert command[1:4] == ["-NoProfile", "-NonInteractive", "-EncodedCommand"]
    assert "CreateShortcut($env:GHOSTSCRIBE_SHORTCUT)" in base64.b64decode(command[4]).decode("utf-16-le")
    assert env["GHOSTSCRIBE_SHORTCUT"] == str(path)
    assert env["GHOSTSCRIBE_TARGET"] == str(app_dir / "start.bat")
    assert env["GHOSTSCRIBE_DIR"] == str(app_dir)
    assert env["GHOSTSCRIBE_ICON"] == f"{shortcut.ICON_ICO},0" and shortcut.ICON_ICO.is_file()
    assert env["GHOSTSCRIBE_DESCRIPTION"] == translate("shortcut.description")


def test_nothing_is_created_without_the_start_script(tmp_path, helpers):
    with pytest.raises(LocalizedError, match=r"start\.bat"):
        shortcut.windows_shortcut(tmp_path / "installed as a package", tmp_path)
    with pytest.raises(LocalizedError, match=r"start\.sh"):
        shortcut.linux_shortcuts(tmp_path / "installed as a package", tmp_path)

    assert helpers == [] and list(tmp_path.iterdir()) == []


@windows_only
def test_windows_shortcut_starts_start_bat_in_its_folder(app_dir, tmp_path):
    path = shortcut.windows_shortcut(app_dir, tmp_path)

    script = "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); $s.TargetPath; $s.WorkingDirectory"
    result = subprocess.run(
        [shortcut._powershell(), "-NoProfile", "-Command", script],
        env={**os.environ, "LNK": str(path)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == [str(app_dir / "start.bat"), str(app_dir)]


@windows_only
def test_windows_desktop_folder_is_found():
    assert shortcut.windows_desktop().is_dir()


@posix_only
def test_macos_command_file_runs_start_sh_and_gets_the_icon(app_dir, tmp_path, helpers):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    path = shortcut.macos_shortcut(app_dir, desktop)

    assert path == desktop / "GhostScribe.command"
    assert stat.S_IMODE(path.stat().st_mode) == 0o755
    result = subprocess.run([str(path)], capture_output=True, text=True, check=True, cwd=tmp_path)
    assert result.stdout == f"started in {app_dir.resolve()}\n"
    [command] = helpers
    assert command[:4] == ["osascript", "-l", "JavaScript", "-e"]
    assert command[-2:] == [str(shortcut.ICON_PNG), str(path)] and shortcut.ICON_PNG.is_file()


@pytest.mark.skipif(sys.platform != "darwin", reason="needs the Finder")
def test_macos_shortcut_gets_its_icon_from_the_finder(app_dir, tmp_path):
    path = shortcut.macos_shortcut(app_dir, tmp_path)

    attributes = subprocess.run(["/usr/bin/xattr", str(path)], capture_output=True, text=True, check=True).stdout
    assert "com.apple.ResourceFork" in attributes  # where the Finder keeps a custom icon


@posix_only
def test_linux_launcher_goes_into_the_menu_and_onto_the_translated_desktop(app_dir, tmp_path, helpers, monkeypatch):
    home = tmp_path / "home"
    (home / "Schreibtisch").mkdir(parents=True)
    (home / ".config").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text(
        'XDG_MUSIC_DIR="$HOME/Musik"\nXDG_DESKTOP_DIR="$HOME/Schreibtisch"\n'
    )
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    written = shortcut.linux_shortcuts(app_dir, home)

    on_desktop = home / "Schreibtisch" / "ghostscribe.desktop"
    in_menu = home / ".local" / "share" / "applications" / "ghostscribe.desktop"
    assert written == [on_desktop, in_menu]
    assert on_desktop.read_text(encoding="utf-8") == in_menu.read_text(encoding="utf-8")
    assert stat.S_IMODE(on_desktop.stat().st_mode) == 0o755
    entry = desktop_entry(on_desktop)
    assert (entry["Type"], entry["Name"], entry["Terminal"]) == ("Application", "GhostScribe", "true")
    assert entry["Path"] == str(app_dir) and Path(entry["Icon"]) == shortcut.ICON_PNG
    assert exec_arguments(entry["Exec"]) == [
        "sh",
        "-c",
        shortcut._LINUX_EXEC_SCRIPT,
        "sh",
        str(app_dir / "start.sh"),
        translate("shortcut.press_enter"),
    ]
    # Only the launcher on the desktop has to be marked as trusted (GNOME; Xfce by the checksum of its content)
    assert helpers == [
        ["gio", "set", str(on_desktop), "metadata::trusted", "true"],
        [
            "gio",
            "set",
            str(on_desktop),
            "metadata::xfce-exe-checksum",
            hashlib.sha256(on_desktop.read_bytes()).hexdigest(),
        ],
    ]


@posix_only
def test_linux_launcher_quotes_every_path(tmp_path, xdg, helpers):
    app_dir = portable_folder(tmp_path / 'Ghost "Scribe" $HOME `id` 100% back\\slash')

    [launcher] = shortcut.linux_shortcuts(app_dir, tmp_path / "no desktop")

    arguments = exec_arguments(desktop_entry(launcher)["Exec"])
    assert arguments[4] == str(app_dir / "start.sh")
    # Run as the desktop environment would: start.sh runs in its folder, the terminal closes afterwards
    result = subprocess.run(arguments, capture_output=True, text=True, check=True, input="")
    assert result.stdout == f"started in {app_dir.resolve()}\n"


@posix_only
def test_linux_launcher_keeps_the_window_open_when_ghostscribe_fails(app_dir, tmp_path, xdg, helpers, monkeypatch):
    monkeypatch.setenv("GHOSTSCRIBE_TEST_STATUS", "1")
    [launcher] = shortcut.linux_shortcuts(app_dir, tmp_path / "no desktop")

    result = subprocess.run(
        exec_arguments(desktop_entry(launcher)["Exec"]),
        capture_output=True,
        text=True,
        input="\n",
        timeout=10,
        check=True,
    )

    assert result.stdout == f"started in {app_dir.resolve()}\n\n{translate('shortcut.press_enter')}\n"


@posix_only
@pytest.mark.parametrize(
    ("line", "desktop"),
    [
        ('XDG_DESKTOP_DIR="$HOME/Bureau"', "home/Bureau"),
        ('XDG_DESKTOP_DIR="$HOME/"', "home"),  # no desktop of its own: nothing is put there
        ('XDG_DESKTOP_DIR="{tmp}/elsewhere"', "elsewhere"),
        ("", "home/Desktop"),
    ],
)
def test_linux_desktop_folder_comes_from_xdg_user_dirs(tmp_path, xdg, line, desktop):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "user-dirs.dirs").write_text(line.replace("{tmp}", str(tmp_path)) + "\n")

    assert shortcut.linux_desktop(tmp_path / "home") == tmp_path / desktop


@posix_only
def test_create_puts_the_shortcut_into_the_home_folder_of_this_system(app_dir, tmp_path, xdg, helpers, monkeypatch):
    monkeypatch.setattr(shortcut.Path, "home", lambda: tmp_path / "home")
    (tmp_path / "home" / "Desktop").mkdir(parents=True)

    written = shortcut.create(app_dir)

    if sys.platform == "darwin":
        assert written == [tmp_path / "home" / "Desktop" / "GhostScribe.command"]
    else:
        assert written == [
            tmp_path / "home" / "Desktop" / "ghostscribe.desktop",
            tmp_path / "data" / "applications" / "ghostscribe.desktop",
        ]


def test_a_failing_helper_program_reports_its_message():
    with pytest.raises(OSError, match="no COM here"):
        shortcut._run([sys.executable, "-c", "import sys; print('starting'); sys.exit('no COM here')"])
    with pytest.raises(OSError, match="timed out"):
        shortcut._run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.5)


@posix_only
def test_launcher_works_even_if_it_cannot_be_marked_as_trusted(app_dir, tmp_path, xdg, monkeypatch):
    calls = []

    def no_session(command, **options):
        calls.append(command)
        raise OSError("gio: Setting attribute metadata::trusted not supported")

    monkeypatch.setattr(shortcut, "_run", no_session)
    monkeypatch.setattr(shortcut.shutil, "which", lambda name: f"/usr/bin/{name}")
    (tmp_path / "home" / "Desktop").mkdir(parents=True)

    written = shortcut.linux_shortcuts(app_dir, tmp_path / "home")

    assert all(path.is_file() for path in written) and len(written) == 2
    assert len(calls) == 1  # gives up after the first refusal

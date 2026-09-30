"""
Shortcut that starts GhostScribe like a double click on the start script of its folder (key D in the console window):
a .lnk file on the Windows desktop, a .command file on the macOS desktop (opens in the Terminal) and a .desktop
launcher on Linux, in the applications menu and on the desktop.
"""

import hashlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from base64 import b64encode
from pathlib import Path

from ghostscribe.i18n import LocalizedError, translate

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
APP_DIR = PACKAGE_DIR.parent  # the folder with the start scripts
ICON_ICO = PACKAGE_DIR / "static" / "icon.ico"
ICON_PNG = PACKAGE_DIR / "static" / "icon-192.png"
NAME = "GhostScribe"
HELPER_TIMEOUT = 30  # seconds for PowerShell and osascript
TRUST_TIMEOUT = 5  # seconds for gio, which waits for the desktop session


def create(app_dir: Path = APP_DIR) -> list[Path]:
    """Creates or renews the shortcut of this system and returns the files written. Raises LocalizedError or OSError,
    PermissionError when the desktop may not be written (macOS asks the user first)."""
    if sys.platform == "win32":
        written = [windows_shortcut(app_dir, windows_desktop())]
    elif sys.platform == "darwin":
        written = [macos_shortcut(app_dir, Path.home() / "Desktop")]
    else:
        written = linux_shortcuts(app_dir, Path.home())
    return written


def _start_script(app_dir: Path, name: str) -> Path:
    script = app_dir / name
    if not script.is_file():  # e.g. GhostScribe was installed as a package, without the portable folder
        raise LocalizedError("error.start_script_missing", path=script)
    return script


def _run(command: list[str], timeout: float = HELPER_TIMEOUT, env: dict[str, str] | None = None) -> None:
    """Runs a helper program and raises OSError with its message if it fails."""
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            # Windows: PowerShell gets no console, so it cannot change the modes of the console window
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as e:
        raise OSError(f"{Path(command[0]).name}: timed out") from e
    if result.returncode:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise OSError(f"{Path(command[0]).name}: {lines[-1] if lines else f'exit code {result.returncode}'}")


def _write_launcher(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


# The Windows Script Host creates the .lnk file. The paths arrive as environment variables, so no quoting can go wrong,
# and an error message is written as UTF-8, independent of the code page of the console.
_POWERSHELL_SCRIPT = """
$ProgressPreference = 'SilentlyContinue'
try {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($env:GHOSTSCRIBE_SHORTCUT)
    $shortcut.TargetPath = $env:GHOSTSCRIBE_TARGET
    $shortcut.WorkingDirectory = $env:GHOSTSCRIBE_DIR
    $shortcut.IconLocation = $env:GHOSTSCRIBE_ICON
    $shortcut.Description = $env:GHOSTSCRIBE_DESCRIPTION
    $shortcut.Save()
} catch {
    $message = [Text.Encoding]::UTF8.GetBytes($_.Exception.Message)
    [Console]::OpenStandardError().Write($message, 0, $message.Length)
    exit 1
}
"""


def _powershell() -> str:
    """Windows PowerShell from the system folder, not whatever is found first in PATH."""
    path = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return str(path) if path.is_file() else "powershell.exe"


def windows_shortcut(app_dir: Path, desktop: Path) -> Path:
    """GhostScribe.lnk on the desktop: starts start.bat in its folder, with the GhostScribe icon."""
    shortcut = desktop / f"{NAME}.lnk"
    env = {
        **os.environ,
        "GHOSTSCRIBE_SHORTCUT": str(shortcut),
        "GHOSTSCRIBE_TARGET": str(_start_script(app_dir, "start.bat")),
        "GHOSTSCRIBE_DIR": str(app_dir),
        "GHOSTSCRIBE_ICON": f"{ICON_ICO},0",
        "GHOSTSCRIBE_DESCRIPTION": translate("shortcut.description"),
    }
    script = b64encode(_POWERSHELL_SCRIPT.encode("utf-16-le")).decode("ascii")
    _run([_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand", script], env=env)
    return shortcut


if sys.platform == "win32":
    import ctypes
    import uuid

    FOLDERID_DESKTOP = uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")

    def windows_desktop() -> Path:
        """The desktop folder, also when it has been moved, e.g. into OneDrive."""
        folder_id = (ctypes.c_ubyte * 16).from_buffer_copy(FOLDERID_DESKTOP.bytes_le)
        path = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(path))
        try:
            if result or not path.value:
                raise OSError(f"No desktop folder (SHGetKnownFolderPath: {result & 0xFFFFFFFF:#010x})")
            return Path(path.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(path)  # also after an error, as the documentation demands


# Gives the .command file the GhostScribe icon and hides its extension in the Finder (JavaScript for Automation)
_MACOS_ICON_SCRIPT = """
ObjC.import('AppKit');
function run(argv) {
    const [icon, file] = argv;
    $.NSWorkspace.sharedWorkspace.setIconForFileOptions($.NSImage.alloc.initWithContentsOfFile(icon), file, 0);
    const hidden = $.NSDictionary.dictionaryWithObjectForKey($.NSNumber.numberWithBool(true), $.NSFileExtensionHidden);
    $.NSFileManager.defaultManager.setAttributesOfItemAtPathError(hidden, file, null);
}
"""


def macos_shortcut(app_dir: Path, desktop: Path) -> Path:
    """GhostScribe.command on the desktop: a double click runs start.sh in a Terminal window, like start.command."""
    start = _start_script(app_dir, "start.sh")
    shortcut = desktop / f"{NAME}.command"
    _write_launcher(shortcut, f"#!/bin/sh\n# {translate('shortcut.description')}\nexec sh {shlex.quote(str(start))}\n")
    if shutil.which("osascript"):
        try:
            _run(["osascript", "-l", "JavaScript", "-e", _MACOS_ICON_SCRIPT, str(ICON_PNG), str(shortcut)])
        except OSError as e:  # the shortcut works without its icon
            logger.debug("Could not set the icon of %s: %s", shortcut, e)
    return shortcut


def linux_desktop(home: Path) -> Path:
    """The desktop folder from xdg-user-dirs (it has the language of the system, e.g. ~/Schreibtisch), else ~/Desktop."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
    try:
        match = re.search(r'^XDG_DESKTOP_DIR="([^"]*)"', config.read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        match = None
    if match and match.group(1).startswith("$HOME"):
        return home / match.group(1).removeprefix("$HOME").lstrip("/")
    if match and match.group(1).startswith("/"):
        return Path(match.group(1))
    return home / "Desktop"


def _escape(value: str) -> str:
    """A string value of a desktop entry."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")


def _exec_argument(value: str) -> str:
    """An argument of the Exec key, quoted as the Desktop Entry Specification demands if it has to be."""
    if re.fullmatch(r"[\w./:+,@=-]+", value):
        return value
    return _escape('"' + re.sub(r'(["`$\\])', r"\\\1", value) + '"').replace("%", "%%")


# Runs start.sh; when it fails (e.g. the setup), the window stays open until Enter so that the error can be read.
# Ctrl+C must not end this shell before GhostScribe has shut down: the terminal would close and cut it short.
_LINUX_EXEC_SCRIPT = 'trap : INT; sh "$1" || { echo; echo "$2"; read -r _; }'


def linux_shortcuts(app_dir: Path, home: Path) -> list[Path]:
    """The launcher in the applications menu and, if there is a desktop folder, on the desktop."""
    start = _start_script(app_dir, "start.sh")
    command = ["sh", "-c", _LINUX_EXEC_SCRIPT, "sh", str(start), translate("shortcut.press_enter")]
    entry = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={NAME}",
            f"Comment={_escape(translate('shortcut.description'))}",
            "Exec=" + " ".join(_exec_argument(argument) for argument in command),
            f"Path={_escape(str(app_dir))}",
            f"Icon={_escape(str(ICON_PNG))}",
            "Terminal=true",
            "Categories=AudioVideo;Office;",
            "",
        ]
    )
    data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    menu_entry = data_home / "applications" / "ghostscribe.desktop"
    menu_entry.parent.mkdir(parents=True, exist_ok=True)
    _write_launcher(menu_entry, entry)
    written = [menu_entry]
    desktop = linux_desktop(home)
    if desktop.is_dir() and desktop != home:
        _write_launcher(desktop / "ghostscribe.desktop", entry)
        _trust(desktop / "ghostscribe.desktop", entry)
        written.insert(0, desktop / "ghostscribe.desktop")
    return written


def _trust(launcher: Path, entry: str) -> None:
    """The desktop icons of GNOME and Xfce only start launchers that are marked as trusted."""
    if not shutil.which("gio"):
        return
    checksum = hashlib.sha256(entry.encode("utf-8")).hexdigest()
    for attribute, value in (("metadata::trusted", "true"), ("metadata::xfce-exe-checksum", checksum)):
        try:
            _run(["gio", "set", str(launcher), attribute, value], timeout=TRUST_TIMEOUT)
        except OSError as e:  # e.g. no desktop session; a right click on the icon allows launching it then
            logger.debug("Could not mark %s as trusted: %s", launcher, e)
            return

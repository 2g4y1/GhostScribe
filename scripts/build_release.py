"""
Builds the portable release for Windows, macOS and Linux: dist/GhostScribe-v<version>.zip plus its SHA-256 checksum.

The archive contains only what end users need to run GhostScribe. Developer tooling
(tests, scripts, configs), secrets (.env) and personal data (recordings, meetings) are never packed.
With SOURCE_DATE_EPOCH set (the release workflow uses the time of the tagged commit), every build of the same
commit produces a byte-identical archive.
Usage: python scripts/build_release.py
"""

import hashlib
import os
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_FILES = [
    "start.bat",
    "install_requirements.bat",
    "start.sh",
    "install_requirements.sh",
    "start.command",
    "requirements.txt",
    ".env.example",
    "README.md",
    "LICENSE",
]
EXECUTABLES = {"start.sh", "install_requirements.sh", "start.command"}
PACKAGE_DIR = "ghostscribe"
EMPTY_DIRS = ["recordings", "meetings"]
# Last line of defense in case one of the lists above is ever extended carelessly
FORBIDDEN = re.compile(
    r"(^|/)\.env$|\.(wav|mp3|flac|pcm)$|^(recordings|meetings|models|voices)/|__pycache__|\.pyc$|node_modules"
)


def project_version() -> str:
    init = (ROOT / PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', init, re.MULTILINE)
    if not match:
        sys.exit("No __version__ found in ghostscribe/__init__.py")
    return match.group(1)


def release_files() -> list[Path]:
    package_files = (ROOT / PACKAGE_DIR).rglob("*")
    code_and_assets = [p for p in package_files if p.is_file() and "__pycache__" not in p.parts]
    return [ROOT / name for name in RELEASE_FILES] + sorted(code_and_assets)


def zip_entry(name: str, path: Path | None) -> zipfile.ZipInfo:
    """Archive entry with a fixed timestamp if SOURCE_DATE_EPOCH is set, and Unix permissions for the scripts."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    timestamp = int(epoch) if epoch else int(path.stat().st_mtime) if path else int(time.time())
    info = zipfile.ZipInfo(name, date_time=time.gmtime(max(timestamp, 315532800))[:6])  # zip dates start in 1980
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if Path(name).name in EXECUTABLES else 0o644
    info.external_attr = (0o100000 | mode) << 16  # regular file
    return info


def main() -> None:
    files = release_files()
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        sys.exit(f"Missing files: {', '.join(missing)}")

    version = project_version()
    prefix = f"GhostScribe-v{version}/"
    target = ROOT / "dist" / f"GhostScribe-v{version}.zip"
    target.parent.mkdir(exist_ok=True)

    with zipfile.ZipFile(target, "w") as archive:
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            if FORBIDDEN.search(name):
                archive.close()
                target.unlink()
                sys.exit(f"Aborted: '{name}' must not be part of the release.")
            archive.writestr(zip_entry(prefix + name, path), path.read_bytes())
        for directory in EMPTY_DIRS:
            archive.writestr(zip_entry(f"{prefix}{directory}/.gitkeep", None), b"")

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    checksum = target.with_name(target.name + ".sha256")
    checksum.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"{target.relative_to(ROOT)}: {len(files)} files, {target.stat().st_size // 1024} KB, SHA-256 {digest}")


if __name__ == "__main__":
    main()

"""
Builds the portable releases for Windows, macOS and Linux, each with its SHA-256 checksum:

- dist/GhostScribe-v<version>.zip: the private edition.
- dist/GhostScribe-Company-v<version>.zip: the company edition (see ghostscribe/edition.py). Its only difference is
  the file ghostscribe/EDITION, so both editions run exactly the tested code.

The archives contain only what end users need to run GhostScribe. Developer tooling
(tests, scripts, configs), secrets (.env) and personal data (recordings, meetings) are never packed.
With SOURCE_DATE_EPOCH set (the release workflow uses the time of the tagged commit), every build of the same
commit produces byte-identical archives.
Usage: python scripts/build_release.py [--edition private|company|all]
"""

import argparse
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
EDITIONS = {"private": "GhostScribe", "company": "GhostScribe-Company"}  # edition: name of its archive
EDITION_MARKER = f"{PACKAGE_DIR}/EDITION"  # only in the company archive; a local one (for testing) is never packed
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
    code_and_assets = [
        p for p in package_files if p.is_file() and "__pycache__" not in p.parts and p != ROOT / EDITION_MARKER
    ]
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


def build(edition: str, version: str, files: list[Path], dist: Path | None = None) -> Path:
    """Writes the archive of one edition and its checksum file; returns the archive."""
    name = f"{EDITIONS[edition]}-v{version}"
    prefix = f"{name}/"
    target = (dist or ROOT / "dist") / f"{name}.zip"
    target.parent.mkdir(exist_ok=True)

    with zipfile.ZipFile(target, "w") as archive:
        for path in files:
            entry = path.relative_to(ROOT).as_posix()
            if FORBIDDEN.search(entry):
                archive.close()
                target.unlink()
                sys.exit(f"Aborted: '{entry}' must not be part of the release.")
            archive.writestr(zip_entry(prefix + entry, path), path.read_bytes())
        if edition == "company":
            archive.writestr(zip_entry(prefix + EDITION_MARKER, None), b"company\n")
        for directory in EMPTY_DIRS:
            archive.writestr(zip_entry(f"{prefix}{directory}/.gitkeep", None), b"")

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    checksum = target.with_name(target.name + ".sha256")
    checksum.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"{target.name}: {len(files)} files, {target.stat().st_size // 1024} KB, SHA-256 {digest}")
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Builds the release archives of GhostScribe.")
    parser.add_argument("--edition", choices=[*EDITIONS, "all"], default="all", help="default: all editions")
    args = parser.parse_args(argv)

    files = release_files()
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        sys.exit(f"Missing files: {', '.join(missing)}")
    version = project_version()
    for edition in EDITIONS if args.edition == "all" else [args.edition]:
        build(edition, version, files)


if __name__ == "__main__":
    main()

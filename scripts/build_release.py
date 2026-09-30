"""
Builds the portable Windows release: dist/GhostScribe-v<version>-windows.zip

The archive contains only what end users need to run GhostScribe. Developer tooling
(tests, scripts, configs), secrets (.env) and personal data (recordings, meetings) are never packed.
Usage: python scripts/build_release.py
"""

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_FILES = [
    "start.bat",
    "install_requirements.bat",
    "requirements.txt",
    ".env.example",
    "README.md",
    "LICENSE",
]
PACKAGE_DIR = "ghostscribe"
EMPTY_DIRS = ["recordings", "meetings"]
# Last line of defense in case one of the lists above is ever extended carelessly
FORBIDDEN = re.compile(r"(^|/)\.env$|\.(wav|mp3|flac)$|^(recordings|meetings|models|voices)/|__pycache__|\.pyc$")


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


def main() -> None:
    files = release_files()
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        sys.exit(f"Missing files: {', '.join(missing)}")

    version = project_version()
    prefix = f"GhostScribe-v{version}/"
    target = ROOT / "dist" / f"GhostScribe-v{version}-windows.zip"
    target.parent.mkdir(exist_ok=True)

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            if FORBIDDEN.search(name):
                archive.close()
                target.unlink()
                sys.exit(f"Aborted: '{name}' must not be part of the release.")
            archive.write(path, prefix + name)
        for directory in EMPTY_DIRS:
            archive.writestr(f"{prefix}{directory}/.gitkeep", "")

    print(f"{target.relative_to(ROOT)}: {len(files)} files, {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

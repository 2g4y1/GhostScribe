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
    "main.py",
    "app.py",
    "cli.py",
    "recorder.py",
    "analyzer.py",
    "utils.py",
    "requirements.txt",
    "start.bat",
    "install_requirements.bat",
    ".env.example",
    "README.md",
    "LICENSE",
]
RELEASE_DIRS = ["static"]
EMPTY_DIRS = ["recordings", "meetings"]
# Last line of defense in case one of the lists above is ever extended carelessly
FORBIDDEN = re.compile(r"(^|/)\.env$|\.(wav|mp3|flac)$|^(recordings|meetings)/")


def project_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)


def main() -> None:
    files = [ROOT / name for name in RELEASE_FILES]
    for directory in RELEASE_DIRS:
        files += sorted(path for path in (ROOT / directory).rglob("*") if path.is_file())
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        sys.exit(f"Fehlende Dateien: {', '.join(missing)}")

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
                sys.exit(f"Abbruch: '{name}' darf nicht ins Release.")
            archive.write(path, prefix + name)
        for directory in EMPTY_DIRS:
            archive.writestr(f"{prefix}{directory}/.gitkeep", "")

    print(f"{target.relative_to(ROOT)}: {len(files)} Dateien, {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

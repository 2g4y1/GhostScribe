"""
Checks that every package of a lock file has a prebuilt wheel for every supported platform and Python version, so
that the start scripts never have to compile a package (e.g. after an update that dropped Intel Macs).

Usage: python scripts/check_wheels.py requirements.txt [requirements-dev.txt ...]
Needs the "packaging" library (part of requirements-dev.txt) and access to pypi.org.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

from packaging.markers import Marker
from packaging.tags import compatible_tags, cpython_tags, mac_platforms
from packaging.utils import parse_wheel_filename

PYTHON_VERSIONS = (11, 12, 13, 14)


def manylinux(arch: str) -> list[str]:
    return [f"manylinux_2_{minor}_{arch}" for minor in range(35, 16, -1)] + [f"manylinux2014_{arch}", f"linux_{arch}"]


# Name: (sys.platform, platform.system(), platform.machine(), compatible platform tags)
PLATFORMS = {
    "Windows x64": ("win32", "Windows", "AMD64", ["win_amd64"]),
    "macOS Apple silicon": ("darwin", "Darwin", "arm64", list(mac_platforms((11, 0), "arm64"))),
    "macOS Intel": ("darwin", "Darwin", "x86_64", list(mac_platforms((11, 0), "x86_64"))),
    "Linux x64": ("linux", "Linux", "x86_64", manylinux("x86_64")),
    "Linux ARM64": ("linux", "Linux", "aarch64", manylinux("aarch64")),
}
REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)(?:\s*;\s*([^\\\n]+?))?\s*\\?$", re.MULTILINE)


def wheels(name: str, version: str) -> list[str]:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
        return [f["filename"] for f in json.load(response)["urls"] if f["filename"].endswith(".whl")]


def gaps(lock_file: Path) -> list[str]:
    pins = REQUIREMENT.findall(lock_file.read_text(encoding="utf-8"))
    files = {(name, version): wheels(name, version) for name, version, _ in pins}
    problems = []
    for platform_name, (sys_platform, system, machine, platform_tags) in PLATFORMS.items():
        for minor in PYTHON_VERSIONS:
            environment = {
                "sys_platform": sys_platform,
                "platform_system": system,
                "platform_machine": machine,
                "python_version": f"3.{minor}",
                "python_full_version": f"3.{minor}.0",
                "platform_python_implementation": "CPython",
                "implementation_name": "cpython",
                "os_name": "nt" if sys_platform == "win32" else "posix",
            }
            supported = set(cpython_tags((3, minor), platforms=platform_tags))
            supported |= set(compatible_tags((3, minor), f"cp3{minor}", platforms=platform_tags))
            for name, version, marker in pins:
                if marker and not Marker(marker).evaluate(environment):
                    continue
                if not any(set(parse_wheel_filename(f)[3]) & supported for f in files[name, version]):
                    problems.append(f"{lock_file}: no wheel of {name}=={version} for {platform_name}, Python 3.{minor}")
    print(f"{lock_file}: {len(pins)} packages, {len(PLATFORMS) * len(PYTHON_VERSIONS)} platform/Python combinations")
    return problems


def main() -> None:
    problems = [problem for path in sys.argv[1:] for problem in gaps(Path(path))]
    for problem in problems:
        print(problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()

#!/bin/sh
# GhostScribe setup for Linux and macOS: creates .venv and installs the Python dependencies.
# Runs from start.sh or on its own: sh install_requirements.sh
cd "$(dirname "$0")" || exit 1

fail() {
    echo
    echo "[ERROR] $1"
    exit 1
}

echo "============================================================"
echo "  GhostScribe - Setup"
echo "============================================================"
echo

# Look for Python 3.11+, the newest first
PYTHON_CMD=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c "import sys; sys.exit(sys.version_info < (3, 11))" >/dev/null 2>&1; then
        PYTHON_CMD="$candidate"
        break
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python 3.11 or newer was not found."
    echo
    echo "  macOS:          brew install python@3.13  (or https://www.python.org/downloads/)"
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv"
    echo "  Fedora:         sudo dnf install python3"
    exit 1
fi
echo "[1/3] Found $("$PYTHON_CMD" --version 2>&1)."

if [ ! -x .venv/bin/python ]; then
    echo "[2/3] Creating the virtual environment .venv ..."
    "$PYTHON_CMD" -m venv .venv ||
        fail "Could not create .venv. On Debian/Ubuntu install the venv module: sudo apt install python3-venv"
fi

echo "[3/3] Installing the libraries, the first time takes 1-2 minutes ..."
.venv/bin/python -m pip install --upgrade pip --quiet --disable-pip-version-check ||
    fail "Setup failed. Please check the internet connection and run this script again."
# Every package is pinned with its checksum: a changed or tampered download is rejected
.venv/bin/python -m pip install --require-hashes -r requirements.txt --disable-pip-version-check ||
    fail "Setup failed. Please check the internet connection and run this script again."
cp requirements.txt .venv/installed-requirements.txt
[ -f .env ] || cp .env.example .env

echo
echo "Setup complete. Start GhostScribe with: sh start.sh"

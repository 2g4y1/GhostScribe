#!/bin/sh
# Starts GhostScribe on Linux and macOS: sh start.sh (the setup runs first when needed)
cd "$(dirname "$0")" || exit 1
[ -t 1 ] && printf '\033]0;GhostScribe\007' # window title
export PYTHONUTF8=1

# Run the setup on the first start and whenever requirements.txt has changed
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
    sh ./install_requirements.sh || {
        echo
        echo "GhostScribe could not be set up."
        exit 1
    }
fi

exec .venv/bin/python -m ghostscribe "$@"

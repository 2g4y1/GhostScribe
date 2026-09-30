# Contributing to GhostScribe

Thank you for improving GhostScribe! Bug reports, translations and pull requests are welcome.

## Setting up

GhostScribe runs on Windows, macOS and Linux with Python 3.11 to 3.14.

```
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt   # Windows: .venv\Scripts\python ...
.venv/bin/python -m pip install -e . --no-deps               # optional: makes "ghostscribe" importable from anywhere
npm ci                                                        # optional: ESLint for the web interface (Node.js 22.13+)
pip install pre-commit && pre-commit install                  # optional: the formatting checks before every commit
```

Start the app with `python -m ghostscribe` (web interface) or `python -m ghostscribe --cli` (terminal version).

## Checks

The CI runs these checks on every pull request; please run them before you push:

```
ruff check . && ruff format --check .
mypy --platform linux && mypy --platform win32 && mypy --platform darwin
pytest                      # with --cov for the coverage report
npm run lint                # ESLint for ghostscribe/static/*.js
shellcheck -s sh start.sh start.command install_requirements.sh
```

The tests run on every operating system: the audio devices, Gemini and the voice recognition models are replaced by
test doubles (`tests/fakes.py`, `tests/test_audio.py`, `tests/test_analysis.py`), so no microphone, network access
or API key is needed.

## Dependencies

`pyproject.toml` lists the direct dependencies with their lowest supported versions (and the development tools as the
extra `dev`). The start scripts and the CI install from lock files that pin every package, including indirect ones,
with its SHA-256 checksums for all supported platforms. After changing a dependency, regenerate both lock files with
[uv](https://docs.astral.sh/uv/) 0.8.17 (the commands are also in the first lines of the files):

```
uv pip compile pyproject.toml --universal --python-version=3.11 --generate-hashes --output-file=requirements.txt
uv pip compile pyproject.toml --extra=dev --constraints=requirements.txt --universal --python-version=3.11 --generate-hashes --output-file=requirements-dev.txt
```

uv keeps the pinned versions of the existing files; add `--upgrade-package <name>` (or `--upgrade`) to update.
The development lock file takes the versions of `requirements.txt`, so the tests run exactly what users install.
The CI checks that both files match `pyproject.toml` and that every locked package has a prebuilt wheel for every
supported platform and Python version (`scripts/check_wheels.py`), so that nobody needs a compiler to install.

[Renovate](https://docs.renovatebot.com/) proposes updates of the Python packages, GitHub Actions and ESLint once a
month (`renovate.json`); it regenerates the lock files with the same uv version as the CI (`constraints.uv`), so update
both together.

The web interface uses no build step. Its two libraries are unmodified release files in
`ghostscribe/static/vendor/`; see the README there for updating them.

## Translations

Each language is one JSON file in `ghostscribe/static/locales/` (see "Adding a language" in the README). The tests
check that every language has the same keys and placeholders as English, and that every key is used.

## Pull requests

- Keep a pull request to one topic and describe what it changes and why.
- Add or adjust tests for changed behavior.
- Add a line to the "Unreleased" section of [CHANGELOG.md](CHANGELOG.md) for changes users notice.
- Never commit `.env`, recordings, minutes, voice profiles or other personal data; `.gitignore` excludes them.

## Releasing

1. Set the new version in `ghostscribe/__init__.py` and move the "Unreleased" entries of the changelog to it.
2. Tag the commit on `main` with `v<version>` and push the tag.
3. The release workflow builds `GhostScribe-v<version>.zip` (private edition) and `GhostScribe-Company-v<version>.zip`
   (company edition, which only adds the file `ghostscribe/EDITION`), byte-identical for the same commit, with their
   SHA-256 checksums and a signed build provenance, and creates a draft release. Check the draft and publish it.
   `python scripts/build_release.py` builds both locally. To try the company edition from source, put the word
   `company` into `ghostscribe/EDITION`; the file is ignored by git and never packed into the private archive.

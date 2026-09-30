"""
Shared fixtures. The app keeps recordings/, meetings/ and .env in the working directory and reads .env when it is
imported, so the tests switch to an isolated temporary directory with a dummy .env before any test module (and with
it the app) is imported.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    path = Path(tempfile.mkdtemp(prefix="ghostscribe-tests-"))
    (path / "meetings").mkdir()
    (path / ".env").write_text("GEMINI_API_KEY=dummy-key-for-tests\nGEMINI_MODEL=test-model\n", encoding="utf-8")
    config.stash[WORKDIR] = path
    os.chdir(path)


def pytest_unconfigure(config):
    path = config.stash.get(WORKDIR, None)
    if path is not None:
        os.chdir(config.invocation_params.dir)
        shutil.rmtree(path, ignore_errors=True)


WORKDIR = pytest.StashKey[Path]()


@pytest.fixture(scope="session")
def workdir(pytestconfig):
    return pytestconfig.stash[WORKDIR]


@pytest.fixture(scope="session")
def client(workdir):
    from fastapi.testclient import TestClient

    from ghostscribe import app

    return TestClient(app.app, base_url="http://127.0.0.1:8765")


@pytest.fixture
def write_file(workdir):
    """Creates a file (with parent directories) relative to the working directory."""

    def write(relative_path, data=b"x" * 20000):
        path = workdir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    return write


@pytest.fixture
def company(tmp_path, monkeypatch):
    """The company edition, with the marker its release archive installs."""
    from ghostscribe import edition

    marker = tmp_path / "EDITION"
    marker.write_text("company\n", encoding="utf-8")
    monkeypatch.setattr(edition, "EDITION_FILE", marker)

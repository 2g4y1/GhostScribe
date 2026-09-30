"""
Shared fixtures. The app keeps recordings/, meetings/ and .env in the working directory,
so the API tests run in an isolated temporary directory with a dummy .env.
"""

import os

import pytest


@pytest.fixture(scope="session")
def workdir(tmp_path_factory):
    path = tmp_path_factory.mktemp("ghostscribe")
    (path / "meetings").mkdir()
    (path / ".env").write_text("GEMINI_API_KEY=dummy-key-for-tests\nGEMINI_MODEL=test-model\n", encoding="utf-8")
    previous = os.getcwd()
    os.chdir(path)
    yield path
    os.chdir(previous)


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

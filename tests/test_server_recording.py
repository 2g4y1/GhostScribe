"""The recording endpoints with fake audio devices: start, stop, discard and recovery after an interruption."""

import threading
import time

import numpy as np
import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from ghostscribe import app as server
from ghostscribe.recorder import MeetingRecorder

from fakes import FakeBackend

SECOND = np.zeros(48000, dtype=np.int16).tobytes()


@pytest.fixture
def devices(workdir, monkeypatch):
    """The server records from fake devices; its state and the recordings folder are restored after each test."""
    for key in ("status", "pending_recording", "last_error", "process_step"):
        monkeypatch.setitem(server.app_state, key, server.app_state[key])
    backend = FakeBackend()
    monkeypatch.setattr(server.recorder, "_backend", backend)
    recordings = workdir / "recordings"
    recordings.mkdir(exist_ok=True)
    before = set(recordings.iterdir())
    yield backend
    server.recorder.cancel()
    for path in set(recordings.iterdir()) - before:
        if path.is_file():
            path.unlink()


def test_a_recording_keeps_its_input_from_the_start(client, devices, workdir):
    response = client.post("/api/record/start", json={"title": "Retro", "mic_device": "1", "loopback_device": 2})

    assert response.status_code == 200
    base = server.recorder.base_name
    assert (workdir / f"recordings/{base}.context.json").exists()  # a recovered recording keeps its title
    assert client.post("/api/record/start", json={}).status_code == 409  # busy
    assert client.get("/api/status").json()["mic_device"] == "Headset"

    assert client.post("/api/record/cancel").status_code == 200
    assert not list(workdir.glob(f"recordings/{base}*"))


def test_unknown_devices_and_meeting_types_are_rejected(client, devices):
    assert client.post("/api/record/start", json={"meeting_type": "gossip"}).status_code == 422
    response = client.post("/api/record/start", json={"mic_device": "99"})
    assert response.status_code == 500 and server.app_state["status"] == "error"


def test_a_double_click_on_stop_saves_the_recording_once(client, devices, monkeypatch):
    assert client.post("/api/record/start", json={}).status_code == 200
    devices.on_mic(SECOND)
    saved = []
    monkeypatch.setattr(server.recorder, "save", lambda compress=True: saved.append(1) or "recordings/x.mp3")
    slow_stop = devices.stop

    def stop():
        time.sleep(0.2)  # releasing the devices takes a moment: the second click arrives meanwhile
        slow_stop()

    monkeypatch.setattr(devices, "stop", stop)
    results = []

    def click():
        tasks = BackgroundTasks()
        try:
            server.stop_recording(tasks)
            results.append(200)
            for task in tasks.tasks:
                task.func(*task.args, **task.kwargs)
        except HTTPException as e:
            results.append(e.status_code)

    clicks = [threading.Thread(target=click) for _ in range(2)]
    for thread in clicks:
        thread.start()
    for thread in clicks:
        thread.join()

    assert sorted(results) == [200, 409]
    assert saved == [1]


def test_interrupted_recordings_are_recovered_when_the_server_starts(devices, workdir):
    crashed = MeetingRecorder(output_dir=str(workdir / "recordings"), backend=FakeBackend())
    base = crashed.start()
    crashed.backend.on_mic(SECOND)
    crashed.backend.on_system(SECOND * 2)
    crashed._release()  # the console window was closed while recording

    with TestClient(server.app, base_url="http://127.0.0.1:8765") as client:  # runs the startup
        for _ in range(100):
            status = client.get("/api/status").json()
            if status["status"] == "idle":
                break
            time.sleep(0.05)
        assert status["pending_recording"].startswith(base)
        listed = [r["filename"] for r in client.get("/api/unprocessed-recordings").json()]
        assert any(name.startswith(base) for name in listed)
        assert client.delete(f"/api/recordings/{base}.wav").status_code == 200
    assert not list(workdir.glob(f"recordings/{base}*"))

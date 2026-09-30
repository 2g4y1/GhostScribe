import base64
import json

import pytest

from ghostscribe import app as server


@pytest.fixture
def idle_server(monkeypatch):
    """Server state is restored after each test; the Gemini analysis is recorded instead of started."""
    for key in ("status", "pending_recording", "last_error"):
        monkeypatch.setitem(server.app_state, key, server.app_state[key])
    started = []
    monkeypatch.setattr(server, "run_gemini_analysis", lambda path, context: started.append((path, context)))
    return started


def test_stopping_saves_the_recording_and_waits_for_the_analysis(client, workdir, monkeypatch, idle_server):
    audio = workdir / "recordings" / "meeting_2026-01-01_10-00-00.mp3"

    def save(compress=True):
        audio.parent.mkdir(exist_ok=True)
        audio.write_bytes(b"x" * 20000)
        return str(audio)

    monkeypatch.setattr(server.recorder, "stop_capture", lambda: None)
    monkeypatch.setattr(server.recorder, "save", save)
    monkeypatch.setattr(server.recorder, "start_time", 0.0)
    monkeypatch.setattr(server.recorder, "end_time", 75.0)
    server.app_state["status"] = "recording"

    assert client.post("/api/record/stop").status_code == 200

    status = client.get("/api/status").json()
    assert (status["status"], status["pending_recording"]) == ("idle", audio.name)
    context = json.loads(audio.with_name(audio.stem + ".context.json").read_text(encoding="utf-8"))
    assert context["duration"] == "00:01:15"
    assert idle_server == []  # the analysis waits until chat history and slides could be added
    assert client.delete(f"/api/recordings/{audio.name}").status_code == 200
    assert client.get("/api/status").json()["pending_recording"] is None


def test_analysis_uses_the_input_added_after_the_recording(client, workdir, write_file, idle_server):
    write_file("recordings/meeting_c.mp3", "x" * 20000)
    write_file(
        "recordings/meeting_c.context.json", json.dumps({"title": "Alt", "participants": "Anna", "ai_act_mode": False})
    )
    png = "data:image/png;base64," + base64.b64encode(b"slide").decode()
    body = {"title": "Neu", "chat_text": "Link: https://example.org", "images": [{"filename": "a.png", "data": png}]}

    assert client.post("/api/recordings/meeting_c.mp3/analyze", json=body).status_code == 200

    [(path, context)] = idle_server
    assert (context["title"], context["participants"], context["chat_text"]) == ("Neu", "Anna", body["chat_text"])
    assert context["ai_act_mode"] is False  # the mode chosen for the recording is kept
    assert len(context["image_paths"]) == 1
    saved = json.loads((workdir / "recordings/meeting_c.context.json").read_text(encoding="utf-8"))
    assert saved == context  # kept for a retry until the minutes exist
    server.app_state["status"] = "idle"
    assert client.delete("/api/recordings/meeting_c.mp3").status_code == 200


def test_later_keeps_chat_and_slides_for_the_next_analysis(client, write_file, idle_server):
    write_file("recordings/meeting_l.mp3", "x" * 20000)

    assert client.put("/api/recordings/meeting_l.mp3/context", json={"chat_text": "Notiz"}).status_code == 200

    listed = {r["filename"]: r for r in client.get("/api/unprocessed-recordings").json()}
    assert listed["meeting_l.mp3"]["chat_text"] == "Notiz"
    assert idle_server == []
    assert client.delete("/api/recordings/meeting_l.mp3").status_code == 200

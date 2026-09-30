import json
import os

import pytest


def test_requests_from_foreign_websites_are_rejected(client):
    assert client.post("/api/record/cancel", headers={"Origin": "https://evil.example"}).status_code == 403


def test_requests_via_foreign_host_names_are_rejected(client):
    assert client.get("/api/status", headers={"Host": "evil.example:8765"}).status_code == 403


def test_requests_from_the_local_ui_are_allowed(client):
    response = client.get("/api/status", headers={"Origin": "http://localhost:8765"})

    assert response.status_code == 200
    assert response.json()["status"] == "idle"


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", "/recordings/..%5C.env"),
        ("get", "/api/meetings/..%5Cfoo"),
        ("delete", "/api/meetings/..%5Cfoo"),
        ("delete", "/api/recordings/..%5Cfoo.mp3"),
        ("post", "/api/recordings/..%5C.env/analyze"),
    ],
)
def test_path_traversal_is_rejected(client, method, url):
    assert getattr(client, method)(url).status_code == 400


def test_delete_meeting_removes_every_file_of_the_meeting(client, workdir, write_file):
    files = [
        write_file("recordings/meeting_x.mp3"),
        write_file("recordings/meeting_x.wav"),
        write_file("recordings/attachments/shot.png"),
        write_file("meetings/meeting_x.md", "# Protokoll"),
        write_file(
            "meetings/meeting_x.json",
            json.dumps({"audio_file": "recordings\\meeting_x.mp3", "attachments": ["recordings/attachments/shot.png"]}),
        ),
    ]

    assert client.delete("/api/meetings/meeting_x").status_code == 200
    assert not [path for path in files if path.exists()]


def test_unprocessed_recordings_are_listed_once_and_can_be_deleted(client, workdir, write_file):
    write_file("recordings/meeting_a.mp3")
    write_file("recordings/meeting_a.wav")
    write_file("recordings/attachments/a.png")
    write_file(
        "recordings/meeting_a.context.json",
        json.dumps({"title": "Retro", "image_paths": ["recordings/attachments/a.png"]}),
    )
    # A protocol may reference its audio under a different base name (e.g. demo data)
    write_file("recordings/meeting_demo.mp3")
    write_file("meetings/meeting_demo_review.json", json.dumps({"audio_file": "recordings/meeting_demo.mp3"}))

    listed = client.get("/api/unprocessed-recordings").json()

    assert [(r["filename"], r["title"]) for r in listed] == [("meeting_a.mp3", "Retro")]
    assert client.delete("/api/recordings/meeting_a.mp3").status_code == 200
    assert not list(workdir.glob("recordings/meeting_a*")) and not (workdir / "recordings/attachments/a.png").exists()
    assert client.delete("/api/recordings/meeting_demo.mp3").status_code == 409  # has a protocol


def test_analyzing_a_missing_recording_returns_404(client):
    assert client.post("/api/recordings/missing.mp3/analyze").status_code == 404


def test_settings_are_persisted_and_line_breaks_rejected(client, workdir, monkeypatch):
    for key in ("GEMINI_MODEL", "AI_ACT_MODE"):
        monkeypatch.setenv(key, os.environ.get(key, ""))  # restored after the test
    env_before = (workdir / ".env").read_text(encoding="utf-8")

    assert client.post("/api/settings", json={"model": "evil\nINJECTED=1"}).status_code == 400
    assert (workdir / ".env").read_text(encoding="utf-8") == env_before

    assert client.post("/api/settings", json={"model": "m1", "default_ai_act_mode": False}).status_code == 200
    env = (workdir / ".env").read_text(encoding="utf-8")
    assert "GEMINI_MODEL=m1" in env and "AI_ACT_MODE=false" in env
    assert client.get("/api/status").json()["default_ai_act_mode"] is False

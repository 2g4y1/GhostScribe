"""The private and the company edition: which one is installed, and what the company edition does differently."""

import json
from datetime import datetime, timedelta

import pytest

from ghostscribe import app as server, cli, edition
from ghostscribe.i18n import translate
from ghostscribe.recorder import MeetingRecorder

from fakes import FakeBackend


@pytest.fixture
def marker(tmp_path, monkeypatch):
    path = tmp_path / "EDITION"
    monkeypatch.setattr(edition, "EDITION_FILE", path)
    return path


def test_a_source_checkout_is_the_private_edition(marker):
    assert (edition.edition(), edition.is_company()) == ("private", False)


@pytest.mark.parametrize(
    ("content", "expected"), [("company\n", "company"), ("private\n", "private"), ("", "company"), ("Firma", "company")]
)
def test_the_marker_names_the_edition_and_anything_unknown_counts_as_company(marker, content, expected):
    marker.write_text(content, encoding="utf-8")

    assert edition.edition() == expected


def test_the_company_edition_has_no_sentiment_mode(client, company, monkeypatch):
    monkeypatch.setenv("AI_ACT_MODE", "false")  # a .env from a private installation changes nothing

    status = client.get("/api/status").json()
    assert (status["edition"], status["default_ai_act_mode"]) == ("company", True)
    rejected = client.post("/api/settings", json={"default_ai_act_mode": False})
    assert rejected.status_code == 400 and "Art. 5" in rejected.json()["detail"]
    assert client.post("/api/record/start", json={"ai_act_mode": False, "consent": True}).status_code == 400
    assert client.post("/api/recordings/missing.mp3/analyze", json={"ai_act_mode": False}).status_code == 400


def test_the_company_edition_records_only_with_everyones_consent(client, company, monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(server.recorder, "_backend", backend)
    for key in ("status", "pending_recording", "last_error", "process_step"):
        monkeypatch.setitem(server.app_state, key, server.app_state[key])

    refused = client.post("/api/record/start", json={})
    assert refused.status_code == 400 and refused.json()["detail"] == translate("api.recording_consent_required")
    assert not server.recorder.is_recording

    assert client.post("/api/record/start", json={"consent": True}).status_code == 200
    assert client.post("/api/record/cancel").status_code == 200


def test_the_private_edition_leaves_it_to_the_user(client, monkeypatch):
    monkeypatch.setattr(server.recorder, "_backend", FakeBackend())
    for key in ("status", "pending_recording", "last_error", "process_step"):
        monkeypatch.setitem(server.app_state, key, server.app_state[key])

    assert client.get("/api/status").json()["edition"] == "private"
    assert client.post("/api/record/start", json={}).status_code == 200  # no confirmation needed
    assert client.post("/api/record/cancel").status_code == 200


def test_the_company_terminal_version_asks_for_everyones_consent(tmp_path, company, monkeypatch, capsys):
    recorder = MeetingRecorder(output_dir=str(tmp_path), backend=FakeBackend())
    monkeypatch.setattr(cli, "MeetingRecorder", lambda: recorder)
    answers = iter(["Retro", "n"])  # topic, consent
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    cli.main()

    assert recorder.base_name is None  # nothing was recorded
    assert translate("cli.no_consent") in capsys.readouterr().out


def meeting(write_file, base, days_ago, with_minutes=True):
    """A recording, analyzed `days_ago` days ago or not at all."""
    audio = write_file(f"recordings/{base}.mp3")
    if with_minutes:
        analyzed = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
        meta = {"title": base, "created_at": analyzed, "audio_file": f"recordings/{base}.mp3", "voices": []}
        write_file(f"meetings/{base}.json", json.dumps(meta))
        write_file(f"meetings/{base}.md", "# Protokoll")
    return audio


def test_audio_is_deleted_after_the_retention_period_but_the_minutes_stay(client, write_file, workdir, monkeypatch):
    monkeypatch.setenv("KEEP_AUDIO_DAYS", "30")
    old = meeting(write_file, "meeting_old", days_ago=45)
    recent = meeting(write_file, "meeting_recent", days_ago=5)
    waiting = meeting(write_file, "meeting_waiting", days_ago=90, with_minutes=False)  # not analyzed yet

    assert server.delete_expired_audio() == 1

    assert not old.exists() and recent.exists() and waiting.exists()
    assert (workdir / "meetings/meeting_old.md").exists()
    shown = client.get("/api/meetings/meeting_old").json()
    assert shown["audio_url"] is None and shown["metadata"]["audio_deleted"] is True
    assert client.get("/api/meetings/meeting_recent").json()["metadata"]["audio_deleted"] is False
    for base in ("meeting_old", "meeting_recent", "meeting_waiting"):
        client.delete(f"/api/meetings/{base}")
        client.delete(f"/api/recordings/{base}.mp3")


@pytest.mark.parametrize(("setting", "private", "company"), [(None, 0, 30), ("0", 0, 0), ("7", 7, 7), ("x", 0, 30)])
def test_the_retention_period_defaults_to_30_days_in_the_company_edition(
    monkeypatch, tmp_path, setting, private, company
):
    if setting is None:
        monkeypatch.delenv("KEEP_AUDIO_DAYS", raising=False)
    else:
        monkeypatch.setenv("KEEP_AUDIO_DAYS", setting)
    marker = tmp_path / "EDITION"
    monkeypatch.setattr(edition, "EDITION_FILE", marker)
    assert server.keep_audio_days() == private
    marker.write_text("company", encoding="utf-8")
    assert server.keep_audio_days() == company


def test_the_retention_period_is_a_setting(client, monkeypatch):
    monkeypatch.setenv("KEEP_AUDIO_DAYS", "")  # restored after the test
    assert client.post("/api/settings", json={"keep_audio_days": -1}).status_code == 422

    assert client.post("/api/settings", json={"keep_audio_days": 90}).status_code == 200
    assert client.get("/api/status").json()["keep_audio_days"] == 90

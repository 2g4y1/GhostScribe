import json

import pytest

from ghostscribe import utils
from ghostscribe.utils import file_name, format_duration, update_env_file, write_json_atomic


def test_format_duration():
    assert format_duration(0) == "00:00:00"
    assert format_duration(59.9) == "00:00:59"
    assert format_duration(3725) == "01:02:05"


def test_update_env_file_replaces_existing_and_appends_missing_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")  # restored after the test
    monkeypatch.setenv("GEMINI_MODEL", "")
    env = tmp_path / ".env"
    env.write_text("# comment\nGEMINI_API_KEY=\nOTHER=1", encoding="utf-8")

    update_env_file({"GEMINI_API_KEY": "abc", "GEMINI_MODEL": "m1"}, path=str(env))

    assert env.read_text(encoding="utf-8").splitlines() == [
        "# comment",
        "GEMINI_API_KEY=abc",
        "OTHER=1",
        "GEMINI_MODEL=m1",
    ]


def test_update_env_file_rejects_line_breaks(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GEMINI_MODEL=a\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line breaks"):
        update_env_file({"GEMINI_MODEL": "evil\nINJECTED=1"}, path=str(env))

    assert env.read_text(encoding="utf-8") == "GEMINI_MODEL=a\n"


def test_an_interrupted_write_keeps_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "meeting.json"
    write_json_atomic(target, {"title": "Alt"})

    def crash(*args):
        raise OSError("disk full")

    monkeypatch.setattr(utils.os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        write_json_atomic(target, {"title": "Neu"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"title": "Alt"}
    assert [p.name for p in tmp_path.iterdir()] == ["meeting.json"]  # no temporary file is left behind


@pytest.mark.parametrize(
    ("stored", "name"),
    [("recordings\\meeting_x.mp3", "meeting_x.mp3"), ("recordings/meeting_x.mp3", "meeting_x.mp3"), ("x.mp3", "x.mp3")],
)
def test_paths_written_on_any_system_give_their_file_name(stored, name):
    assert file_name(stored) == name

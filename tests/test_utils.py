import pytest

from ghostscribe.utils import format_duration, update_env_file


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

    with pytest.raises(ValueError):
        update_env_file({"GEMINI_MODEL": "evil\nINJECTED=1"}, path=str(env))

    assert env.read_text(encoding="utf-8") == "GEMINI_MODEL=a\n"

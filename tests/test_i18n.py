import json
import os
import re
from pathlib import Path

import pytest

from ghostscribe.i18n import LOCALES_DIR, available_languages

PACKAGE = Path(__file__).resolve().parent.parent / "ghostscribe"
SOURCES = [*PACKAGE.glob("*.py"), *(PACKAGE / "static").glob("*.js"), PACKAGE / "static" / "index.html"]
PLACEHOLDER = re.compile(r"\{(\w+)\}")
STRING_LITERAL = re.compile(r"""["']([a-z]+(?:\.[a-z0-9_]+)+)["']""")


def messages(language):
    return json.loads((LOCALES_DIR / f"{language}.json").read_text(encoding="utf-8"))


def keys_used_in_code():
    prefixes = {key.split(".")[0] for key in messages("en")}
    used = set()
    for path in SOURCES:
        used |= {m for m in STRING_LITERAL.findall(path.read_text(encoding="utf-8")) if m.split(".")[0] in prefixes}
    return used


def test_german_and_english_are_available():
    assert {"de", "en"} <= set(available_languages())


@pytest.mark.parametrize("language", sorted(available_languages()))
def test_every_language_has_the_same_keys_and_placeholders_as_english(language):
    reference, translated = messages("en"), messages(language)

    assert translated.keys() == reference.keys()
    for key, text in reference.items():
        assert set(PLACEHOLDER.findall(translated[key])) == set(PLACEHOLDER.findall(text)), key


def test_every_key_used_in_the_code_exists():
    keys = messages("en").keys()
    missing = {k for k in keys_used_in_code() if k not in keys and not {f"{k}_one", f"{k}_other"} <= keys}

    assert not missing


def test_every_translation_is_used():
    used = keys_used_in_code()
    unused = {k for k in messages("en") if k not in used and k.rsplit("_", 1)[0] not in used}

    assert not unused


def test_server_messages_follow_the_configured_language(client, monkeypatch):
    monkeypatch.setenv("UI_LANGUAGE", "en")
    assert client.delete("/api/recordings/missing.mp3").json()["detail"] == "Recording not found."

    monkeypatch.setenv("UI_LANGUAGE", "de")
    assert client.delete("/api/recordings/missing.mp3").json()["detail"] == "Aufnahme nicht gefunden."


def test_language_is_saved_without_touching_other_settings(client, workdir, monkeypatch):
    for key in ("UI_LANGUAGE", "GEMINI_MODEL"):
        monkeypatch.setenv(key, os.environ.get(key, ""))  # restored after the test
    monkeypatch.setenv("UI_LANGUAGE", "")
    model_line = next(line for line in (workdir / ".env").read_text(encoding="utf-8").splitlines() if "MODEL" in line)

    assert client.get("/api/languages").json()["current"] is None
    assert client.post("/api/settings", json={"ui_language": "xx"}).status_code == 400
    assert client.post("/api/settings", json={"ui_language": "de"}).status_code == 200

    env = (workdir / ".env").read_text(encoding="utf-8")
    assert client.get("/api/languages").json()["current"] == "de"
    assert "UI_LANGUAGE=de" in env and model_line in env

"""
Translations for the web interface, server messages and the terminal.

Each language is one JSON file in static/locales/ with flat keys and {placeholder} parameters.
The web interface loads the same files, so adding a file adds a language everywhere.
"""

import json
import os
from functools import cache
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "static" / "locales"
FALLBACK_LANGUAGE = "en"


class _KeepMissing(dict):
    """Leaves unknown {placeholders} visible instead of raising KeyError."""

    def __missing__(self, key):
        return "{" + key + "}"


@cache
def _messages(language: str) -> dict[str, str]:
    with open(LOCALES_DIR / f"{language}.json", encoding="utf-8") as f:
        return json.load(f)


@cache
def available_languages() -> dict[str, str]:
    """Language code -> native language name, e.g. {"de": "Deutsch", "en": "English"}."""
    return {path.stem: _messages(path.stem)["meta.name"] for path in sorted(LOCALES_DIR.glob("*.json"))}


def configured_language() -> str | None:
    """The language chosen in the settings (UI_LANGUAGE in .env), or None if none was chosen yet."""
    language = os.getenv("UI_LANGUAGE", "").strip().lower()
    return language if language in available_languages() else None


def translate(key: str, **params) -> str:
    """Text for key in the configured language; falls back to English and finally to the key itself."""
    for language in (configured_language() or FALLBACK_LANGUAGE, FALLBACK_LANGUAGE):
        text = _messages(language).get(key)
        if text is not None:
            return text.format_map(_KeepMissing(params))
    return key


class LocalizedError(Exception):
    """Error whose message is translated, so it can be shown to the user as is."""

    def __init__(self, key: str, **params):
        super().__init__(translate(key, **params))

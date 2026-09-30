"""The Gemini analysis with a fake client: what is sent, what is saved and that the uploads are always deleted."""

import json
import wave
from types import SimpleNamespace

import numpy as np
import pytest
from google.genai import types

from ghostscribe import analyzer
from ghostscribe.analyzer import MeetingAnalyzer
from ghostscribe.i18n import LocalizedError

MINUTES = "# 📝 Besprechungsprotokoll: Budget 2027\n\n## 🎯 Management Summary\nText"


class FakeFiles:
    def __init__(self, states=("ACTIVE",)):
        self.states = list(states)  # the audio file's state per request; images are active at once
        self.uploaded, self.deleted = [], []

    def _file(self, name, state="ACTIVE"):
        return SimpleNamespace(name=name, state=SimpleNamespace(name=state), error="broken")

    def upload(self, file):
        self.uploaded.append(str(file))
        state = self.states.pop(0) if len(self.uploaded) == 1 else "ACTIVE"
        return self._file(f"files/{len(self.uploaded)}", state)

    def get(self, name):
        return self._file(name, self.states.pop(0) if self.states else "ACTIVE")

    def delete(self, name):
        self.deleted.append(name)


class FakeModels:
    def __init__(self, *results):
        self.results = list(results)  # responses, or exceptions to raise
        self.requests = []

    def generate_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def response(text=MINUTES, finish_reason=types.FinishReason.STOP):
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason=finish_reason, content=None)])


@pytest.fixture
def audio(tmp_path):
    """A silent 3-second recording: MP3 for the upload, stereo WAV for the channel analysis."""
    wav = tmp_path / "meeting_2026-09-29_15-17-28.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(np.zeros((3 * 16000, 2), dtype=np.int16).tobytes())
    mp3 = wav.with_suffix(".mp3")
    mp3.write_bytes(b"mp3")
    return mp3


def analyze(tmp_path, audio, models, files=None, **kwargs):
    client = SimpleNamespace(files=files or FakeFiles(), models=models)
    steps = []
    meeting_analyzer = MeetingAnalyzer(
        api_key="key", model="configured-model", meetings_dir=str(tmp_path / "meetings"), client=client
    )
    result = meeting_analyzer.analyze_meeting(
        audio_filepath=str(audio), on_status_update=lambda key, **params: steps.append(key), **kwargs
    )
    return result, client, steps


def test_the_minutes_are_saved_with_their_metadata(tmp_path, audio):
    slide = tmp_path / "slide.png"
    slide.write_bytes(b"png")
    models = FakeModels(response())

    result, client, steps = analyze(
        tmp_path,
        audio,
        models,
        meeting_title="Budget",
        participants="Anna, Tom",
        user_name="Max",
        chat_text="  Link: https://example.org  ",
        image_filepaths=[str(slide), str(tmp_path / "missing.png")],
        ai_act_mode=False,
    )

    prompt = models.requests[0]["contents"][-1]
    assert "Titel: Budget" in prompt and "Dauer: 00:00:03" in prompt and "Datum: 29.09.2026, 15:17 Uhr" in prompt
    assert "Nutzer (Headset-Mikrofon): Max" in prompt and "Weitere Teilnehmer: Anna, Tom" in prompt
    assert "<zusatz_chatverlauf>\nLink: https://example.org\n</zusatz_chatverlauf>" in prompt
    assert "(1 Bild(er))" in prompt
    assert "Stimmung & Tonalität" in models.requests[0]["config"].system_instruction  # the sentiment mode
    assert client.files.uploaded == [str(audio), str(slide)]
    assert client.files.deleted == ["files/1", "files/2"]  # nothing stays at Google

    saved = json.loads((tmp_path / "meetings" / "meeting_2026-09-29_15-17-28.json").read_text(encoding="utf-8"))
    assert saved == result["metadata"]
    assert (saved["title"], saved["model_used"], saved["image_count"], saved["has_chat"]) == (
        "Budget",
        "configured-model",
        1,
        True,
    )
    assert saved["meeting_start"] == "2026-09-29T15:17:28" and saved["ai_act_mode"] is False
    assert (tmp_path / "meetings" / "meeting_2026-09-29_15-17-28.md").read_text(encoding="utf-8") == MINUTES
    assert steps[-1] == "step.remote_file_deleted"


def test_gemini_learns_where_the_recording_was_paused(tmp_path, audio):
    models = FakeModels(response(), response())

    analyze(tmp_path, audio, models, cuts=["00:12:30", "00:40:02"])
    analyze(tmp_path, audio, models)

    with_pauses, without = (request["contents"][-1] for request in models.requests)
    assert "Pausen: Die Aufnahme wurde bei [00:12:30], [00:40:02] pausiert" in with_pauses
    assert "Pausen:" not in without


def test_the_company_edition_analyzes_without_emotions_or_assessing_people(tmp_path, audio, company):
    models = FakeModels(response())

    result, _, _ = analyze(tmp_path, audio, models, meeting_type="interview", ai_act_mode=False)

    request = models.requests[0]
    assert "Stimmung & Tonalität" not in request["config"].system_instruction  # asked for, but not available
    assert "bewerte die befragte Person nicht" in request["contents"][-1]
    assert "Kandidatenprofil" not in request["contents"][-1]
    assert result["metadata"]["ai_act_mode"] is True
    minutes = (tmp_path / "meetings" / "meeting_2026-09-29_15-17-28.md").read_text(encoding="utf-8")
    assert minutes.startswith(MINUTES.rstrip()) and minutes.endswith(
        "(configured-model). Vor der Weitergabe prüfen.*\n"
    )


def test_a_generic_title_is_replaced_by_the_topic_of_the_minutes(tmp_path, audio):
    result, _, steps = analyze(tmp_path, audio, FakeModels(response()), meeting_title="Teams Besprechung")

    assert result["metadata"]["title"] == "Budget 2027"
    assert "step.title_detected" in steps


def test_the_next_model_is_tried_when_one_fails(tmp_path, audio):
    models = FakeModels(RuntimeError("429 quota"), response())

    result, _, steps = analyze(tmp_path, audio, models)

    assert [r["model"] for r in models.requests] == ["configured-model", analyzer.DEFAULT_MODEL]
    assert result["metadata"]["model_used"] == analyzer.DEFAULT_MODEL
    assert "step.model_failed" in steps


def test_the_uploads_are_deleted_even_if_every_model_fails(tmp_path, audio):
    files = FakeFiles()
    models = FakeModels(*[RuntimeError("down")] * 4)

    with pytest.raises(LocalizedError):
        analyze(tmp_path, audio, models, files=files)

    assert len(models.requests) == 4  # the configured model and the three fallbacks
    assert files.deleted == ["files/1"]
    assert not (tmp_path / "meetings" / "meeting_2026-09-29_15-17-28.md").exists()


def test_minutes_cut_off_at_the_output_limit_are_marked(tmp_path, audio):
    result, _, steps = analyze(tmp_path, audio, FakeModels(response(finish_reason=types.FinishReason.MAX_TOKENS)))

    assert result["markdown_content"].endswith("abgeschnitten und ist unvollständig.")
    assert "step.output_truncated" in steps


def test_an_empty_answer_leaves_a_note(tmp_path, audio):
    result, _, _ = analyze(tmp_path, audio, FakeModels(response(text=None)))

    assert "Keine Zusammenfassung generiert" in result["markdown_content"]


def test_the_analysis_waits_while_google_processes_the_audio(tmp_path, audio, monkeypatch):
    monkeypatch.setattr(analyzer.time, "sleep", lambda seconds: None)
    files = FakeFiles(states=("PROCESSING", "PROCESSING", "ACTIVE"))

    _, _, steps = analyze(tmp_path, audio, FakeModels(response()), files=files)

    assert steps.count("step.gemini_processing") == 2


def test_audio_that_google_cannot_process_is_reported(tmp_path, audio):
    files = FakeFiles(states=("FAILED",))

    with pytest.raises(LocalizedError):
        analyze(tmp_path, audio, FakeModels(response()), files=files)

    assert files.deleted == ["files/1"]


def test_processing_that_does_not_finish_gives_up(tmp_path, audio, monkeypatch):
    monkeypatch.setattr(analyzer, "PROCESSING_TIMEOUT", 0)
    monkeypatch.setattr(analyzer.time, "sleep", lambda seconds: None)
    files = FakeFiles(states=["PROCESSING"] * 10)

    with pytest.raises(LocalizedError, match="0 minutes"):
        analyze(tmp_path, audio, FakeModels(response()), files=files)

    assert files.deleted == ["files/1"]

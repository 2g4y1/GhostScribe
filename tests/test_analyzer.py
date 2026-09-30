import wave
from datetime import datetime

import numpy as np

from ghostscribe.analyzer import (
    extract_channel_activity_summary,
    extract_title_from_markdown,
    get_system_instruction,
    recording_start,
)


def section_numbers(prompt):
    return [line.split(".")[0] for line in prompt.splitlines() if line[:2] == "# " and line[2:3].isdigit()]


def test_system_prompts_are_numbered_per_mode():
    ai_act, sentiment = get_system_instruction(True), get_system_instruction(False)

    assert section_numbers(ai_act) == [f"# {i}" for i in range(1, 7)]
    assert section_numbers(sentiment) == [f"# {i}" for i in range(1, 8)]
    assert "EU AI Act Konformität" in ai_act and "Stimmung & Tonalität" not in ai_act
    assert "Stimmung & Tonalität" in sentiment and "EU AI Act Konformität" not in sentiment


def test_extract_title_from_markdown():
    assert extract_title_from_markdown("# 📝 Besprechungsprotokoll: Sprint Review\n- **Datum:** …") == "Sprint Review"
    assert extract_title_from_markdown("", fallback="Fallback") == "Fallback"


def test_recording_start_is_read_from_the_file_name(tmp_path):
    path = tmp_path / "meeting_2026-09-29_15-17-28.mp3"
    path.write_bytes(b"")

    assert recording_start(str(path)) == datetime(2026, 9, 29, 15, 17, 28)


def test_channel_timeline_marks_microphone_and_system_audio(tmp_path):
    sample_rate = 16000
    stereo = np.zeros((sample_rate * 6, 2), dtype=np.int16)
    stereo[: sample_rate * 3, 0] = 5000  # 0-3 s: local microphone
    stereo[sample_rate * 3 :, 1] = 5000  # 3-6 s: system audio
    wav_path = tmp_path / "meeting_2026-01-01_10-00-00.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(stereo.tobytes())

    summary = extract_channel_activity_summary(str(wav_path.with_suffix(".mp3")))  # uses the WAV next to the MP3

    assert "[00:00:00–00:00:03] M" in summary
    assert "[00:00:03–00:00:06] S" in summary
    assert "Mikrofon (Nutzer) 50 %" in summary

import wave
from datetime import datetime

import numpy as np
import pytest

from ghostscribe.analyzer import (
    extract_channel_activity_summary,
    extract_title_from_markdown,
    get_system_instruction,
    recording_start,
    retitle_markdown,
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


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        ("# 📝 Besprechungsprotokoll: Alt\n\nText", "# 📝 Besprechungsprotokoll: Neu\n\nText"),
        ("# Alt\nText", "# Neu\nText"),
        ("## Zusammenfassung\nText", "## Zusammenfassung\nText"),  # no title heading: nothing changes
    ],
)
def test_retitle_markdown_keeps_the_prefix_of_the_heading(markdown, expected):
    assert retitle_markdown(markdown, "Neu") == expected


def test_recording_start_is_read_from_the_file_name(tmp_path):
    path = tmp_path / "meeting_2026-09-29_15-17-28.mp3"
    path.write_bytes(b"")

    assert recording_start(str(path)) == datetime(2026, 9, 29, 15, 17, 28)


def channel_timeline(tmp_path, *parts):
    """Summary of a stereo recording made of (seconds, microphone level, system audio level) parts."""
    sample_rate = 16000
    stereo = np.concatenate(
        [np.tile(np.int16([mic, system]), (int(seconds * sample_rate), 1)) for seconds, mic, system in parts]
    )
    wav_path = tmp_path / "meeting_2026-01-01_10-00-00.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(stereo.tobytes())
    return extract_channel_activity_summary(str(wav_path.with_suffix(".mp3")))  # uses the WAV next to the MP3


def test_channel_timeline_marks_microphone_and_system_audio(tmp_path):
    summary = channel_timeline(tmp_path, (3, 5000, 0), (3, 0, 5000))

    assert "[00:00:00–00:00:03] M" in summary
    assert "[00:00:03–00:00:06] S" in summary
    assert "Mikrofon (Nutzer) 50 %" in summary


def test_channel_timeline_hears_a_quiet_microphone_while_others_talk(tmp_path):
    # the microphone 20 dB below the system audio, the user starts while a colleague still murmurs
    summary = channel_timeline(tmp_path, (10, 0, 6000), (4, 300, 1500), (4, 300, 0), (2, 0, 0))

    assert "[00:00:00–00:00:10] S" in summary
    assert "[00:00:10–00:00:18] M" in summary
    assert "stumm" not in summary


def test_channel_timeline_does_not_take_system_audio_in_the_microphone_for_the_user(tmp_path):
    # speakers instead of a headset: the microphone picks up the others 20 dB quieter, as loud as the user
    summary = channel_timeline(tmp_path, (10, 2000, 20000), (4, 3000, 0))

    assert "[00:00:00–00:00:10] S" in summary
    assert "[00:00:10–00:00:14] M" in summary
    assert "] B" not in summary

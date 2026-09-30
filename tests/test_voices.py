import json
import wave

import numpy as np
import pytest

from ghostscribe import voices

RATE = voices.SAMPLE_RATE


class FakeEngine:
    """Voices are told apart by their loudness: level 0.1 -> (1, 0, 0), 0.5 -> (0, 1, 0), 0.9 -> (0, 0, 1)."""

    def __init__(self, clusters):
        self.clusters = clusters

    def diarize(self, samples):
        return self.clusters

    def embed(self, samples):
        level = float(np.mean(np.abs(samples)))
        return np.eye(3)[min(2, int(level * 3))]


def recording(path, levels):
    """Stereo WAV with a silent microphone channel; levels = [(seconds, level on the system-audio channel)]."""
    system = np.concatenate([np.full(int(seconds * RATE), level) for seconds, level in levels])
    frames = np.stack([np.zeros_like(system), system], axis=1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes((frames * 32767).astype(np.int16).tobytes())
    return str(path)


@pytest.fixture
def profiles_file(tmp_path, monkeypatch):
    path = tmp_path / "voices" / "profiles.json"
    monkeypatch.setattr(voices, "PROFILES_FILE", path)
    return path


def test_voices_are_recognized_by_profile_or_numbered_by_speaking_time(tmp_path):
    wav = recording(tmp_path / "meeting.wav", [(10, 0.1), (6, 0.5), (1, 0.9)])
    engine = FakeEngine([[(10.0, 13.0), (13.5, 16.0)], [(0.0, 10.0)], [(16.0, 17.0)]])
    sarah = {"id": "p1", "name": "Sarah", "model": voices.EMBEDDING_NAME, "embedding": [1.0, 0.0, 0.0]}

    result = voices.recognize_voices(wav, engine, profiles=[sarah])

    assert [(v["label"], v["profile_id"]) for v in result] == [("Sarah", "p1"), ("Stimme 1", None)]
    assert result[0]["similarity"] == pytest.approx(1.0)
    assert result[1]["intervals"] == [[10.0, 16.0]]  # a pause of 0.5 s does not split the turn
    assert len(result) == 2  # the 1-second voice is too short for a fingerprint


def test_each_profile_is_assigned_once_and_only_for_the_same_model():
    voice = {"seconds": 10.0, "intervals": [[0, 10]], "embedding": [1.0, 0.0]}
    close = {**voice, "seconds": 5.0, "embedding": [0.9, 0.1]}
    sarah = {"id": "p1", "name": "Sarah", "model": voices.EMBEDDING_NAME, "embedding": [1.0, 0.0]}
    other_model = {**sarah, "id": "p2", "name": "Tom", "model": "other.onnx"}

    labels = [v["label"] for v in voices.label_voices([dict(close), dict(voice)], [sarah, other_model])]

    assert labels == ["Sarah", "Stimme 1"]


def test_unclear_or_short_voices_are_not_recognized():
    sarah = {"id": "p1", "name": "Sarah", "model": voices.EMBEDDING_NAME, "embedding": [1.0, 0.0]}
    anna = {**sarah, "id": "p2", "name": "Anna", "embedding": [0.8, 0.6]}  # 0.8 similar to Sarah
    between = {"seconds": 30.0, "intervals": [[0, 30]], "embedding": [0.95, 0.31]}  # 0.95 Sarah, 0.95 Anna
    short = {"seconds": 6.0, "intervals": [[40, 46]], "embedding": [1.0, 0.0]}  # exactly Sarah, but only 6 s

    labels = [v["label"] for v in voices.label_voices([between, short], [sarah, anna])]

    assert labels == ["Stimme 1", "Stimme 2"]


def test_clusters_of_one_voice_are_merged():
    split = [
        {"seconds": 10.0, "intervals": [[0, 10]], "embedding": [1.0, 0.0, 0.0]},
        {"seconds": 5.0, "intervals": [[20, 25]], "embedding": [0.95, 0.05, 0.0]},
        {"seconds": 8.0, "intervals": [[10, 18]], "embedding": [0.0, 1.0, 0.0]},
    ]

    merged = voices.merge_similar_voices(split)

    assert [(v["seconds"], v["intervals"]) for v in merged] == [(15.0, [[0, 10], [20, 25]]), (8.0, [[10, 18]])]


def test_voice_context_names_every_voice_with_its_times():
    context = voices.voice_context(
        [
            {"label": "Sarah", "profile_id": "p1", "similarity": 0.84, "intervals": [[5.0, 70.0]]},
            {"label": "Stimme 1", "profile_id": None, "similarity": None, "intervals": [[0.0, 4.0], [80.0, 95.5]]},
        ]
    )

    assert "„Sarah“ (gespeichertes Stimmprofil, Übereinstimmung 84%): [00:00:05–00:01:10]" in context
    assert "„Stimme 1“ (unbekannte Stimme): [00:00:00–00:00:04], [00:01:20–00:01:35]" in context
    assert voices.voice_context([]) == ""


def test_profiles_with_the_same_name_are_merged_and_can_be_deleted(profiles_file):
    first = voices.save_profile("Tom", [1.0, 0.0, 0.0], 10)
    second = voices.save_profile("tom", [0.0, 1.0, 0.0], 30)

    saved = json.loads(profiles_file.read_text(encoding="utf-8"))
    assert first["id"] == second["id"] and len(saved) == 1
    assert (saved[0]["samples"], saved[0]["seconds"]) == (2, 40)
    assert saved[0]["embedding"][1] > saved[0]["embedding"][0]  # weighted by speaking time
    assert voices.delete_profile(first["id"]) and not voices.delete_profile(first["id"])


def test_rename_speaker_replaces_generated_labels_everywhere_but_names_only_as_speaker():
    minutes = "**Stimme 2:** Hallo\n- Stimme 2 fragt nach Stimme 20.\n**Sarah:** Danke, Sarah.\n- **Tom (Stimme 2)**"

    renamed = voices.rename_speaker(minutes, "Stimme 2", "Tom")
    assert renamed == "**Tom:** Hallo\n- Tom fragt nach Stimme 20.\n**Sarah:** Danke, Sarah.\n- **Tom**"
    assert "**Anna:** Danke, Sarah." in voices.rename_speaker(renamed, "Sarah", "Anna")


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("Anna-Lena O'Brien", True),
        ("Jürgen", True),
        ("", False),
        ("x" * 61, False),
        ("Stimme 3", False),
        ("<b>", False),
        ("a\nb", False),
    ],
)
def test_voice_names_are_validated(name, valid):
    assert voices.valid_name(name) is valid


def test_naming_a_voice_saves_the_profile_and_updates_the_minutes(client, write_file, profiles_file):
    write_file("meetings/meeting_v.md", "- **Stimme 1** – Kollege\n- [00:00:01] **Stimme 1:** Hallo")
    voice = {
        "label": "Stimme 1",
        "seconds": 12.0,
        "intervals": [[0, 12]],
        "embedding": [0.0, 1.0],
        "profile_id": None,
        "similarity": None,
    }
    write_file("meetings/meeting_v.json", json.dumps({"title": "V", "voices": [voice]}))
    url = "/api/meetings/meeting_v/voices"
    traversal = client.post(
        "/api/meetings/..%5Cmeeting_v/voices", json={"label": "Stimme 1", "name": "Tom", "consent": True}
    )
    assert traversal.status_code == 400

    assert client.post(url, json={"label": "Stimme 1", "name": "Tom"}).status_code == 400  # no consent
    assert client.post(url, json={"label": "Stimme 1", "name": "<Tom>", "consent": True}).status_code == 400
    assert client.post(url, json={"label": "Stimme 9", "name": "Tom", "consent": True}).status_code == 404
    assert client.post(url, json={"label": "Stimme 1", "name": "Tom", "consent": True}).status_code == 200

    meeting = client.get("/api/meetings/meeting_v").json()
    assert "**Tom:** Hallo" in meeting["markdown"] and "**Tom** – Kollege" in meeting["markdown"]
    assert meeting["metadata"]["voices"][0]["label"] == "Tom"
    assert "embedding" not in meeting["metadata"]["voices"][0]  # fingerprints never leave the server
    profiles = client.get("/api/voices").json()
    assert [p["name"] for p in profiles] == ["Tom"] and "embedding" not in profiles[0]
    assert client.delete(f"/api/voices/{profiles[0]['id']}").status_code == 200
    assert client.delete(f"/api/voices/{profiles[0]['id']}").status_code == 404


def test_voice_recognition_is_off_by_default_and_can_be_switched_on(client, monkeypatch):
    monkeypatch.delenv("VOICE_RECOGNITION", raising=False)
    assert client.get("/api/status").json()["voice_recognition"] is False

    assert client.post("/api/settings", json={"voice_recognition": True}).status_code == 200
    assert client.get("/api/status").json()["voice_recognition"] is True
    monkeypatch.delenv("VOICE_RECOGNITION")  # set by the request, removed again for the other tests


def test_long_recordings_are_cut_at_the_quietest_moment_near_each_boundary():
    samples = np.full(RATE * 60, 0.5, dtype=np.float32)
    samples[RATE * 32 : RATE * 33] = 0.0  # a pause two seconds after the middle

    bounds = voices.part_bounds(samples, 2)

    assert bounds[0] == 0 and bounds[-1] == len(samples)
    assert RATE * 32 <= bounds[1] <= RATE * 33


def test_recordings_are_split_into_parts_of_at_least_five_minutes():
    assert voices.part_count(299, workers=8) == 1
    assert voices.part_count(600, workers=8) == 2
    assert voices.part_count(76 * 60, workers=14) == 14
    assert voices.part_count(76 * 60, workers=4) == 4


def test_voice_workers_default_to_one_and_at_most_half_of_the_logical_processors(monkeypatch):
    monkeypatch.setattr(voices.os, "cpu_count", lambda: 16)
    monkeypatch.delenv("VOICE_WORKERS", raising=False)
    assert voices.configured_workers() == 1

    monkeypatch.setenv("VOICE_WORKERS", "6")
    assert voices.configured_workers() == 6
    monkeypatch.setenv("VOICE_WORKERS", "99")
    assert voices.configured_workers() == 8


def test_voice_workers_are_saved_within_the_limit(client, monkeypatch):
    monkeypatch.setattr(voices.os, "cpu_count", lambda: 8)

    assert client.post("/api/settings", json={"voice_workers": 5}).status_code == 400
    assert client.post("/api/settings", json={"voice_workers": 3}).status_code == 200
    status = client.get("/api/status").json()
    assert (status["voice_workers"], status["voice_workers_max"]) == (3, 4)
    monkeypatch.delenv("VOICE_WORKERS")  # set by the request, removed again for the other tests

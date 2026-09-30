"""
Local voice recognition for the system-audio channel (the other participants).

The voices are separated and fingerprinted on this PC with sherpa-onnx; the models are downloaded once into
models/. Voice profiles (name + fingerprint) are kept in voices/profiles.json and only saved when the user
confirms the consent of the person: voice fingerprints are biometric data.
"""

import hashlib
import json
import logging
import os
import re
import tarfile
import urllib.request
import uuid
import wave
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import numpy as np

from ghostscribe.i18n import LocalizedError
from ghostscribe.utils import format_duration

logger = logging.getLogger(__name__)

MODELS_DIR = Path("models")
PROFILES_FILE = Path("voices") / "profiles.json"
SAMPLE_RATE = 16000
UNKNOWN_LABEL = "Stimme {number}"  # the minutes are German
# Calibrated with TitaNet: in real Teams calls the same colleague reached 0.80-0.94 across meetings, different
# colleagues up to 0.55; one speaker across recordings six years apart (TV, stage) 0.75. Clusters of one person
# within a recording mostly reach >= 0.67.
MATCH_THRESHOLD = 0.65  # cosine similarity from which a saved profile counts as recognized ...
MATCH_MARGIN = 0.1  # ... with this lead over the second-best profile
MIN_MATCH_SECONDS = 10.0  # shorter voices give unreliable fingerprints: listed, but not recognized automatically
MERGE_THRESHOLD = 0.6  # clusters this similar are one voice that the diarization split up (reverb, applause)
MIN_VOICE_SECONDS = 5.0  # shorter voices are mostly applause, noise or cross-talk
FINGERPRINT_SECONDS = 90.0  # longest segments used for one fingerprint
MERGE_GAP = 1.5  # pauses up to this length do not split a speaking turn
# sherpa-onnx keeps Python's GIL while it computes, so long recordings are split into parts for separate processes
MIN_PART_SECONDS = 300.0  # parts are at least this long: shorter ones separate the voices less reliably
SPLIT_SEARCH_SECONDS = 15.0  # a part ends at the quietest moment this close to its nominal end
MIN_PART_VOICE_SECONDS = 2.0  # clusters of a part from this length are merged across the parts first

_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_ARCHIVE = (
    f"{_RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
)
SEGMENTATION_MODEL = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMBEDDING_MODEL = (
    f"{_RELEASES}/speaker-recongition-models/nemo_en_titanet_small.onnx",
    "ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e",
)
EMBEDDING_NAME = EMBEDDING_MODEL[0].rsplit("/", 1)[1]

_NAME = re.compile(r"^[\w .'’()-]{1,60}$")
_UNKNOWN = re.compile(r"^Stimme \d+$")


def recognition_enabled() -> bool:
    """Voice recognition is opt-in (VOICE_RECOGNITION=true in .env)."""
    return os.getenv("VOICE_RECOGNITION", "false").strip().lower() == "true"


def max_workers() -> int:
    """Most parallel processes for the voice recognition: half the logical processors (usually the physical
    cores). More share the cores and the cache: not faster, but the PC hardly responds any more."""
    return max(1, (os.cpu_count() or 2) // 2)


def default_workers() -> int:
    """A quarter of the logical processors: measured on 8 cores / 16 threads, 4 processes were 1.5 times as fast
    as one, 8 or 14 were not faster."""
    return max(1, (os.cpu_count() or 1) // 4)


def configured_workers() -> int:
    """VOICE_WORKERS from .env, limited to max_workers(); without a valid value default_workers()."""
    try:
        workers = int(os.getenv("VOICE_WORKERS", ""))
    except ValueError:
        return default_workers()
    return max(1, min(workers, max_workers()))


# ---------- models ----------
def _download(url: str, sha256: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    urllib.request.urlretrieve(url, partial)
    if hashlib.sha256(partial.read_bytes()).hexdigest() != sha256:
        partial.unlink()
        raise LocalizedError("error.voice_model_checksum", name=target.name)
    return partial.replace(target)


def ensure_models(report=lambda key, **params: None) -> None:
    """Downloads and verifies the two models on first use (about 45 MB)."""
    embedding = MODELS_DIR / EMBEDDING_NAME
    if SEGMENTATION_MODEL.exists() and embedding.exists():
        return
    report("step.voice_models_download")
    if not embedding.exists():
        _download(*EMBEDDING_MODEL, embedding)
    if not SEGMENTATION_MODEL.exists():
        archive = _download(*SEGMENTATION_ARCHIVE, MODELS_DIR / "segmentation.tar.bz2")
        with tarfile.open(archive) as tar:
            members = [m for m in tar.getmembers() if m.name.endswith(("/model.onnx", "/LICENSE"))]
            tar.extractall(MODELS_DIR, members=members, filter="data")
        archive.unlink()


class VoiceEngine:
    """sherpa-onnx speaker diarization plus fingerprint extraction for one part of a recording."""

    def __init__(self, threads: int = 4):
        import sherpa_onnx  # imported on first use only

        embedding = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(MODELS_DIR / EMBEDDING_NAME), num_threads=threads
        )
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(SEGMENTATION_MODEL)),
                num_threads=threads,
            ),
            embedding=embedding,
            clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not config.validate():
            raise LocalizedError("error.voice_models_invalid")
        self._diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(embedding)

    def diarize(self, samples: np.ndarray) -> list[list[tuple[float, float]]]:
        """Segments per voice: [[(start, end), ...], ...] in seconds."""
        voices = {}
        for segment in self._diarizer.process(samples).sort_by_start_time():
            voices.setdefault(segment.speaker, []).append((segment.start, segment.end))
        return list(voices.values())

    def embed(self, samples: np.ndarray) -> np.ndarray:
        stream = self._extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        stream.input_finished()
        return np.array(self._extractor.compute(stream))


# ---------- recognition ----------
def read_system_channel(wav_path: str, start: int = 0, end: int | None = None) -> np.ndarray:
    """Channel 1 (system audio) of a GhostScribe recording as float32 samples, optionally only [start, end)."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getnchannels() != 2 or wf.getsampwidth() != 2 or wf.getframerate() != SAMPLE_RATE:
            raise LocalizedError("error.voice_audio_format")
        wf.setpos(start)
        count = (wf.getnframes() if end is None else end) - start
        frames = np.frombuffer(wf.readframes(count), dtype=np.int16).reshape(-1, 2)
    return frames[:, 1].astype(np.float32) / 32768.0


def _normalize(vector) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64)
    return vector / (np.linalg.norm(vector) or 1.0)


def fingerprint(voice_engine, samples: np.ndarray, segments) -> np.ndarray:
    """Mean of the normalized fingerprints of the longest segments of one voice."""
    vectors, total = [], 0.0
    for start, end in sorted(segments, key=lambda s: s[0] - s[1]):
        if end - start < 1.5 or total >= FINGERPRINT_SECONDS:
            continue
        vectors.append(_normalize(voice_engine.embed(samples[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)])))
        total += end - start
    if not vectors:  # only short segments: use them all at once
        joined = np.concatenate([samples[int(s * SAMPLE_RATE) : int(e * SAMPLE_RATE)] for s, e in segments])
        vectors.append(_normalize(voice_engine.embed(joined)))
    return _normalize(np.mean(vectors, axis=0))


def merge_intervals(segments, gap: float = MERGE_GAP) -> list[list[float]]:
    merged = []
    for start, end in sorted(segments):
        if merged and start - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [[round(s, 1), round(e, 1)] for s, e in merged]


def _similarity(a, b) -> float:
    return float(_normalize(a) @ _normalize(b))


def _rounded(vector) -> list[float]:
    return [round(float(x), 5) for x in vector]


def merge_similar_voices(voices: list[dict], threshold: float = MERGE_THRESHOLD) -> list[dict]:
    """Merges clusters with similar fingerprints, most similar pair first (weighted by speaking time).
    Keeps a similarity matrix, so that the hundreds of clusters of a long recording in parts merge quickly."""
    voices = list(voices)
    if len(voices) < 2:
        return voices
    vectors = np.array([_normalize(voice["embedding"]) for voice in voices])
    alive = np.ones(len(voices), dtype=bool)
    similarity = vectors @ vectors.T
    np.fill_diagonal(similarity, -np.inf)
    while True:
        i, j = sorted(np.unravel_index(int(np.argmax(similarity)), similarity.shape))
        if similarity[i, j] < threshold:
            break
        a, b = voices[i], voices[j]
        a.update(
            seconds=round(a["seconds"] + b["seconds"], 1),
            intervals=merge_intervals(a["intervals"] + b["intervals"]),
            embedding=_rounded(_normalize(vectors[i] * a["seconds"] + vectors[j] * b["seconds"])),
        )
        alive[j] = False
        vectors[i] = _normalize(a["embedding"])
        row = vectors @ vectors[i]
        row[~alive] = -np.inf
        row[i] = -np.inf
        similarity[i], similarity[:, i] = row, row
        similarity[j], similarity[:, j] = -np.inf, -np.inf
    return [voice for voice, keep in zip(voices, alive, strict=True) if keep]


def label_voices(voices: list[dict], profiles: list[dict]) -> list[dict]:
    """Names recognized voices after their profile (each profile once, most similar first); the others become
    "Stimme 1", "Stimme 2", ... in the order of their speaking time. A voice is only recognized with enough
    speaking time, a clear similarity and a clear lead over the second-best profile."""
    voices = sorted(voices, key=lambda v: -v["seconds"])
    candidates = [p for p in profiles if p.get("model") == EMBEDDING_NAME]
    pairs = []
    for i, voice in enumerate(voices):
        scores = sorted((_similarity(voice["embedding"], p["embedding"]) for p in candidates), reverse=True)
        best = max(candidates, key=lambda p: _similarity(voice["embedding"], p["embedding"]), default=None)
        runner_up = scores[1] if len(scores) > 1 else -1.0
        if (
            best
            and voice["seconds"] >= MIN_MATCH_SECONDS
            and scores[0] >= MATCH_THRESHOLD
            and scores[0] - runner_up >= MATCH_MARGIN
        ):
            pairs.append((scores[0], i, best))
    matches, used = {}, set()
    for similarity, i, profile in sorted(pairs, key=lambda pair: -pair[0]):
        if profile["id"] not in used:
            matches[i] = (profile, similarity)
            used.add(profile["id"])
    unknown = 0
    for i, voice in enumerate(voices):
        if i in matches:
            profile, similarity = matches[i]
            voice.update(label=profile["name"], profile_id=profile["id"], similarity=round(similarity, 3))
        else:
            unknown += 1
            voice.update(label=UNKNOWN_LABEL.format(number=unknown), profile_id=None, similarity=None)
    return voices


def part_bounds(samples: np.ndarray, parts: int) -> list[int]:
    """Sample indices where the parts begin and end; every cut lies in the quietest half second near its
    nominal position, so that no word is cut in two."""
    window, search = SAMPLE_RATE // 2, int(SPLIT_SEARCH_SECONDS * SAMPLE_RATE)
    bounds = [0]
    for part in range(1, parts):
        nominal = len(samples) * part // parts
        start = max(bounds[-1] + window, nominal - search)
        region = samples[start : nominal + search]
        frames = len(region) // window
        energy = np.square(region[: frames * window]).reshape(frames, window).mean(axis=1)
        bounds.append(start + int(np.argmin(energy)) * window + window // 2)
    return bounds + [len(samples)]


def _voices_in(voice_engine, samples: np.ndarray, offset: float = 0.0) -> list[dict]:
    """Voices of one part with their times in the whole recording and their fingerprints."""
    found = []
    for segments in voice_engine.diarize(samples):
        seconds = sum(end - start for start, end in segments)
        if seconds < MIN_PART_VOICE_SECONDS:
            continue
        found.append(
            {
                "seconds": round(seconds, 1),
                "intervals": merge_intervals([(start + offset, end + offset) for start, end in segments]),
                "embedding": _rounded(fingerprint(voice_engine, samples, segments)),
            }
        )
    return found


def _part_voices(wav_path: str, start: int, end: int, threads: int) -> list[dict]:
    """Runs in a separate process for one part of the recording."""
    return _voices_in(VoiceEngine(threads), read_system_channel(wav_path, start, end), start / SAMPLE_RATE)


def part_count(seconds: float, workers: int) -> int:
    """Parts of a recording: at most one per process, each at least MIN_PART_SECONDS long."""
    return int(max(1, min(workers, seconds // MIN_PART_SECONDS)))


def recognize_voices(
    wav_path: str,
    voice_engine=None,
    profiles: list[dict] | None = None,
    workers: int = 1,
    report=lambda key, **params: None,
) -> list[dict]:
    """Separates the voices on the system-audio channel and compares them with the saved profiles.
    The work runs in separate processes, because sherpa-onnx keeps Python's GIL while it computes and would
    block the web server; long recordings are split at pauses into up to `workers` parts that run at the same
    time, and the voices of the parts are merged by their fingerprints. With a voice_engine (tests) everything
    runs in this process."""
    if voice_engine:
        found = _voices_in(voice_engine, read_system_channel(wav_path))
    else:
        ensure_models(report)
        with wave.open(wav_path, "rb") as wf:
            frames = wf.getnframes()
        parts = part_count(frames / SAMPLE_RATE, workers)
        bounds = part_bounds(read_system_channel(wav_path), parts) if parts > 1 else [0, frames]
        threads = max(1, min(4, (os.cpu_count() or 2) // 2 // parts))  # together not more than the physical cores
        found = []
        with ProcessPoolExecutor(parts) as pool:
            jobs = [pool.submit(_part_voices, wav_path, start, end, threads) for start, end in pairwise(bounds)]
            for done, job in enumerate(as_completed(jobs), 1):
                found += job.result()
                if parts > 1:
                    report("step.recognizing_voices_parts", done=done, total=parts)
    voices = [voice for voice in merge_similar_voices(found) if voice["seconds"] >= MIN_VOICE_SECONDS]
    return label_voices(voices, load_profiles() if profiles is None else profiles)


def voice_context(voices: list[dict]) -> str:
    """Block for the Gemini request: who speaks when on the system-audio channel."""
    if not voices:
        return ""
    lines = []
    for voice in voices:
        origin = (
            f"gespeichertes Stimmprofil, Übereinstimmung {voice['similarity']:.0%}"
            if voice.get("profile_id")
            else "unbekannte Stimme"
        )
        times = ", ".join(f"[{format_duration(s)}–{format_duration(e)}]" for s, e in voice["intervals"])
        lines.append(f"- „{voice['label']}“ ({origin}): {times}")
    return (
        "\n<lokale_stimmerkennung>\n"
        "Die Stimmen auf dem Systemton (Kanal 1) wurden lokal getrennt und mit gespeicherten Stimmprofilen verglichen:\n"
        + "\n".join(lines)
        + "\nVerwende für diese Stimmen genau diese Bezeichnungen statt eigener Kürzel. Namen aus Stimmprofilen gelten als Beleg."
        " Eine unbekannte Stimme benennst du nur um, wenn das Gespräch ihren Namen eindeutig belegt.\n"
        "</lokale_stimmerkennung>\n"
    )


# ---------- profiles ----------
def load_profiles() -> list[dict]:
    if not PROFILES_FILE.exists():
        return []
    return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))


def _save_profiles(profiles: list[dict]) -> None:
    PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(json.dumps(profiles, ensure_ascii=False, indent=1), encoding="utf-8")


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name)) and not _UNKNOWN.match(name)


def save_profile(name: str, embedding, seconds: float) -> dict:
    """Adds a voice to the profile of this name (weighted by speaking time) or creates the profile."""
    profiles = load_profiles()
    now = datetime.now().isoformat(timespec="seconds")
    profile = next(
        (p for p in profiles if p["name"].casefold() == name.casefold() and p.get("model") == EMBEDDING_NAME),
        None,
    )
    if profile:
        mixed = _normalize(profile["embedding"]) * profile["seconds"] + _normalize(embedding) * seconds
        profile.update(
            embedding=_rounded(_normalize(mixed)),
            seconds=round(profile["seconds"] + seconds, 1),
            samples=profile["samples"] + 1,
            updated_at=now,
        )
    else:
        profile = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "model": EMBEDDING_NAME,
            "embedding": _rounded(_normalize(embedding)),
            "seconds": round(seconds, 1),
            "samples": 1,
            "consent_confirmed_at": now,
            "updated_at": now,
        }
        profiles.append(profile)
    _save_profiles(profiles)
    return profile


def delete_profile(profile_id: str) -> bool:
    profiles = load_profiles()
    remaining = [p for p in profiles if p["id"] != profile_id]
    if len(remaining) == len(profiles):
        return False
    _save_profiles(remaining)
    return True


def rename_speaker(markdown: str, old: str, new: str) -> str:
    """Replaces a voice label in the minutes: generated labels everywhere, real names only as bold speaker labels."""
    if _UNKNOWN.match(old):
        markdown = re.sub(rf" \({re.escape(old)}\)", "", markdown)  # "Roland (Stimme 1)": a name from the conversation
        return re.sub(rf"{re.escape(old)}(?!\d)", lambda _: new, markdown)
    return re.sub(rf"\*\*{re.escape(old)}(:?)\*\*", lambda m: f"**{new}{m.group(1)}**", markdown)

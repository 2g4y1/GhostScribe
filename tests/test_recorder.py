import json
import shutil
import wave

import numpy as np
import pytest

from ghostscribe import recorder as recorder_module
from ghostscribe.i18n import LocalizedError
from ghostscribe.recorder import MeetingRecorder, resample_to_mono

from fakes import Clock, FakeBackend

SR_IN, SR_OUT = 48000, 16000
AMPLITUDE = 10000


def tone(freq, seconds=1.0, channels=1):
    t = np.arange(int(SR_IN * seconds)) / SR_IN
    mono = (AMPLITUDE * np.sin(2 * np.pi * freq * t)).astype(np.int16)
    return np.repeat(mono[:, None], channels, axis=1)


def rms(samples):
    return float(np.sqrt(np.mean(samples[500:-500].astype(np.float64) ** 2)))


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def rec(tmp_path, backend, clock):
    return MeetingRecorder(output_dir=str(tmp_path), backend=backend, clock=clock)


def channels_of(path):
    with wave.open(str(path), "rb") as wf:
        assert (wf.getnchannels(), wf.getframerate()) == (2, SR_OUT)
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).reshape(-1, 2)


def test_resample_keeps_speech_frequencies():
    out = resample_to_mono(tone(1000), SR_IN, SR_OUT, mix_channels=False)

    assert len(out) == SR_OUT
    assert abs(rms(out) / (AMPLITUDE / np.sqrt(2)) - 1) < 0.02


def test_resample_removes_frequencies_above_target_nyquist():
    # Plain interpolation would fold a 12 kHz tone back to 4 kHz at almost full level (aliasing)
    out = resample_to_mono(tone(12000), SR_IN, SR_OUT, mix_channels=False)

    assert rms(out) < 10


def test_resample_mixes_the_first_two_channels():
    frames = np.zeros((SR_IN, 2), dtype=np.int16)
    frames[:, 0] = 1000

    out = resample_to_mono(frames, SR_IN, SR_IN, mix_channels=True)

    assert abs(int(out[SR_IN // 2]) - 500) <= 1


def test_resample_works_in_blocks(monkeypatch):
    monkeypatch.setattr(recorder_module, "RESAMPLE_BLOCK", 1000)
    whole = resample_to_mono(tone(440), SR_IN, SR_OUT, mix_channels=False)
    monkeypatch.setattr(recorder_module, "RESAMPLE_BLOCK", 1 << 20)

    assert np.array_equal(whole, resample_to_mono(tone(440), SR_IN, SR_OUT, mix_channels=False))


def test_recording_is_saved_as_synchronized_stereo_of_the_full_duration(rec, backend, clock, tmp_path):
    base = rec.start()
    clock.now += 1.0
    backend.on_mic(tone(1000, seconds=1.0).tobytes())  # the microphone delivers only 1 of 2 seconds
    backend.on_system(tone(500, seconds=1.0, channels=2).tobytes())
    clock.now += 1.0
    backend.on_system(tone(500, seconds=1.0, channels=2).tobytes())

    assert rec.stop_capture() and not rec.stop_capture()  # stopping twice does nothing the second time
    path = rec.save(compress=False)

    audio = channels_of(path)
    assert path == str(tmp_path / f"{base}.wav")
    assert len(audio) == 2 * SR_OUT
    assert rms(audio[:SR_OUT, 0]) > 5000 and rms(audio[SR_OUT:, 0]) == 0  # left: microphone, then silence
    assert rms(audio[:, 1]) > 5000  # right: system audio for the whole recording
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{base}.wav"]  # the raw inputs are removed


def test_an_input_that_delivered_nothing_for_a_while_stays_in_time(rec, backend, clock):
    rec.start()
    clock.now += 1.0
    backend.on_system(tone(500, seconds=1.0, channels=2).tobytes())
    clock.now += 3.0  # the playback device played nothing for two seconds: no data from its loopback
    backend.on_system(tone(500, seconds=1.0, channels=2).tobytes())
    rec.stop_capture()

    system = channels_of(rec.save(compress=False))[:, 1]
    assert len(system) == 4 * SR_OUT
    assert rms(system[:SR_OUT]) > 5000 and rms(system[3 * SR_OUT :]) > 5000
    assert rms(system[SR_OUT : 3 * SR_OUT]) == 0  # the pause is where it happened, not at the end


def test_the_usual_delay_of_an_input_is_not_mistaken_for_a_gap(rec, backend, clock):
    rec.start()
    clock.now += 1.5  # the sound server delivers its first half second one second late (latency)
    backend.on_mic(tone(1000, seconds=0.5).tobytes())
    clock.now += 0.5
    backend.on_mic(tone(1000, seconds=0.5).tobytes())
    rec.stop_capture()

    mic = channels_of(rec.save(compress=False))[:, 0]
    assert len(mic) == 2 * SR_OUT
    assert rms(mic[:SR_OUT]) > 5000 and rms(mic[SR_OUT:]) == 0  # in place; the last second was still under way


def test_a_loopback_that_starts_late_is_placed_at_its_time(rec, backend, clock):
    rec.start()
    for _ in range(5):
        clock.now += 1.0
        backend.on_mic(tone(1000, seconds=1.0).tobytes())
    backend.on_system(tone(500, seconds=1.0, channels=2).tobytes())  # nothing was played in the first four seconds
    rec.stop_capture()

    audio = channels_of(rec.save(compress=False))
    assert len(audio) == 5 * SR_OUT and rms(audio[:, 0]) > 5000
    assert rms(audio[: 4 * SR_OUT, 1]) == 0 and rms(audio[4 * SR_OUT :, 1]) > 5000


def test_a_pause_is_cut_out_of_the_recording(rec, backend, clock):
    rec.start()
    clock.now += 1.0
    backend.on_mic(tone(1000, seconds=1.0).tobytes())
    backend.on_system(tone(500, seconds=1.0, channels=2).tobytes())
    assert rec.pause() and rec.paused
    clock.now += 30.0  # a coffee break: the inputs keep delivering, but nothing of it is recorded
    backend.on_mic(np.full((SR_IN, 1), 32000, dtype=np.int16).tobytes())
    backend.on_system(np.full((SR_IN, 2), 32000, dtype=np.int16).tobytes())
    assert rec.resume() and not rec.paused
    clock.now += 1.0
    backend.on_mic(tone(1000, seconds=1.0).tobytes())
    backend.on_system(tone(500, seconds=1.0, channels=2).tobytes())
    rec.stop_capture()

    audio = channels_of(rec.save(compress=False))
    assert rec.duration == 2.0 and rec.cuts == [1.0]
    assert len(audio) == 2 * SR_OUT  # the thirty seconds of the pause are not in it
    assert np.abs(audio).max() < 15000  # neither is what the inputs delivered meanwhile
    for column in (0, 1):  # no silence was filled in for the pause: both seconds follow each other directly
        assert rms(audio[:SR_OUT, column]) > 5000 and rms(audio[SR_OUT:, column]) > 5000


def test_the_time_and_the_levels_stand_still_while_paused(rec, backend, clock):
    rec.start()
    clock.now += 1.0
    backend.on_mic(tone(1000, seconds=1.0).tobytes())
    assert rec.mic_level > 0

    rec.pause()
    clock.now += 10.0
    backend.on_mic(tone(1000, seconds=1.0).tobytes())
    assert (rec.get_duration(), rec.mic_level) == (1.0, 0.0)

    rec.resume()
    clock.now += 0.5
    assert rec.get_duration() == 1.5


def test_the_usual_delay_of_an_input_survives_a_pause(rec, backend, clock):
    rec.start()
    clock.now += 1.5  # one second of latency, as in the test above
    backend.on_mic(tone(1000, seconds=0.5).tobytes())
    clock.now += 0.5
    backend.on_mic(tone(1000, seconds=0.5).tobytes())
    rec.pause()
    clock.now += 60.0
    rec.resume()
    clock.now += 0.5
    backend.on_mic(tone(1000, seconds=0.5).tobytes())  # still one second behind: no gap to fill
    rec.stop_capture()

    mic = channels_of(rec.save(compress=False))[:, 0]
    assert len(mic) == int(2.5 * SR_OUT)
    assert rms(mic[: int(1.5 * SR_OUT)]) > 5000 and rms(mic[int(1.5 * SR_OUT) :]) == 0


def test_a_recording_stopped_while_paused_ends_at_the_pause(rec, backend, clock):
    assert not rec.pause() and not rec.resume()  # nothing is recording
    rec.start()
    assert not rec.resume()  # not paused
    clock.now += 1.0
    backend.on_mic(tone(1000, seconds=1.0).tobytes())
    assert rec.pause() and not rec.pause()
    clock.now += 30.0
    rec.stop_capture()

    assert rec.duration == 1.0 and rec.cuts == [] and not rec.paused
    assert len(channels_of(rec.save(compress=False))) == SR_OUT


@pytest.mark.parametrize(
    ("first_delays", "offsets"),
    [
        ({"mic": 0.02, "system": 30.02}, {"mic": 0.0, "system": 30.0}),  # a loopback that had nothing to play
        ({"mic": 1.0, "system": 1.0}, {"mic": 0.0, "system": 0.0}),  # the same latency on both inputs
        ({"mic": 0.509, "system": 0.488}, {"mic": 0.0, "system": 0.0}),  # one audio block apart: no shift
        ({"mic": 0.5, "system": None}, {"mic": 0.0}),  # the system audio delivered nothing at all
    ],
)
def test_the_later_input_starts_later_in_the_recording(first_delays, offsets):
    assert recorder_module.start_offsets(first_delays) == offsets


def test_level_meters_follow_the_inputs_without_overflow(rec, backend):
    rec.start()
    backend.on_mic(np.array([-32768, 0], dtype=np.int16).tobytes())

    assert rec.mic_level == 1.0 and rec.loopback_level == 0.0
    rec.stop_capture()
    assert rec.mic_level == 0.0


def test_an_interrupted_recording_is_recovered_at_the_next_start(tmp_path, backend, clock):
    crashed = MeetingRecorder(output_dir=str(tmp_path), backend=backend, clock=clock)
    base = crashed.start()
    clock.now += 1.0
    backend.on_mic(tone(1000).tobytes())
    backend.on_system(tone(500, channels=2).tobytes())
    crashed._release()  # the process ended: its files are closed, nothing was converted

    restarted = MeetingRecorder(output_dir=str(tmp_path), backend=FakeBackend())
    assert restarted.interrupted_recordings() == [base]
    path = restarted.recover(base)

    audio = channels_of(path if path.endswith(".wav") else path[:-4] + ".wav")
    assert len(audio) == SR_OUT and rms(audio[:, 0]) > 5000 and rms(audio[:, 1]) > 5000
    assert restarted.interrupted_recordings() == []


def test_recovery_without_audio_only_cleans_up(tmp_path, backend):
    crashed = MeetingRecorder(output_dir=str(tmp_path), backend=backend)
    base = crashed.start()
    crashed._release()

    assert crashed.recover(base) is None
    assert list(tmp_path.iterdir()) == []


def test_cancel_deletes_the_recorded_audio(rec, backend, tmp_path):
    rec.start()
    backend.on_mic(tone(1000).tobytes())

    rec.cancel()

    assert not rec.is_recording and backend.stopped
    assert list(tmp_path.iterdir()) == []


def test_a_failed_start_releases_everything(tmp_path):
    rec = MeetingRecorder(output_dir=str(tmp_path), backend=FakeBackend(fail=True))

    with pytest.raises(LocalizedError):
        rec.start()

    assert not rec.is_recording
    assert list(tmp_path.iterdir()) == []


def test_the_sidecar_describes_both_inputs(rec, tmp_path):
    base = rec.start()

    sidecar = json.loads((tmp_path / f"{base}.recording.json").read_text(encoding="utf-8"))
    assert sidecar["inputs"]["mic"] == {"device": "Headset", "channels": 1, "rate": SR_IN}
    assert sidecar["inputs"]["system"]["channels"] == 2
    rec.cancel()


def test_devices_are_listed_with_their_ids(rec):
    assert rec.list_devices()["loopbacks"] == [{"id": "2", "name": "Speakers [Loopback]", "default": True}]
    assert [d.name for d in rec.default_devices()] == ["Headset", "Speakers [Loopback]"]


def test_without_ffmpeg_the_wav_file_is_used(tmp_path, monkeypatch):
    wav = tmp_path / "meeting.wav"
    wav.write_bytes(b"RIFF")

    def missing_ffmpeg(*args, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(recorder_module.subprocess, "run", missing_ffmpeg)

    assert MeetingRecorder.compress_to_mp3(str(wav)) == str(wav)
    assert [p.name for p in tmp_path.iterdir()] == ["meeting.wav"]  # no half-written MP3 remains


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is optional")
def test_mp3_copy_is_mono_because_gemini_mixes_the_channels_down_anyway(tmp_path):
    wav = tmp_path / "meeting.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR_OUT)
        wf.writeframes(tone(1000, channels=2).tobytes())

    mp3 = MeetingRecorder.compress_to_mp3(str(wav))

    with open(mp3, "rb") as f:
        data = f.read()
    if data[:3] == b"ID3":  # skip the ID3v2 tag: 10-byte header, size as four 7-bit bytes
        data = data[10 + sum(byte << (7 * (3 - i)) for i, byte in enumerate(data[6:10])) :]
    assert data[0] == 0xFF and data[1] & 0xE0 == 0xE0  # MPEG audio frame header
    assert data[3] >> 6 == 3  # channel mode: mono

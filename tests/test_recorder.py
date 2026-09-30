import wave

import numpy as np

from recorder import MeetingRecorder, resample_to_mono

SR_IN, SR_OUT = 48000, 16000
AMPLITUDE = 10000


def tone(freq, seconds=1.0, channels=1):
    t = np.arange(int(SR_IN * seconds)) / SR_IN
    mono = (AMPLITUDE * np.sin(2 * np.pi * freq * t)).astype(np.int16)
    return np.repeat(mono[:, None], channels, axis=1)


def rms(samples):
    return float(np.sqrt(np.mean(samples[500:-500].astype(np.float64) ** 2)))


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


def test_save_pads_both_channels_to_the_recording_duration(tmp_path):
    recorder = MeetingRecorder(output_dir=str(tmp_path))
    recorder.start_time, recorder.end_time = 1_700_000_000.0, 1_700_000_002.0
    recorder.mic_channels, recorder.mic_rate = 1, SR_IN
    recorder.loopback_channels, recorder.loopback_rate = 2, SR_IN
    recorder.mic_frames = [tone(1000, seconds=1.0).tobytes()]  # microphone delivered only 1 of 2 seconds
    recorder.loopback_frames = [tone(500, seconds=2.0, channels=2).tobytes()]

    path = recorder.save(compress=False)

    with wave.open(path, "rb") as wf:
        assert (wf.getnchannels(), wf.getframerate(), wf.getnframes()) == (2, SR_OUT, 2 * SR_OUT)

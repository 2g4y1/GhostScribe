"""The audio backends against stand-ins for PyAudioWPatch (Windows) and SoundCard (Linux, macOS)."""

import sys
import threading
import time
import types
from typing import ClassVar

import numpy as np
import pytest

from ghostscribe import audio
from ghostscribe.i18n import LocalizedError


class FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.started = self.closed = False

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


class FakePyAudio:
    """WASAPI with a headset (default input), a USB microphone and the loopback of the speakers."""

    devices: ClassVar[list[dict]] = [
        {"index": 0, "name": "Headset", "maxInputChannels": 1, "defaultSampleRate": 48000.0},
        {"index": 1, "name": "USB Mic", "maxInputChannels": 4, "defaultSampleRate": 44100.0},
        {"index": 2, "name": "Speakers", "maxInputChannels": 0, "defaultSampleRate": 48000.0},
        {
            "index": 3,
            "name": "Speakers [Loopback]",
            "maxInputChannels": 2,
            "defaultSampleRate": 48000.0,
            "isLoopbackDevice": True,
        },
    ]
    opened: ClassVar[list] = []
    fail_on_open = False

    def __init__(self):
        self.terminated = False

    def get_host_api_info_by_type(self, api):
        return {"index": 0, "deviceCount": len(self.devices), "defaultInputDevice": 0, "defaultOutputDevice": 2}

    def get_device_info_by_host_api_device_index(self, api, i):
        return self.devices[i]

    def get_device_info_by_index(self, i):
        return self.devices[i]

    def get_loopback_device_info_generator(self):
        return (d for d in self.devices if d.get("isLoopbackDevice"))

    def open(self, **kwargs):
        if self.fail_on_open:
            raise OSError("[Errno -9996] Invalid device")
        stream = FakeStream(kwargs["stream_callback"])
        FakePyAudio.opened.append((kwargs, stream))
        return stream

    def terminate(self):
        self.terminated = True


@pytest.fixture
def pyaudio(monkeypatch):
    module = types.SimpleNamespace(PyAudio=FakePyAudio, paWASAPI=13, paInt16=8, paContinue=0)
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", module)
    FakePyAudio.opened = []
    FakePyAudio.fail_on_open = False
    return module


def connect_to(received):
    def connect(mic, system):
        return received["mic"].append, received["system"].append

    return connect


def test_windows_lists_microphones_and_loopbacks_with_their_defaults(pyaudio):
    microphones, loopbacks = audio.WasapiBackend().list_devices()

    assert [(d.id, d.name, d.channels, d.default) for d in microphones] == [
        ("0", "Headset", 1, True),
        ("1", "USB Mic", 2, False),  # at most two channels are recorded from a microphone
    ]
    assert [(d.id, d.channels, d.sample_rate, d.default) for d in loopbacks] == [("3", 2, 48000, True)]


def test_windows_opens_both_inputs_as_16_bit_streams(pyaudio):
    received = {"mic": [], "system": []}
    backend = audio.WasapiBackend()

    mic, system = backend.start("1", None, connect_to(received))

    assert (mic.name, system.name) == ("USB Mic", "Speakers [Loopback]")
    (mic_args, mic_stream), (system_args, system_stream) = FakePyAudio.opened
    assert (mic_args["input_device_index"], mic_args["channels"], mic_args["rate"]) == (1, 2, 44100)
    assert (system_args["input_device_index"], system_args["format"], system_args["input"]) == (3, 8, True)
    assert mic_stream.started and system_stream.started
    assert system_stream.callback(b"\x01\x00", 1, {}, 0) == (None, 0)  # delivered and continued
    assert received["system"] == [b"\x01\x00"]
    backend.stop()
    assert mic_stream.closed and system_stream.closed


def test_windows_releases_everything_when_a_device_cannot_be_opened(pyaudio):
    FakePyAudio.fail_on_open = True
    backend = audio.WasapiBackend()

    with pytest.raises(LocalizedError, match="Invalid device"):
        backend.start(None, None, connect_to({"mic": [], "system": []}))
    assert backend._pa is None and backend._streams == []

    with pytest.raises(LocalizedError):
        backend.start("42", None, connect_to({"mic": [], "system": []}))  # unplugged meanwhile


class FakeMicrophone:
    def __init__(self, device_id, name, channels=2, isloopback=False):
        self.id, self.name, self.channels, self.isloopback = device_id, name, channels, isloopback
        self.blocks = 0

    def recorder(self, samplerate, channels, blocksize):
        microphone = self

        class Recorder:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def record(self, numframes=None):
                microphone.blocks += 1
                return np.full((blocksize, channels), 0.5, dtype=np.float32)

        return Recorder()


def fake_soundcard(monkeypatch, microphones, speaker="alsa_output.speakers"):
    module = types.SimpleNamespace(
        all_microphones=lambda include_loopback=False: [m for m in microphones if include_loopback or not m.isloopback],
        default_microphone=lambda: microphones[0],
        default_speaker=lambda: types.SimpleNamespace(id=speaker),
    )
    monkeypatch.setitem(sys.modules, "soundcard", module)


def test_linux_records_the_monitor_of_the_default_output(monkeypatch):
    headset = FakeMicrophone("alsa_input.headset", "Headset", channels=1)
    monitor = FakeMicrophone("alsa_output.speakers.monitor", "Monitor of Speakers", isloopback=True)
    other = FakeMicrophone("alsa_output.hdmi.monitor", "Monitor of HDMI", isloopback=True)
    fake_soundcard(monkeypatch, [headset, monitor, other])
    backend = audio.SoundCardBackend(platform="linux")

    microphones, loopbacks = backend.list_devices()
    assert [(d.id, d.default) for d in microphones] == [("alsa_input.headset", True)]
    assert [(d.id, d.default) for d in loopbacks] == [
        ("alsa_output.speakers.monitor", True),
        ("alsa_output.hdmi.monitor", False),
    ]

    blocks = {"mic": [], "system": []}
    arrived = threading.Event()

    def connect(mic, system):
        def on_system(data):
            blocks["system"].append(data)
            arrived.set()

        return blocks["mic"].append, on_system

    backend.start(None, None, connect)
    assert arrived.wait(5)
    backend.stop()
    pcm = np.frombuffer(blocks["system"][0], dtype="<i2")
    assert len(pcm) == 2 * backend.BLOCK_FRAMES and pcm[0] == 16383  # float32 0.5 as 16-bit PCM, stereo
    delivered = len(blocks["system"])
    time.sleep(0.1)
    assert len(blocks["system"]) == delivered  # the input threads have ended


def test_macos_takes_a_virtual_input_such_as_blackhole_for_the_system_audio(monkeypatch):
    fake_soundcard(monkeypatch, [FakeMicrophone(73, "MacBook Pro Microphone", 1), FakeMicrophone(81, "BlackHole 2ch")])

    microphones, systems = audio.SoundCardBackend(platform="darwin").list_devices()

    assert [d.name for d in systems if d.default] == ["BlackHole 2ch"]
    assert [d.id for d in microphones] == ["73", "81"]


def test_macos_without_a_virtual_input_explains_what_is_missing(monkeypatch):
    fake_soundcard(monkeypatch, [FakeMicrophone(73, "MacBook Pro Microphone", 1)])

    with pytest.raises(LocalizedError, match="BlackHole"):
        audio.SoundCardBackend(platform="darwin").start(None, None, connect_to({"mic": [], "system": []}))


def test_a_missing_sound_server_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "soundcard", None)  # the import fails, as it does without a server

    with pytest.raises(LocalizedError, match="PulseAudio or PipeWire"):
        audio.SoundCardBackend()

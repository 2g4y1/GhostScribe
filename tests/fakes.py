"""Test doubles for the audio devices and the clock."""

from ghostscribe.audio import AudioBackend, Device
from ghostscribe.i18n import LocalizedError

SAMPLE_RATE = 48000


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeBackend(AudioBackend):
    """A mono microphone and a stereo playback device; the test delivers the audio itself."""

    mic = Device("1", "Headset", 1, SAMPLE_RATE, default=True)
    system = Device("2", "Speakers [Loopback]", 2, SAMPLE_RATE, default=True)

    def __init__(self, fail=False):
        self.fail = fail
        self.stopped = 0
        self.on_mic = self.on_system = None

    def list_devices(self):
        return [self.mic], [self.system]

    def start(self, mic_id, system_id, connect):
        if mic_id not in (None, self.mic.id) or system_id not in (None, self.system.id):
            raise LocalizedError("error.device_unavailable")
        self.on_mic, self.on_system = connect(self.mic, self.system)
        if self.fail:
            raise LocalizedError("error.device_failed", error="test")
        return self.mic, self.system

    def stop(self):
        self.stopped += 1

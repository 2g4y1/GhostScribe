"""
Audio capture backends for the two inputs of a recording: the microphone and the system audio (what the other
participants say). Windows records both with WASAPI (PyAudioWPatch, loopback of the playback device), Linux with
PulseAudio/PipeWire (monitor of the playback device) and macOS with Core Audio (a virtual input such as BlackHole),
the latter two through SoundCard. Every backend delivers interleaved 16-bit PCM blocks to a callback.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from ghostscribe.i18n import LocalizedError

logger = logging.getLogger(__name__)

OnAudio = Callable[[bytes], None]  # receives interleaved 16-bit little-endian PCM frames
# Called with the chosen microphone and system-audio device before their inputs start; returns their callbacks
Connect = Callable[["Device", "Device"], tuple[OnAudio, OnAudio]]
# Without a device for the system audio: macOS needs a virtual input first
NO_LOOPBACK = "error.no_loopback_macos" if sys.platform == "darwin" else "error.no_loopback"


@dataclass(frozen=True)
class Device:
    id: str  # backend-specific, valid until the devices change
    name: str
    channels: int  # channels that are recorded
    sample_rate: int
    default: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "default": self.default}


class AudioBackend(ABC):
    @abstractmethod
    def list_devices(self) -> tuple[list[Device], list[Device]]:
        """Microphones and system-audio devices, freshly scanned (a headset may have been plugged in)."""

    @abstractmethod
    def start(self, mic_id: str | None, system_id: str | None, connect: Connect) -> tuple[Device, Device]:
        """Opens and starts both inputs (None = the default device) and returns them. Releases everything and
        raises LocalizedError if one of them cannot be opened."""

    @abstractmethod
    def stop(self) -> None:
        """Stops both inputs; safe to call repeatedly."""


def pick_device(devices: list[Device], device_id: str | None, missing_key: str) -> Device:
    """The device with this id, or the default device for None."""
    if device_id is None:
        device = next((d for d in devices if d.default), None)
        if device is None:
            raise LocalizedError(missing_key)
        return device
    device = next((d for d in devices if d.id == device_id), None)
    if device is None:
        raise LocalizedError("error.device_unavailable")
    return device


class WasapiBackend(AudioBackend):
    """Windows: WASAPI through PyAudioWPatch, with the loopback of the playback device as system audio."""

    def __init__(self) -> None:
        import pyaudiowpatch  # Windows only

        self._pyaudio = pyaudiowpatch
        self._pa: Any = None
        self._streams: list[Any] = []

    def _default_loopback(self, pa: Any, wasapi: dict) -> dict | None:
        """The loopback device of the default output device."""
        if wasapi["defaultOutputDevice"] < 0:
            return None
        speakers = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if speakers.get("isLoopbackDevice", False):
            return speakers
        return next((lb for lb in pa.get_loopback_device_info_generator() if speakers["name"] in lb["name"]), None)

    @staticmethod
    def _device(info: dict, default: bool, max_channels: int | None = None) -> Device:
        channels = info["maxInputChannels"]
        if max_channels:
            channels = max(1, min(max_channels, channels))
        return Device(str(info["index"]), info["name"], channels, int(info["defaultSampleRate"]), default)

    def _scan(self, pa: Any) -> tuple[list[Device], list[Device]]:
        wasapi = pa.get_host_api_info_by_type(self._pyaudio.paWASAPI)
        default_loopback = self._default_loopback(pa, wasapi)
        microphones = []
        for i in range(wasapi["deviceCount"]):
            info = pa.get_device_info_by_host_api_device_index(wasapi["index"], i)
            if info["maxInputChannels"] > 0 and not info.get("isLoopbackDevice", False):
                is_default = info["index"] == wasapi["defaultInputDevice"]
                microphones.append(self._device(info, is_default, max_channels=2))
        loopbacks = [
            self._device(info, default_loopback is not None and info["index"] == default_loopback["index"])
            for info in pa.get_loopback_device_info_generator()
        ]
        return microphones, loopbacks

    def list_devices(self) -> tuple[list[Device], list[Device]]:
        pa = self._pyaudio.PyAudio()
        try:
            return self._scan(pa)
        finally:
            pa.terminate()

    def _open(self, device: Device, on_audio: OnAudio) -> Any:
        continue_flag = self._pyaudio.paContinue

        def callback(in_data, frame_count, time_info, status):
            on_audio(in_data)
            return (None, continue_flag)

        return self._pa.open(
            format=self._pyaudio.paInt16,
            channels=device.channels,
            rate=device.sample_rate,
            input=True,
            input_device_index=int(device.id),
            stream_callback=callback,
        )

    def start(self, mic_id: str | None, system_id: str | None, connect: Connect) -> tuple[Device, Device]:
        self.stop()
        self._pa = self._pyaudio.PyAudio()
        try:
            microphones, loopbacks = self._scan(self._pa)
            mic = pick_device(microphones, mic_id, "error.no_microphone")
            system = pick_device(loopbacks, system_id, NO_LOOPBACK)
            on_mic, on_system = connect(mic, system)
            self._streams = [self._open(mic, on_mic), self._open(system, on_system)]
            for stream in self._streams:
                stream.start_stream()
        except LocalizedError:
            self.stop()
            raise
        except Exception as e:  # PortAudio errors, e.g. the device was unplugged since the list was loaded
            self.stop()
            raise LocalizedError("error.device_failed", error=e) from e
        return mic, system

    def stop(self) -> None:
        for stream in self._streams:
            try:
                stream.stop_stream()
                stream.close()
            except OSError as e:
                logger.warning("Could not close an audio stream: %s", e)
        self._streams = []
        if self._pa is not None:
            try:
                self._pa.terminate()
            except OSError as e:
                logger.warning("Could not release PortAudio: %s", e)
            self._pa = None


# Virtual inputs that carry the system audio on macOS (it has no loopback of its own)
MACOS_VIRTUAL_INPUT = re.compile(r"blackhole|loopback|soundflower", re.IGNORECASE)


class SoundCardBackend(AudioBackend):
    """Linux (PulseAudio or PipeWire) and macOS (Core Audio) through SoundCard. Each input is read by a thread."""

    SAMPLE_RATE = 48000  # the sound server converts the device rate; ghostscribe.recorder downsamples afterwards
    BLOCK_FRAMES = 1024  # about 20 ms: keeps the level meters lively
    OPEN_TIMEOUT = 10.0
    STOP_TIMEOUT = 2.0

    def __init__(self, platform: str = sys.platform) -> None:
        try:
            import soundcard  # connects to the sound server on import (Linux)
        except Exception as e:  # e.g. neither PulseAudio nor PipeWire is running
            raise LocalizedError("error.audio_unavailable", error=e) from e
        self._sc = soundcard
        self._macos = platform == "darwin"
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._errors: list[Exception] = []

    def _default_id(self, get_default: Callable[[], Any]) -> str | None:
        try:
            return str(get_default().id)
        except Exception:  # no default device
            return None

    def _inputs(self) -> tuple[list[tuple[Device, Any]], list[tuple[Device, Any]]]:
        """(Device, SoundCard microphone) pairs of the microphones and the system-audio devices."""
        sc = self._sc
        default_mic = self._default_id(sc.default_microphone)
        microphones = [
            (self._device(m, str(m.id) == default_mic), m) for m in sc.all_microphones(include_loopback=False)
        ]
        if self._macos:
            # Core Audio has no loopback: the system audio comes from a virtual input such as BlackHole
            inputs = sc.all_microphones()
            virtual = next((m for m in inputs if MACOS_VIRTUAL_INPUT.search(m.name)), None)
            systems = [(self._device(m, m is virtual), m) for m in inputs]
        else:
            # PulseAudio and PipeWire name the monitor of an output "<output>.monitor"
            speaker = self._default_id(sc.default_speaker)
            monitors = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
            systems = [(self._device(m, str(m.id) == f"{speaker}.monitor"), m) for m in monitors]
        return microphones, systems

    def _device(self, microphone: Any, default: bool) -> Device:
        channels = microphone.channels if isinstance(microphone.channels, int) else len(microphone.channels)
        return Device(str(microphone.id), microphone.name, max(1, min(2, channels)), self.SAMPLE_RATE, default)

    def list_devices(self) -> tuple[list[Device], list[Device]]:
        microphones, systems = self._inputs()
        return [d for d, _ in microphones], [d for d, _ in systems]

    def _capture(self, source: Any, device: Device, on_audio: OnAudio, opened: threading.Event) -> None:
        try:
            with source.recorder(
                samplerate=device.sample_rate, channels=device.channels, blocksize=self.BLOCK_FRAMES
            ) as recorder:
                opened.set()
                while not self._stop.is_set():
                    block = recorder.record(numframes=None)
                    if self._stop.is_set():
                        break
                    on_audio((np.clip(block, -1.0, 1.0) * 32767).astype("<i2").tobytes())
        except Exception as e:
            logger.exception("Recording from %s failed", device.name)
            self._errors.append(e)
        finally:
            opened.set()

    def start(self, mic_id: str | None, system_id: str | None, connect: Connect) -> tuple[Device, Device]:
        self.stop()
        microphones, systems = self._inputs()
        mic = pick_device([d for d, _ in microphones], mic_id, "error.no_microphone")
        system = pick_device(
            [d for d, _ in systems], system_id, "error.no_loopback_macos" if self._macos else "error.no_loopback"
        )
        sources = {d.id: s for d, s in microphones + systems}
        on_mic, on_system = connect(mic, system)
        self._stop.clear()
        self._errors = []
        for device, on_audio in ((mic, on_mic), (system, on_system)):
            opened = threading.Event()
            thread = threading.Thread(
                target=self._capture, args=(sources[device.id], device, on_audio, opened), daemon=True
            )
            thread.start()
            self._threads.append(thread)
            if not opened.wait(self.OPEN_TIMEOUT) or self._errors:
                error = self._errors[0] if self._errors else TimeoutError(device.name)
                self.stop()
                raise LocalizedError("error.device_failed", error=error) from error
        return mic, system

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(self.STOP_TIMEOUT)
            if thread.is_alive():
                logger.warning("An audio input did not stop in time")
        self._threads = []


def default_backend() -> AudioBackend:
    """The audio backend of this operating system."""
    return WasapiBackend() if sys.platform == "win32" else SoundCardBackend()

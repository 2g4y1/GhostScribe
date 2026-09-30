"""
Two-channel meeting recorder: channel 0 (left) is the microphone (you), channel 1 (right) the system audio (the
other participants in Teams, Zoom, ...). While recording, each input is written unchanged to a raw file in
recordings/, so the memory use stays constant and a recording that was interrupted (crash, closed console window,
power cut) is recovered at the next start. Stopping turns both files into a synchronized 16 kHz stereo WAV plus a
mono MP3 copy.

Both inputs are kept in time with the clock: an input whose first audio arrives later than the other one's (e.g.
the loopback of a playback device that plays nothing yet) starts later in the recording, and an input that falls
behind its usual delay while recording (it delivered nothing meanwhile) is padded with silence. A pause is cut out:
the inputs keep running, but their audio is dropped and the clock of the recording stands still until it resumes.
"""

import contextlib
import json
import logging
import os
import subprocess
import threading
import time
import wave
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any, BinaryIO

import numpy as np

from ghostscribe.audio import NO_LOOPBACK, AudioBackend, Device, OnAudio, default_backend, pick_device
from ghostscribe.i18n import LocalizedError
from ghostscribe.utils import write_json_atomic

logger = logging.getLogger(__name__)
RESAMPLE_BLOCK = 1 << 20  # Output samples per processing block; bounds memory use for long meetings
GAP_SECONDS = 0.25  # an input this far behind its usual delay delivered nothing meanwhile: filled with silence
SIDECAR = ".recording.json"  # devices and start of a recording whose raw inputs are not converted yet
INPUTS = ("mic", "system")
MP3_TIMEOUT = 600  # seconds FFmpeg may take for one recording

Reader = Callable[[int, int], np.ndarray]  # frames [lo, hi) of an input as a (samples, channels) int16 array


def _lowpass_kernel(cutoff: float, taps: int = 127) -> np.ndarray:
    """Windowed-sinc FIR lowpass; cutoff as a fraction of the input sample rate (0..0.5)."""
    n = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(2 * cutoff * n) * np.blackman(taps)
    return (kernel / kernel.sum()).astype(np.float32)


def resampled_blocks(read: Reader, n_in: int, orig_sr: int, target_sr: int, mix_channels: bool) -> Iterator[np.ndarray]:
    """
    Converts (samples, channels) int16 audio to mono int16 at target_sr, RESAMPLE_BLOCK output samples at a time.
    mix_channels averages the first two channels, otherwise channel 0 is used.
    Before downsampling, everything above the target Nyquist frequency is filtered out;
    plain interpolation would fold those frequencies back into the speech band (aliasing).
    """
    ratio = orig_sr / target_sr
    n_out = int(n_in / ratio)
    kernel = _lowpass_kernel(0.44 / ratio) if ratio > 1 else None
    pad = len(kernel) if kernel is not None else 1

    for start in range(0, n_out, RESAMPLE_BLOCK):
        positions = np.arange(start, min(start + RESAMPLE_BLOCK, n_out)) * ratio
        lo = max(int(positions[0]) - pad, 0)
        hi = min(int(positions[-1]) + 2 + pad, n_in)
        block = read(lo, hi).astype(np.float32)
        mono = block[:, :2].mean(axis=1) if mix_channels and block.shape[1] > 1 else block[:, 0]
        if kernel is not None:
            mono = np.convolve(mono, kernel, mode="same")
        resampled = np.interp(positions - lo, np.arange(len(mono)), mono)
        yield np.clip(resampled, -32768, 32767).astype(np.int16)


def resample_to_mono(frames: np.ndarray, orig_sr: int, target_sr: int, mix_channels: bool) -> np.ndarray:
    """resampled_blocks() for audio in memory, as one array."""
    blocks = list(resampled_blocks(lambda lo, hi: frames[lo:hi], len(frames), orig_sr, target_sr, mix_channels))
    return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.int16)


class _Samples:
    """Hands out a stream of mono blocks in pieces of any size, after `lead` samples of silence."""

    def __init__(self, blocks: Iterator[np.ndarray], lead: int):
        self._blocks = blocks
        self._lead = lead
        self._buffer = np.zeros(0, dtype=np.int16)

    def take(self, count: int) -> np.ndarray:
        """The next `count` samples; fewer (or none) at the end of the stream."""
        silence = min(self._lead, count)
        self._lead -= silence
        parts, available = [np.zeros(silence, dtype=np.int16), self._buffer], silence + len(self._buffer)
        while available < count:
            block = next(self._blocks, None)
            if block is None:
                break
            parts.append(block)
            available += len(block)
        data = np.concatenate(parts)
        self._buffer = data[count:]
        return data[:count]


class _Capture:
    """One input while recording: appends its PCM blocks (arriving on an audio thread) to a raw file and keeps its
    level meter. The delay of its first block is its usual delay (latency, or a late start); falling further behind
    later means the input delivered nothing meanwhile, and the gap is filled with silence."""

    def __init__(self, path: str, started: float, clock: Callable[[], float]):
        self.path = path
        self.channels = 1
        self.rate = 1
        self.frames = 0
        self.level = 0.0
        self.first_delay: float | None = None  # seconds the first block was behind the start of the recording
        self.error: OSError | None = None
        self.paused = False
        self._delay: int | None = None  # frames the input usually lags behind the clock
        self._started = started
        self._clock = clock
        self._lock = threading.Lock()
        self._file: BinaryIO | None = open(path, "wb")  # noqa: SIM115 (closed by close())

    def configure(self, device: Device) -> None:
        self.channels, self.rate = device.channels, device.sample_rate

    def pause(self, paused: bool) -> None:
        """While paused, arriving blocks are dropped."""
        self.paused = paused
        self.level = 0.0

    def write(self, data: bytes) -> None:
        if self.paused:
            return
        pcm = np.frombuffer(data, dtype="<i2")
        count = len(pcm) // self.channels
        if not count:
            return
        self.level = min(1.0, float(np.abs(pcm.astype(np.int32)).max()) / 32768)
        with self._lock:
            if self._file is None or self.error:
                return  # a late block after the stop, or the disk is full
            try:
                lag = int((self._clock() - self._started) * self.rate) - self.frames - count
                if self._delay is None:
                    self._delay = lag
                    self.first_delay = lag / self.rate
                self._delay = min(self._delay, lag)
                if lag - self._delay > GAP_SECONDS * self.rate:
                    self._write_silence(self._file, lag - self._delay)
                self._file.write(data[: count * self.channels * 2])
                self.frames += count
            except OSError as e:  # e.g. the disk is full: what was written so far is kept
                logger.error("Recording to %s failed: %s", self.path, e)
                self.error = e

    def _write_silence(self, file: BinaryIO, frames: int) -> None:
        second = bytes(2 * self.channels * self.rate)
        while frames > 0:
            count = min(frames, self.rate)
            file.write(second[: 2 * self.channels * count])
            self.frames += count
            frames -= count

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


class _RawInput(contextlib.AbstractContextManager):
    """The raw file of one input, read block by block."""

    def __init__(self, path: str, channels: int):
        self.channels = channels
        self._frame_bytes = 2 * channels
        self.frames = os.path.getsize(path) // self._frame_bytes if os.path.exists(path) else 0
        self._file: BinaryIO | None = open(path, "rb") if self.frames else None  # noqa: SIM115 (closed by __exit__)

    def read(self, lo: int, hi: int) -> np.ndarray:
        if self._file is None:
            return np.zeros((0, self.channels), dtype=np.int16)
        self._file.seek(lo * self._frame_bytes)
        data = self._file.read((hi - lo) * self._frame_bytes)
        whole_frames = len(data) // self._frame_bytes * self.channels
        return np.frombuffer(data, dtype="<i2")[:whole_frames].reshape(-1, self.channels)

    def __exit__(self, *exc_info: object) -> None:
        if self._file is not None:
            self._file.close()


def start_offsets(first_delays: dict[str, float | None]) -> dict[str, float]:
    """Both inputs start together: an input whose first audio arrived clearly later than the other one's missed the
    difference (e.g. a loopback that had nothing to play yet) and starts that much later in the recording. Smaller
    differences are latency and block size."""
    known = {name: delay for name, delay in first_delays.items() if delay is not None}
    earliest = min(known.values(), default=0.0)
    return {
        name: round(delay - earliest, 3) if delay - earliest > GAP_SECONDS else 0.0 for name, delay in known.items()
    }


class MeetingRecorder:
    def __init__(
        self,
        target_sample_rate: int = 16000,
        output_dir: str = "recordings",
        backend: AudioBackend | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.target_sample_rate = target_sample_rate
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self._backend = backend
        self._clock = clock
        self._captures: dict[str, _Capture] = {}
        self._sidecar: dict[str, Any] = {}
        self._started = 0.0
        # (clock time of the running pause or None, seconds paused before it): replaced as a whole, so that the audio
        # threads always read a consistent pair
        self._pause: tuple[float | None, float] = (None, 0.0)
        self.cuts: list[float] = []  # positions in the recording where a pause was cut out

        self.is_recording = False
        self.base_name: str | None = None  # meeting_YYYY-MM-DD_HH-MM-SS of the current or last recording
        self.start_time = 0.0  # wall-clock start, names the recording
        self.duration = 0.0  # of the last stopped recording, in seconds
        self.mic: Device | None = None
        self.system: Device | None = None

    @property
    def backend(self) -> AudioBackend:
        if self._backend is None:
            self._backend = default_backend()  # imports the audio libraries only when they are needed
        return self._backend

    # Level meters (0.0 to 1.0)
    @property
    def mic_level(self) -> float:
        return self._level("mic")

    @property
    def loopback_level(self) -> float:
        return self._level("system")

    def _level(self, name: str) -> float:
        capture = self._captures.get(name)
        return capture.level if self.is_recording and capture else 0.0

    def _recording_clock(self) -> float:
        """The clock without the pauses: it stands still while the recording is paused."""
        paused_at, paused_before = self._pause
        return (self._clock() if paused_at is None else paused_at) - paused_before

    @property
    def paused(self) -> bool:
        return self.is_recording and self._pause[0] is not None

    def pause(self) -> bool:
        """Pauses the recording: what happens until resume() is not recorded. False if it is not running."""
        if not self.is_recording or self._pause[0] is not None:
            return False
        for capture in self._captures.values():
            capture.pause(True)
        self._pause = (self._clock(), self._pause[1])
        return True

    def resume(self) -> bool:
        """Continues a paused recording right where it was paused. False if it is not paused."""
        paused_at, paused_before = self._pause
        if not self.is_recording or paused_at is None:
            return False
        self._pause = (None, paused_before + self._clock() - paused_at)
        self.cuts.append(round(self.get_duration(), 3))
        for capture in self._captures.values():
            capture.pause(False)
        return True

    def list_devices(self) -> dict[str, list[dict]]:
        """The selectable microphones and system-audio devices; the defaults of the system are flagged."""
        microphones, loopbacks = self.backend.list_devices()
        return {"microphones": [d.as_dict() for d in microphones], "loopbacks": [d.as_dict() for d in loopbacks]}

    def default_devices(self) -> tuple[Device, Device]:
        microphones, loopbacks = self.backend.list_devices()
        return pick_device(microphones, None, "error.no_microphone"), pick_device(loopbacks, None, NO_LOOPBACK)

    def _path(self, base: str, suffix: str) -> str:
        return os.path.join(self.output_dir, base + suffix)

    def _input_path(self, base: str, name: str) -> str:
        return self._path(base, f".{name}.pcm")

    def start(self, mic_id: str | None = None, loopback_id: str | None = None) -> str:
        """Starts recording (None = the default device) and returns the base name of the recording."""
        if self.is_recording and self.base_name:
            return self.base_name
        os.makedirs(self.output_dir, exist_ok=True)  # the folder may have been deleted meanwhile
        start_time = time.time()
        base = datetime.fromtimestamp(start_time).strftime("meeting_%Y-%m-%d_%H-%M-%S")
        self._pause, self.cuts = (None, 0.0), []
        started = self._recording_clock()
        captures: dict[str, _Capture] = {}
        sidecar: dict[str, Any] = {"started_at": start_time}

        def connect(mic: Device, system: Device) -> tuple[OnAudio, OnAudio]:
            try:
                for name, device in zip(INPUTS, (mic, system), strict=True):
                    captures[name] = _Capture(self._input_path(base, name), started, self._recording_clock)
                    captures[name].configure(device)
                sidecar["inputs"] = {
                    name: {"device": device.name, "channels": device.channels, "rate": device.sample_rate}
                    for name, device in zip(INPUTS, (mic, system), strict=True)
                }
                write_json_atomic(self._path(base, SIDECAR), sidecar)
            except OSError as e:
                raise LocalizedError("error.save_audio_failed", error=e) from e
            return captures["mic"].write, captures["system"].write

        try:
            self.mic, self.system = self.backend.start(mic_id, loopback_id, connect)
        except BaseException:
            for capture in captures.values():
                capture.close()
            self._delete_inputs(base)
            raise
        self._captures, self._sidecar = captures, sidecar
        self.base_name, self.start_time, self._started = base, start_time, started
        self.is_recording = True
        return base

    def get_duration(self) -> float:
        """Seconds recorded so far, without the pauses."""
        return self._recording_clock() - self._started if self.is_recording else 0.0

    def stop_capture(self) -> bool:
        """Stops both inputs; the audio stays in its raw files until save() is called."""
        if not self.is_recording or not self.base_name:
            return False
        self.duration = self.get_duration()
        self.is_recording = False
        self._release()
        self._sidecar["duration"] = self.duration
        self._sidecar["offsets"] = start_offsets({name: c.first_delay for name, c in self._captures.items()})
        try:
            write_json_atomic(self._path(self.base_name, SIDECAR), self._sidecar)
        except OSError as e:  # save() uses the values in memory
            logger.warning("Could not update %s: %s", self._path(self.base_name, SIDECAR), e)
        return True

    def _release(self) -> None:
        if self._backend is not None:
            self._backend.stop()
        for capture in self._captures.values():
            capture.close()

    def save(self, compress: bool = True) -> str:
        """Synchronizes both inputs of the last recording into a 16-bit stereo WAV (plus a mono MP3 copy) and
        returns the file to upload."""
        if not self.base_name or self.is_recording:
            raise RuntimeError("There is no stopped recording to save.")
        return self._finish(self.base_name, self._sidecar, compress)

    def stop(self, compress: bool = True) -> str | None:
        """Stops recording and writes the audio files in one step (used by the CLI)."""
        if not self.stop_capture():
            return None
        return self.save(compress=compress)

    def cancel(self) -> None:
        """Cancels recording immediately, releases the devices and deletes the recorded audio."""
        was_recording, self.is_recording = self.is_recording, False
        self._release()
        if was_recording and self.base_name:
            self._delete_inputs(self.base_name)

    def interrupted_recordings(self) -> list[str]:
        """Base names of recordings that were not converted yet because the program ended while recording."""
        current = self.base_name if self.is_recording else None
        names = (name[: -len(SIDECAR)] for name in os.listdir(self.output_dir) if name.endswith(SIDECAR))
        return sorted(base for base in names if base != current)

    def recover(self, base: str) -> str | None:
        """Converts the raw inputs of an interrupted recording like save() and returns the file to upload, or None
        if nothing had been recorded yet."""
        inputs = [self._input_path(base, name) for name in INPUTS]
        if not any(os.path.isfile(path) and os.path.getsize(path) for path in inputs):
            self._delete_inputs(base)
            return None
        with open(self._path(base, SIDECAR), encoding="utf-8") as f:
            sidecar = json.load(f)
        return self._finish(base, sidecar, compress=True)

    def _finish(self, base: str, sidecar: dict[str, Any], compress: bool) -> str:
        wav_path = self._write_wav(base, sidecar)
        self._delete_inputs(base)
        return self.compress_to_mp3(wav_path) if compress else wav_path

    def _write_wav(self, base: str, sidecar: dict[str, Any]) -> str:
        """Left = microphone, right = system audio, both padded to the length of the recording."""
        rate = self.target_sample_rate
        offsets = sidecar.get("offsets", {})  # missing after an interruption: both inputs start at the beginning
        total = int(sidecar.get("duration", 0) * rate)
        wav_path = self._path(base, ".wav")
        partial = wav_path + ".part"
        with contextlib.ExitStack() as stack:
            channels = []
            for name in INPUTS:
                spec = sidecar["inputs"][name]
                raw = stack.enter_context(_RawInput(self._input_path(base, name), spec["channels"]))
                blocks = resampled_blocks(raw.read, raw.frames, spec["rate"], rate, mix_channels=name == "system")
                lead = int(offsets.get(name, 0) * rate)
                channels.append(_Samples(blocks, lead))
                total = max(total, lead + int(raw.frames / (spec["rate"] / rate)))
            with wave.open(partial, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(rate)
                for start in range(0, total, RESAMPLE_BLOCK):
                    stereo = np.zeros((min(RESAMPLE_BLOCK, total - start), 2), dtype=np.int16)
                    for column, samples in enumerate(channels):
                        block = samples.take(len(stereo))
                        stereo[: len(block), column] = block
                    wf.writeframes(stereo.tobytes())
        os.replace(partial, wav_path)
        return wav_path

    def _delete_inputs(self, base: str) -> None:
        for path in [*(self._input_path(base, name) for name in INPUTS), self._path(base, SIDECAR)]:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning("Could not delete %s: %s", path, e)

    @staticmethod
    def compress_to_mp3(wav_filepath: str, bitrate: str = "48k") -> str:
        """Compresses the WAV to a mono MP3 with a local FFmpeg (48 instead of 512 kbit/s, about 90 % smaller).
        The MP3 is played back and uploaded: Gemini mixes all channels down to mono anyway, while the stereo WAV
        keeps both channels for the channel timeline and the voice recognition."""
        if not os.path.exists(wav_filepath):
            return wav_filepath
        mp3_filepath = os.path.splitext(wav_filepath)[0] + ".mp3"
        partial = mp3_filepath + ".part"  # a half-written MP3 must never look like a finished recording
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", wav_filepath]
        cmd += ["-codec:a", "libmp3lame", "-b:a", bitrate, "-ac", "1", "-f", "mp3", partial]
        try:
            # No keys for FFmpeg: it would otherwise read the console input
            subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=MP3_TIMEOUT)
            if os.path.getsize(partial) > 0:
                os.replace(partial, mp3_filepath)
                return mp3_filepath
        except FileNotFoundError:
            logger.warning("FFmpeg was not found: the recording stays a WAV file (about ten times larger to upload)")
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("MP3 compression skipped, using the WAV file (%s)", e)
        finally:
            with contextlib.suppress(OSError):
                os.remove(partial)
        return wav_filepath

"""
Audio recording engine for Windows:
Captures both Microphone (User) and WASAPI Loopback (Speakers/Headphones/Teams)
simultaneously and merges them into a synchronized 2-channel WAV file.
Channel 0 (Left): Microphone (You)
Channel 1 (Right): System Audio (Teams / Other participants)
"""

import logging
import os
import subprocess
import time
import wave
from datetime import datetime

import numpy as np
import pyaudiowpatch as pyaudio

from ghostscribe.i18n import LocalizedError

logger = logging.getLogger(__name__)
RESAMPLE_BLOCK = 1 << 20  # Output samples per processing block; bounds memory use for long meetings


def _lowpass_kernel(cutoff: float, taps: int = 127) -> np.ndarray:
    """Windowed-sinc FIR lowpass; cutoff as a fraction of the input sample rate (0..0.5)."""
    n = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(2 * cutoff * n) * np.blackman(taps)
    return (kernel / kernel.sum()).astype(np.float32)


def resample_to_mono(frames: np.ndarray, orig_sr: int, target_sr: int, mix_channels: bool) -> np.ndarray:
    """
    Converts (samples, channels) int16 audio to mono int16 at target_sr.
    mix_channels averages the first two channels, otherwise channel 0 is used.
    Before downsampling, everything above the target Nyquist frequency is filtered out;
    plain interpolation would fold those frequencies back into the speech band (aliasing).
    """
    n_in = len(frames)
    ratio = orig_sr / target_sr
    n_out = int(n_in / ratio)
    out = np.zeros(n_out, dtype=np.int16)
    kernel = _lowpass_kernel(0.44 / ratio) if ratio > 1 else None
    pad = len(kernel) if kernel is not None else 1

    for start in range(0, n_out, RESAMPLE_BLOCK):
        positions = np.arange(start, min(start + RESAMPLE_BLOCK, n_out)) * ratio
        lo = max(int(positions[0]) - pad, 0)
        hi = min(int(positions[-1]) + 2 + pad, n_in)
        block = frames[lo:hi].astype(np.float32)
        mono = block[:, :2].mean(axis=1) if mix_channels and block.shape[1] > 1 else block[:, 0]
        if kernel is not None:
            mono = np.convolve(mono, kernel, mode="same")
        resampled = np.interp(positions - lo, np.arange(len(mono)), mono)
        out[start : start + len(positions)] = np.clip(resampled, -32768, 32767)
    return out


class MeetingRecorder:
    def __init__(self, target_sample_rate=16000, output_dir="recordings"):
        self.target_sample_rate = target_sample_rate
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        self.p = None
        self.is_recording = False
        self.start_time = 0.0
        self.end_time = 0.0

        self.mic_stream = None
        self.loopback_stream = None
        self.mic_frames = []
        self.loopback_frames = []

        self.mic_info = {}
        self.loopback_info = {}
        self.mic_channels = self.mic_rate = 0
        self.loopback_channels = self.loopback_rate = 0

        # Level meters (0.0 to 1.0)
        self.mic_level = 0.0
        self.loopback_level = 0.0

    @staticmethod
    def find_loopback_device(p):
        """Returns the WASAPI loopback device of the default output device, or None."""
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        if default_speakers.get("isLoopbackDevice", False):
            return default_speakers
        for loopback in p.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                return loopback
        return None

    @staticmethod
    def find_devices(p_instance=None):
        """Finds the default WASAPI microphone and the loopback device of the default output."""
        p = p_instance if p_instance is not None else pyaudio.PyAudio()
        try:
            default_loopback = MeetingRecorder.find_loopback_device(p)
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            if wasapi_info["defaultInputDevice"] < 0:
                raise LocalizedError("error.no_microphone")
            default_input = p.get_device_info_by_index(wasapi_info["defaultInputDevice"])
            if not default_loopback:
                raise LocalizedError("error.no_loopback")
            return default_input, default_loopback
        finally:
            if p_instance is None:
                try:
                    p.terminate()
                except Exception:
                    pass

    @staticmethod
    def list_devices():
        """Returns the selectable microphones and loopback devices; the Windows defaults are flagged."""
        p = pyaudio.PyAudio()
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_loopback = MeetingRecorder.find_loopback_device(p)
            microphones = []
            for i in range(wasapi_info["deviceCount"]):
                device = p.get_device_info_by_host_api_device_index(wasapi_info["index"], i)
                if device["maxInputChannels"] > 0 and not device.get("isLoopbackDevice", False):
                    is_default = device["index"] == wasapi_info["defaultInputDevice"]
                    microphones.append({"index": device["index"], "name": device["name"], "default": is_default})
            loopbacks = [
                {
                    "index": device["index"],
                    "name": device["name"],
                    "default": default_loopback is not None and device["index"] == default_loopback["index"],
                }
                for device in p.get_loopback_device_info_generator()
            ]
            return {"microphones": microphones, "loopbacks": loopbacks}
        finally:
            p.terminate()

    def _make_callback(self, frames, level_attr):
        """Creates a stream callback that buffers the audio and updates the given level meter."""

        def callback(in_data, frame_count, time_info, status):
            frames.append(in_data)
            data_arr = np.frombuffer(in_data, dtype=np.int16)
            if len(data_arr) > 0:
                setattr(self, level_attr, min(1.0, float(np.max(np.abs(data_arr))) / 32768.0))
            return (None, pyaudio.paContinue)

        return callback

    def _release_streams(self):
        """Stops and closes both streams and terminates PyAudio. Safe to call repeatedly."""
        for stream in (self.mic_stream, self.loopback_stream):
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
        if self.p:
            try:
                self.p.terminate()
            except Exception:
                pass
        self.mic_stream = self.loopback_stream = self.p = None

    def start(self, mic_index=None, loopback_index=None):
        """Starts recording asynchronously. A device index of None means the Windows default device."""
        if self.is_recording:
            return

        self._release_streams()
        self.p = pyaudio.PyAudio()
        try:
            default_mic = default_loopback = {}
            if mic_index is None or loopback_index is None:
                default_mic, default_loopback = self.find_devices(p_instance=self.p)
            self.mic_info = self.p.get_device_info_by_index(mic_index) if mic_index is not None else default_mic
            self.loopback_info = (
                self.p.get_device_info_by_index(loopback_index) if loopback_index is not None else default_loopback
            )
        except OSError as e:
            self._release_streams()
            raise LocalizedError("error.device_unavailable") from e

        self.mic_frames = []
        self.loopback_frames = []
        self.mic_level = 0.0
        self.loopback_level = 0.0

        self.mic_channels = max(1, min(2, self.mic_info["maxInputChannels"]))
        self.mic_rate = int(self.mic_info["defaultSampleRate"])
        self.loopback_channels = self.loopback_info["maxInputChannels"]
        self.loopback_rate = int(self.loopback_info["defaultSampleRate"])

        self.mic_stream = self.p.open(
            format=pyaudio.paInt16,
            channels=self.mic_channels,
            rate=self.mic_rate,
            input=True,
            input_device_index=self.mic_info["index"],
            stream_callback=self._make_callback(self.mic_frames, "mic_level"),
        )

        self.loopback_stream = self.p.open(
            format=pyaudio.paInt16,
            channels=self.loopback_channels,
            rate=self.loopback_rate,
            input=True,
            input_device_index=self.loopback_info["index"],
            stream_callback=self._make_callback(self.loopback_frames, "loopback_level"),
        )

        self.is_recording = True
        self.start_time = time.time()
        self.mic_stream.start_stream()
        self.loopback_stream.start_stream()

    def get_duration(self):
        """Returns elapsed recording duration in seconds."""
        if not self.is_recording or not self.start_time:
            return 0.0
        return time.time() - self.start_time

    def stop_capture(self):
        """Stops both streams; the captured audio stays buffered until save() is called."""
        if not self.is_recording:
            return False
        self.end_time = time.time()
        self.is_recording = False
        self._release_streams()
        return True

    def _take_frames(self, attr, channels):
        """Returns the buffered chunks of one stream as (samples, channels) int16 and frees the buffer."""
        chunks = getattr(self, attr)
        raw = b"".join(chunks)
        chunks.clear()
        return np.frombuffer(raw, dtype=np.int16).reshape(-1, channels)

    def save(self, compress=True, filename=None):
        """Synchronizes both channels into a 16-bit stereo WAV (plus MP3 copy) and returns the file to upload."""
        name = filename or datetime.fromtimestamp(self.start_time).strftime("meeting_%Y-%m-%d_%H-%M-%S.wav")
        output_filepath = os.path.join(self.output_dir, name)

        mic = resample_to_mono(
            self._take_frames("mic_frames", self.mic_channels), self.mic_rate, self.target_sample_rate, False
        )
        loop = resample_to_mono(
            self._take_frames("loopback_frames", self.loopback_channels),
            self.loopback_rate,
            self.target_sample_rate,
            True,
        )

        # Pad to equal length; Left = Mic, Right = Loopback
        total = max(len(mic), len(loop), int((self.end_time - self.start_time) * self.target_sample_rate))
        stereo = np.zeros((total, 2), dtype=np.int16)
        stereo[: len(mic), 0] = mic
        stereo[: len(loop), 1] = loop

        with wave.open(output_filepath, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.target_sample_rate)
            wf.writeframes(stereo.tobytes())

        # Optional MP3 compression for about 10x faster uploads
        return self.compress_to_mp3(output_filepath) if compress else output_filepath

    def stop(self, custom_filename=None, compress=True):
        """Stops recording and writes the audio files in one step (used by the CLI)."""
        if not self.stop_capture():
            return None
        return self.save(compress=compress, filename=custom_filename)

    def cancel(self):
        """Cancels recording immediately and releases all hardware resources."""
        self.is_recording = False
        self._release_streams()
        self.mic_frames = []
        self.loopback_frames = []
        self.mic_level = 0.0
        self.loopback_level = 0.0

    @staticmethod
    def compress_to_mp3(wav_filepath, bitrate="96k"):
        """Compresses WAV to MP3 using local ffmpeg (reduces file size by 85-90%)."""
        if not os.path.exists(wav_filepath):
            return wav_filepath
        mp3_filepath = os.path.splitext(wav_filepath)[0] + ".mp3"
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                wav_filepath,
                "-codec:a",
                "libmp3lame",
                "-b:a",
                bitrate,
                "-ac",
                "2",
                mp3_filepath,
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            if os.path.exists(mp3_filepath) and os.path.getsize(mp3_filepath) > 0:
                return mp3_filepath
        except Exception as e:
            logger.warning("MP3 compression skipped, using the WAV file (%s)", e)
        return wav_filepath

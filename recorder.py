"""
Audio recording engine for Windows:
Captures both Microphone (User) and WASAPI Loopback (Speakers/Headphones/Teams)
simultaneously and merges them into a synchronized 2-channel WAV file.
Channel 0 (Left): Microphone (You)
Channel 1 (Right): System Audio (Teams / Other participants)
"""

import os
import subprocess
import threading
import time
import wave
from datetime import datetime

import numpy as np
import pyaudiowpatch as pyaudio

from utils import format_duration


class MeetingRecorder:
    def __init__(self, target_sample_rate=16000, output_dir="recordings"):
        self.target_sample_rate = target_sample_rate
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        self.p = None
        self.is_recording = False
        self.start_time = None
        self.end_time = None

        self.mic_stream = None
        self.loopback_stream = None
        self.mic_frames = []
        self.loopback_frames = []

        self.mic_info = None
        self.loopback_info = None
        self.mic_channels = self.mic_rate = None
        self.loopback_channels = self.loopback_rate = None

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
        """Finds default input (mic) and WASAPI loopback device for default output."""
        p = p_instance if p_instance is not None else pyaudio.PyAudio()
        try:
            default_loopback = MeetingRecorder.find_loopback_device(p)
            default_input = p.get_default_input_device_info()
            if not default_loopback:
                raise RuntimeError("Kein passendes WASAPI Loopback-Gerät für die Standard-Ausgabe gefunden!")
            return default_input, default_loopback
        finally:
            if p_instance is None:
                try:
                    p.terminate()
                except Exception:
                    pass

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

    def start(self):
        """Starts recording asynchronously."""
        if self.is_recording:
            return

        self._release_streams()
        self.p = pyaudio.PyAudio()
        self.mic_info, self.loopback_info = self.find_devices(p_instance=self.p)

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

        threading.Thread(target=self._console_heartbeat, daemon=True).start()

    def _console_heartbeat(self):
        """Prints the recording status to the terminal every 5 seconds."""
        while self.is_recording:
            time.sleep(5)
            if not self.is_recording:
                break
            try:
                mic_pct = int(self.mic_level * 100)
                teams_pct = int(self.loopback_level * 100)
                print(
                    f"🔴 [Aufnahme aktiv] {format_duration(self.get_duration())} | Mic: {mic_pct:2d}% | Teams: {teams_pct:2d}% | (Browser-unabhängig)"
                )
            except Exception:
                pass

    def get_duration(self):
        """Returns elapsed recording duration in seconds."""
        if not self.is_recording or not self.start_time:
            return 0.0
        return time.time() - self.start_time

    def stop(self, custom_filename=None, compress=True):
        """Stops recording, synchronizes audio, and writes stereo WAV/MP3."""
        if not self.is_recording:
            return None

        self.end_time = time.time()
        duration_total = self.end_time - self.start_time
        self.is_recording = False
        self._release_streams()

        # Filename
        if not custom_filename:
            timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output_filepath = os.path.join(self.output_dir, f"meeting_{timestamp_str}.wav")
        else:
            output_filepath = os.path.join(self.output_dir, custom_filename)

        # Mic Data
        if self.mic_frames:
            mic_raw = b"".join(self.mic_frames)
            mic_data = np.frombuffer(mic_raw, dtype=np.int16)
            if self.mic_channels > 1:
                mic_data = mic_data.reshape(-1, self.mic_channels)[:, 0]
        else:
            mic_data = np.zeros(0, dtype=np.int16)

        # Loopback Data
        if self.loopback_frames:
            loop_raw = b"".join(self.loopback_frames)
            loop_data = np.frombuffer(loop_raw, dtype=np.int16)
            if self.loopback_channels > 1:
                loop_data = loop_data.reshape(-1, self.loopback_channels)
                loop_data = (loop_data[:, 0].astype(np.int32) + loop_data[:, 1].astype(np.int32)) // 2
                loop_data = loop_data.astype(np.int16)
        else:
            loop_data = np.zeros(0, dtype=np.int16)

        def resample_to_target(data, orig_sr, target_sr):
            if len(data) == 0:
                return np.zeros(0, dtype=np.int16)
            if orig_sr == target_sr:
                return data
            target_len = int(len(data) * target_sr / orig_sr)
            orig_indices = np.linspace(0, len(data) - 1, len(data))
            target_indices = np.linspace(0, len(data) - 1, target_len)
            return np.interp(target_indices, orig_indices, data).astype(np.int16)

        mic_resampled = resample_to_target(mic_data, self.mic_rate, self.target_sample_rate)
        loop_resampled = resample_to_target(loop_data, self.loopback_rate, self.target_sample_rate)

        # Pad to equal length
        target_total_samples = max(
            len(mic_resampled), len(loop_resampled), int(duration_total * self.target_sample_rate)
        )

        mic_padded = np.zeros(target_total_samples, dtype=np.int16)
        mic_padded[: len(mic_resampled)] = mic_resampled

        loop_padded = np.zeros(target_total_samples, dtype=np.int16)
        loop_padded[: len(loop_resampled)] = loop_resampled

        # Merge to 2-channel stereo (Left = Mic, Right = Loopback)
        stereo = np.column_stack((mic_padded, loop_padded))

        with wave.open(output_filepath, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.target_sample_rate)
            wf.writeframes(stereo.tobytes())

        # Optional MP3-Kompression für 10x schnellere Uploads
        if compress:
            return self.compress_to_mp3(output_filepath)

        return output_filepath

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
                print(
                    f"[recorder] Komprimiert zu MP3: {os.path.basename(mp3_filepath)} ({os.path.getsize(mp3_filepath) // 1024} KB)"
                )
                return mp3_filepath
        except Exception as e:
            print(f"[recorder] Hinweis: FFmpeg-Kompression nicht ausgeführt ({e}). Nutze WAV-Original.")
        return wav_filepath

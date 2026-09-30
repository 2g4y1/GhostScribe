"""
Test recording: Records 5 seconds from both Microphone and Loopback (Speakers/Headphones)
and saves it as a 2-channel stereo WAV file.
Left channel: Microphone (You)
Right channel: Loopback (Teams / Other participants)
"""

import time
import wave

import numpy as np
import pyaudiowpatch as pyaudio

RECORD_SECONDS = 5
OUTPUT_FILENAME = "test_meeting.wav"
TARGET_SAMPLE_RATE = 48000


def main():
    p = pyaudio.PyAudio()

    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        print("Fehler: WASAPI nicht verfügbar.")
        p.terminate()
        return

    # 1. Standard-Mikrofon finden
    default_input = p.get_default_input_device_info()
    mic_index = default_input["index"]
    mic_rate = int(default_input["defaultSampleRate"])
    mic_channels = max(1, min(2, default_input["maxInputChannels"]))
    print(f"Mikrofon gefunden: {default_input['name']} (Index {mic_index}, {mic_rate} Hz, {mic_channels} Kanäle)")

    # 2. Standard-Loopback finden
    default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
    loopback_dev = None
    if not default_speakers.get("isLoopbackDevice", False):
        for loopback in p.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                loopback_dev = loopback
                break
    else:
        loopback_dev = default_speakers

    if not loopback_dev:
        print("Fehler: Kein passendes Loopback-Gerät gefunden.")
        p.terminate()
        return

    loopback_index = loopback_dev["index"]
    loopback_rate = int(loopback_dev["defaultSampleRate"])
    loopback_channels = loopback_dev["maxInputChannels"]
    print(
        f"Loopback gefunden: {loopback_dev['name']} (Index {loopback_index}, {loopback_rate} Hz, {loopback_channels} Kanäle)"
    )

    # Puffer für Audio-Daten
    mic_frames = []
    loopback_frames = []

    def mic_callback(in_data, frame_count, time_info, status):
        mic_frames.append(in_data)
        return (None, pyaudio.paContinue)

    def loopback_callback(in_data, frame_count, time_info, status):
        loopback_frames.append(in_data)
        return (None, pyaudio.paContinue)

    print("\nÖffne Audioströme...")
    mic_stream = p.open(
        format=pyaudio.paInt16,
        channels=mic_channels,
        rate=mic_rate,
        input=True,
        input_device_index=mic_index,
        stream_callback=mic_callback,
    )

    loopback_stream = p.open(
        format=pyaudio.paInt16,
        channels=loopback_channels,
        rate=loopback_rate,
        input=True,
        input_device_index=loopback_index,
        stream_callback=loopback_callback,
    )

    print(f"\n>>> AUFNAHME LÄUFT FÜR {RECORD_SECONDS} SEKUNDEN... Sprich ins Mikrofon und/oder spiele Sound ab! <<<")
    mic_stream.start_stream()
    loopback_stream.start_stream()

    for sec in range(RECORD_SECONDS, 0, -1):
        print(f"Verbleibend: {sec}s...", end="\r", flush=True)
        time.sleep(1)

    print("\nStoppe Aufnahme...")
    mic_stream.stop_stream()
    mic_stream.close()
    loopback_stream.stop_stream()
    loopback_stream.close()
    p.terminate()

    print("Verarbeite Audiodaten...")

    # Konvertiere Mic Frames zu int16 numpy array
    if mic_frames:
        mic_raw = b"".join(mic_frames)
        mic_data = np.frombuffer(mic_raw, dtype=np.int16)
        if mic_channels > 1:
            mic_data = mic_data.reshape(-1, mic_channels)[:, 0]  # Ersten Kanal (Mono) nehmen
    else:
        mic_data = np.zeros(0, dtype=np.int16)

    # Konvertiere Loopback Frames zu int16 numpy array
    if loopback_frames:
        loop_raw = b"".join(loopback_frames)
        loop_data = np.frombuffer(loop_raw, dtype=np.int16)
        if loopback_channels > 1:
            # Bei Stereo-Loopback zu Mono mitteln
            loop_data = loop_data.reshape(-1, loopback_channels)
            loop_data = (loop_data[:, 0].astype(np.int32) + loop_data[:, 1].astype(np.int32)) // 2
            loop_data = loop_data.astype(np.int16)
    else:
        loop_data = np.zeros(0, dtype=np.int16)

    # Resampling auf TARGET_SAMPLE_RATE falls nötig
    def resample(data, orig_sr, target_sr):
        if orig_sr == target_sr or len(data) == 0:
            return data
        target_len = int(len(data) * target_sr / orig_sr)
        orig_indices = np.linspace(0, len(data) - 1, len(data))
        target_indices = np.linspace(0, len(data) - 1, target_len)
        return np.interp(target_indices, orig_indices, data).astype(np.int16)

    mic_resampled = resample(mic_data, mic_rate, TARGET_SAMPLE_RATE)
    loop_resampled = resample(loop_data, loopback_rate, TARGET_SAMPLE_RATE)

    # Längen angleichen
    max_len = max(len(mic_resampled), len(loop_resampled))
    if max_len == 0:
        print("Keine Audiodaten aufgezeichnet!")
        return

    mic_padded = np.zeros(max_len, dtype=np.int16)
    mic_padded[: len(mic_resampled)] = mic_resampled

    loop_padded = np.zeros(max_len, dtype=np.int16)
    loop_padded[: len(loop_resampled)] = loop_resampled

    # Zu 2-Kanal Stereo zusammensetzen: Kanal 0 = Mic (Ich), Kanal 1 = Loopback (Teams)
    stereo = np.column_stack((mic_padded, loop_padded))

    with wave.open(OUTPUT_FILENAME, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(TARGET_SAMPLE_RATE)
        wf.writeframes(stereo.tobytes())

    print(f"Fertig! Aufnahme erfolgreich gespeichert als: {OUTPUT_FILENAME}")
    print(f"Dauer: {max_len / TARGET_SAMPLE_RATE:.2f} Sekunden")
    print(f"Max Pegel Mikrofon: {np.max(np.abs(mic_padded))}")
    print(f"Max Pegel Loopback: {np.max(np.abs(loop_padded))}")


if __name__ == "__main__":
    main()

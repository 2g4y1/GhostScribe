"""
Script to list all audio input devices and WASAPI loopback devices on Windows.
"""

import sys

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("pyaudiowpatch is not installed yet.")
    sys.exit(1)


def main():
    p = pyaudio.PyAudio()

    print("=" * 60)
    print("AUDIO GERÄTE ERKENNUNG (Windows WASAPI)")
    print("=" * 60)

    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        print(f"WASAPI Host API gefunden (Index {wasapi_info['index']})")
    except OSError:
        print("WASAPI Host API nicht gefunden!")
        p.terminate()
        return

    # Standard-Geräte
    try:
        default_input = p.get_default_input_device_info()
        print("\n[Standard-Mikrofon]")
        print(f"  Index: {default_input['index']}")
        print(f"  Name:  {default_input['name']}")
        print(f"  Samplerate: {int(default_input['defaultSampleRate'])} Hz")
        print(f"  Kanäle: {default_input['maxInputChannels']}")
    except Exception as e:
        print(f"Kein Standard-Mikrofon gefunden: {e}")

    try:
        default_output = p.get_default_output_device_info()
        print("\n[Standard-Ausgabe (Lautsprecher/Kopfhörer)]")
        print(f"  Index: {default_output['index']}")
        print(f"  Name:  {default_output['name']}")
        print(f"  Samplerate: {int(default_output['defaultSampleRate'])} Hz")
    except Exception as e:
        print(f"Kein Standard-Ausgabegerät gefunden: {e}")

    # Standard Loopback
    try:
        default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        default_loopback = None
        if not default_speakers.get("isLoopbackDevice", False):
            for loopback in p.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    default_loopback = loopback
                    break
        else:
            default_loopback = default_speakers

        if default_loopback:
            print("\n[WASAPI Loopback für Standard-Ausgabe (Teams-Ton)]")
            print(f"  Index: {default_loopback['index']}")
            print(f"  Name:  {default_loopback['name']}")
            print(f"  Samplerate: {int(default_loopback['defaultSampleRate'])} Hz")
            print(f"  Kanäle: {default_loopback['maxInputChannels']}")
        else:
            print("\nKein passendes Loopback-Gerät für Standard-Ausgabe gefunden!")
    except Exception as e:
        print(f"Fehler bei Loopback-Erkennung: {e}")

    print("\n" + "=" * 60)
    print("ALLE VERFÜGBAREN LOOPBACK-GERÄTE:")
    print("=" * 60)
    for loopback in p.get_loopback_device_info_generator():
        print(f"- Index {loopback['index']:2d}: {loopback['name']} ({int(loopback['defaultSampleRate'])} Hz)")

    p.terminate()


if __name__ == "__main__":
    main()

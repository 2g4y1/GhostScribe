"""
Interactive terminal version of GhostScribe (python -m ghostscribe --cli).
"""

import contextlib
import os

from ghostscribe import keys
from ghostscribe.analyzer import MeetingAnalyzer, default_ai_act_mode
from ghostscribe.i18n import translate
from ghostscribe.recorder import MeetingRecorder
from ghostscribe.utils import BANNER, format_duration, open_file, print_banner, update_env_file
from ghostscribe.voices import configured_workers, recognition_enabled

STOP_KEYS = ("\r", "\n", "q", " ")


def level_bar(level, width=15):
    filled = int(level * width)
    return "█" * filled + "░" * (width - filled)


def print_step(key, **params):
    print(f"   → {translate(key, **params)}")


def record(recorder: MeetingRecorder) -> None:
    """Shows the levels until Enter, Q or Space (or Ctrl+C) stops the recording."""
    with keys.reading_keys() if keys.supported() else contextlib.nullcontext():
        try:
            while recorder.is_recording:
                levels = translate(
                    "cli.levels",
                    duration=format_duration(recorder.get_duration()),
                    mic=level_bar(recorder.mic_level),
                    playback=level_bar(recorder.loopback_level),
                )
                print(levels, end="\r", flush=True)
                if keys.supported() and keys.wait_for_key(0.15) in STOP_KEYS:
                    break
        except KeyboardInterrupt:
            pass


def main():
    print_banner(BANNER)

    recorder = MeetingRecorder()
    try:
        mic, system = recorder.default_devices()
    except Exception as e:
        print(translate("cli.device_error", error=e))
        return
    print(translate("cli.microphone", name=mic.name))
    print(translate("cli.system_audio", name=system.name))

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n" + translate("cli.no_api_key"))
        api_input = input("   " + translate("cli.ask_api_key")).strip()
        if api_input:
            api_key = api_input
            update_env_file({"GEMINI_API_KEY": api_key})
            print("   " + translate("cli.api_key_saved"))

    print("\n" + "-" * 68)
    title = input(translate("cli.ask_title")).strip()
    input("\n" + translate("cli.press_enter_to_start"))

    try:
        recorder.start()
    except Exception as e:
        print(translate("cli.device_error", error=e))
        return
    print("\n" + translate("cli.recording"))
    record(recorder)

    print("\n\n" + translate("cli.stopping"))
    audio_path = recorder.stop()
    print(translate("cli.audio_saved", path=audio_path))

    if not api_key or not audio_path:
        print("\n" + translate("cli.skip_analysis"))
        return

    print("\n" + translate("cli.starting_analysis"))
    try:
        result = MeetingAnalyzer(api_key=api_key).analyze_meeting(
            audio_filepath=audio_path,
            meeting_title=title,
            on_status_update=print_step,
            ai_act_mode=default_ai_act_mode(),
            voice_recognition=recognition_enabled(),
            voice_workers=configured_workers(),
        )
    except Exception as e:
        print("\n" + translate("cli.analysis_failed", error=e))
        return

    print_banner(translate("cli.done", path=result["markdown_file"]))
    open_file(result["markdown_file"])  # in the default editor

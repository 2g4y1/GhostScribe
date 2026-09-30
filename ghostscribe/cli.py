"""
Interactive terminal version of GhostScribe (python -m ghostscribe --cli).
"""

import contextlib
import os
import time

from ghostscribe import edition, keys
from ghostscribe.analyzer import MeetingAnalyzer, default_ai_act_mode
from ghostscribe.i18n import translate
from ghostscribe.recorder import MeetingRecorder
from ghostscribe.utils import BANNER, format_duration, open_file, print_banner, update_env_file
from ghostscribe.voices import configured_workers, recognition_enabled

STOP_KEYS = ("\r", "\n", "q", " ")
PAUSE_KEY = "p"


def level_bar(level, width=15):
    filled = int(level * width)
    return "█" * filled + "░" * (width - filled)


def print_step(key, **params):
    print(f"   → {translate(key, **params)}")


def status_line(recorder: MeetingRecorder) -> str:
    duration = format_duration(recorder.get_duration())
    if recorder.paused:
        return translate("cli.paused", duration=duration)
    return translate(
        "cli.levels", duration=duration, mic=level_bar(recorder.mic_level), playback=level_bar(recorder.loopback_level)
    )


def record(recorder: MeetingRecorder) -> None:
    """Shows the levels until Enter, Q or Space (or Ctrl+C) stops the recording; P pauses and resumes it."""
    width = 0  # of the longest line so far: a shorter one overwrites all of it
    with keys.reading_keys() if keys.supported() else contextlib.nullcontext():
        try:
            while recorder.is_recording:
                line = status_line(recorder)
                width = max(width, len(line))
                print(line.ljust(width), end="\r", flush=True)
                if not keys.supported():
                    time.sleep(0.15)
                    continue
                key = keys.wait_for_key(0.15)
                if key in STOP_KEYS:
                    break
                if key == PAUSE_KEY and not recorder.resume():
                    recorder.pause()
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
    if edition.is_company() and input(translate("cli.ask_consent")).strip().lower() not in ("j", "ja", "y", "yes"):
        print(translate("cli.no_consent"))
        return
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
            cuts=[format_duration(cut) for cut in recorder.cuts],
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

"""
Interactive terminal version of GhostScribe (python -m ghostscribe --cli).
"""

import msvcrt
import os
import time

from ghostscribe.analyzer import MeetingAnalyzer
from ghostscribe.i18n import translate
from ghostscribe.recorder import MeetingRecorder
from ghostscribe.utils import BANNER, format_duration, print_banner, update_env_file


def level_bar(level, width=15):
    filled = int(level * width)
    return "█" * filled + "░" * (width - filled)


def print_step(key, **params):
    print(f"   → {translate(key, **params)}")


def main():
    print_banner(BANNER)

    recorder = MeetingRecorder()
    try:
        mic_info, loopback_info = recorder.find_devices()
    except Exception as e:
        print(translate("cli.device_error", error=e))
        return
    print(translate("cli.microphone", name=mic_info["name"]))
    print(translate("cli.system_audio", name=loopback_info["name"]))

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

    recorder.start()
    print("\n" + translate("cli.recording"))

    try:
        while recorder.is_recording:
            print(
                f"⏱️  {format_duration(recorder.get_duration())} | Mic: [{level_bar(recorder.mic_level)}] | Teams: [{level_bar(recorder.loopback_level)}]",
                end="\r",
                flush=True,
            )
            time.sleep(0.15)
            # Check for key press on Windows without blocking
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key in [b"\r", b"\n", b"q", b" "]:
                    break
    except KeyboardInterrupt:
        pass

    print("\n\n" + translate("cli.stopping"))
    audio_path = recorder.stop()
    print(translate("cli.audio_saved", path=audio_path))

    if not api_key:
        print("\n" + translate("cli.skip_analysis"))
        return

    print("\n" + translate("cli.starting_analysis"))
    try:
        result = MeetingAnalyzer(api_key=api_key).analyze_meeting(
            audio_filepath=audio_path, meeting_title=title, on_status_update=print_step
        )
    except Exception as e:
        print("\n" + translate("cli.analysis_failed", error=e))
        return

    print_banner(translate("cli.done", path=result["markdown_file"]))
    # Open the Markdown file in the default editor
    try:
        os.startfile(result["markdown_file"])
    except Exception:
        pass

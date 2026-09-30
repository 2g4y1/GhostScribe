"""
Interactive CLI for GhostScribe Meeting Recorder
"""

import os
import time

from dotenv import load_dotenv

from analyzer import MeetingAnalyzer
from recorder import MeetingRecorder

load_dotenv()


def main():
    print("\n" + "=" * 60)
    print("🎙️  GHOSTSCRIBE - BOT-FREE AI MEETING RECORDER & ANALYZER (Gemini)")
    print("=" * 60)

    recorder = MeetingRecorder()
    try:
        mic_info, loopback_info = recorder.find_devices()
        print(f"✅ Mikrofon (Ich):     {mic_info['name']}")
        print(f"✅ Teams-Ton (Andere): {loopback_info['name']}")
    except Exception as e:
        print(f"❌ Fehler bei der Geräte-Erkennung: {e}")
        return

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n⚠️  HINWEIS: Kein GEMINI_API_KEY in .env gefunden.")
        print("   Du kannst trotzdem aufnehmen, aber für die Analyse wird der Key benötigt.")
        api_input = input("   Möchtest du deinen API-Key jetzt eingeben? (Enter zum Überspringen): ").strip()
        if api_input:
            api_key = api_input
            with open(".env", "a", encoding="utf-8") as f:
                f.write(f"\nGEMINI_API_KEY={api_key}\n")
            print("   Key in .env gespeichert!")

    print("\n" + "-" * 60)
    title = input("Meeting-Thema / Titel (optional, Enter für Zeitstempel): ").strip()
    input("\n▶️  Drücke [ENTER], um die AUFNAHME ZU STARTEN...")

    recorder.start()
    print("\n🔴 AUFNAHME LÄUFT! (Drücke [ENTER], um die Aufnahme zu beenden)")

    try:
        while recorder.is_recording:
            dur = int(recorder.get_duration())
            mins, secs = divmod(dur, 60)
            mic_bars = int(recorder.mic_level * 15)
            loop_bars = int(recorder.loopback_level * 15)
            mic_vis = "█" * mic_bars + "░" * (15 - mic_bars)
            loop_vis = "█" * loop_bars + "░" * (15 - loop_bars)

            print(f"⏱️  {mins:02d}:{secs:02d} | Mic: [{mic_vis}] | Teams: [{loop_vis}]", end="\r", flush=True)
            time.sleep(0.15)
            # Check for key press on Windows without blocking
            import msvcrt

            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key in [b"\r", b"\n", b"q", b" "]:
                    break
    except KeyboardInterrupt:
        pass

    print("\n\n⏹️  Stoppe Aufnahme und synchronisiere Audio...")
    wav_path = recorder.stop()
    print(f"✅ Audio gespeichert unter: {wav_path}")

    if not api_key:
        print("\n⚠️  Kein API-Key vorhanden. Analyse übersprungen. Die Audiodatei liegt bereit!")
        return

    print("\n🤖 Starte KI-Analyse mit Gemini...")
    analyzer = MeetingAnalyzer(api_key=api_key)

    try:
        result = analyzer.analyze_meeting(
            audio_filepath=wav_path, meeting_title=title, on_status_update=lambda msg: print(f"   -> {msg}")
        )
        print("\n" + "=" * 60)
        print("🎉 FERTIG! Besprechungsprotokoll erstellt:")
        print(f"📄 Datei: {result['markdown_file']}")
        print("=" * 60)

        # Öffne die Markdown-Datei im Standard-Editor
        try:
            os.startfile(result["markdown_file"])
        except Exception:
            pass

    except Exception as e:
        print(f"\n❌ Fehler bei der Gemini-Analyse: {e}")


if __name__ == "__main__":
    main()

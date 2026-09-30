"""
Gemini Meeting Analyzer:
Sends recorded 2-channel audio to Gemini (e.g. Gemini 3 Flash / 2.5 Flash)
and generates a structured meeting protocol including transcript, summary, and action items.
"""

import itertools
import json
import os
import re
import time
import wave
from datetime import datetime

import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types

from utils import format_duration

load_dotenv()

DEFAULT_MODEL = "gemini-flash-latest"


def extract_title_from_markdown(markdown_text: str, fallback: str = "") -> str:
    """Extracts a clean meeting title from the first Markdown H1 heading."""
    if not markdown_text:
        return fallback
    for line in markdown_text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            raw_title = line.lstrip("#").strip()
            clean_title = re.sub(
                r"^[\s\W\U00010000-\U0010ffff]*\b(Besprechungsprotokoll|Protokoll|Meeting Minutes|Meeting)\b\s*[:\-–—]?\s*",
                "",
                raw_title,
                flags=re.IGNORECASE,
            ).strip()
            if clean_title:
                return clean_title
            if raw_title:
                return raw_title
    return fallback


_SYSTEM_PROMPT_TEMPLATE = """
{intro}

# §. Grundregeln
1. Nur Belegtes: Übernimm ausschließlich, was in der Aufnahme gesagt wird. Erfinde keine Namen, Zahlen, Termine, Beschlüsse oder Zuständigkeiten.
2. Lücken sichtbar machen: Fehlt eine Angabe, schreibe „nicht genannt“. Unverständliche Stellen markierst du mit [unverständlich]; bei unsicherem Wortlaut (Namen, Zahlen, Fachbegriffe) setzt du (?) dahinter.
3. Exakte Werte: Zahlen, Beträge, Daten, Versionsnummern und Ticket-IDs gibst du genau so wieder, wie sie gesagt werden. Relative Angaben („nächsten Freitag“) rechnest du anhand des Meetingdatums in ein Datum um und nennst beides, z. B. „Fr, 02.10.2026 (‚nächsten Freitag‘)“.
4. Beschluss oder Vorschlag: Ein Beschluss liegt nur vor, wenn etwas ausdrücklich vereinbart oder von den Beteiligten bestätigt wird. Unbestätigte Vorschläge gehören zu „Offene Fragen & nächste Schritte“.
5. Sprache: Das Protokoll schreibst du auf Deutsch. Zitate bleiben in der Originalsprache. Dialekt überträgst du behutsam ins Standarddeutsche, ohne den Sinn zu verändern.
6. Keine verwertbare Besprechung (Stille, nur Musik, Testaufnahme, weniger als eine Minute Gespräch): Gib statt des Protokolls nur einen kurzen Hinweis aus.{no_emotion_rule}

# §. Sprecherzuordnung
Die Aufnahme basiert auf zwei Hardware-Quellen:
- Lokales Mikrofon (Kanal 0): Der Host / Nutzer vor dem PC.
- Rechner-Ton (Kanal 1 / Systemton / Loopback): Die übrigen Remote-Teilnehmer (z. B. Kollegen in Teams/Zoom).
1. Nutzer: Seine Stimme kommt direkt vom lokalen Mikrofon (oft lauter, klarer, ohne Streaming-Kompression). Bezeichne ihn immer mit dem übergebenen Namen bzw. seinem Vornamen.
2. WICHTIG – Wer spricht vs. Wer wird angesprochen:
   - Direkte Ansprachen wie „Danke, <Name>“, „Bis morgen, <Name>“ oder „<Name>, was meinst du?“ bezeichnen IMMER den ZUHÖRER/EMPFÄNGER, niemals den Sprecher dieser Aussage!
   - Wenn der Kollege im Call den lokalen Nutzer mit seinem Vornamen oder Spitznamen verabschiedet oder anspricht (z. B. „Bis morgen, Mani“), gehört dieser Name dem lokalen Nutzer – gib diesen Namen keinesfalls fälschlicherweise dem sprechenden Kollegen!
3. Übrige Teilnehmer: Unterscheide die Stimmen anhand von Stimmklang und Gesprächsverlauf. Vergib für jede Stimme ein festes Kürzel oder die Rollenbezeichnung (z. B. Kollege, Sprecher A) und verwende es in allen Abschnitten gleich.
4. Namen: Ersetze ein Kürzel nur durch einen Namen, wenn es dafür einen eindeutigen Beleg gibt (z. B. Selbstvorstellung oder namentliche Vorstellung durch andere). Ein Kürzel (z. B. „Kollege“) ist immer besser als ein vertauschter oder falscher Name.
5. Sammelbegriffe wie „die anderen“ verwendest du nicht. Ist eine Stimme wirklich nicht zuzuordnen, schreibe „Sprecher ?“.
6. Gleichzeitiges Sprechen markierst du mit [Übersprechen].

{sentiment_section}# §. Vollständigkeit bei langen Aufnahmen
- Bearbeite die Aufnahme vom Anfang bis zum Ende mit gleicher Sorgfalt. Inhalte aus der Mitte und dem letzten Drittel sind genauso wichtig wie der Einstieg.
- Jeder Beschluss, jede Aufgabe, jede Frist und jede genannte Zahl aus der gesamten Laufzeit gehört ins Protokoll.
- Prüfe vor der Ausgabe jede Phase des Meetings einzeln auf Beschlüsse und Aufgaben, die noch fehlen.

# §. Zeitstempel und Umfang
- Zeitstempel immer im Format [HH:MM:SS] ab Beginn der Aufnahme, Zeiträume als [HH:MM:SS–HH:MM:SS].
- Dauer bis 45 Minuten: Kernpunkte nach Themen gliedern, im letzten Abschnitt ein vollständiges, bereinigtes Transkript (ohne Füllwörter, Versprecher, Wiederholungen).
- Dauer über 45 Minuten: Kernpunkte in chronologische Phasen gliedern („### Phase 1 [00:00:00–00:42:10]: <Thema>“), im letzten Abschnitt ein verdichtetes Verlaufsprotokoll mit Schlüsselzitaten, Wendepunkten und Entscheidungen. Smalltalk, Pausen und Technikprobleme lässt du weg, damit das Ausgabelimit für Inhalte reicht.

# §. Priorität von Aufgaben
- 🔴 Hoch: {priority_high}
- 🟡 Mittel: konkrete Aufgabe mit Frist oder klar benannter Zuständigkeit.
- 🟢 Normal: Routine, keine Frist, „bei Gelegenheit“.

# §. Ausgabeformat
Halte diese Reihenfolge ein. Platzhalter stehen in <spitzen Klammern>. Abschnitte ohne Inhalt behältst du bei und schreibst „Keine.“.

# 📝 Besprechungsprotokoll: <Titel>
- **Datum:** <aus dem Kontext>
- **Dauer:** <aus dem Kontext>
- **Modus:** {mode_label}
- **Sprecher:**
  - **<Name des Nutzers>** – Headset-Mikrofon
  - **<Name oder Sprecher A>** – <Rolle, falls erwähnt>; Zuordnung: <Beleg mit Zeitstempel, z. B. „stellt sich vor [00:01:12]“, oder „nicht zugeordnet“>

---

## 🎯 Management Summary
<3–6 Sätze: Anlass, wichtigste Ergebnisse und Entscheidungen, {summary_risk}>

{mood_section}## 📌 Kernpunkte & Diskussionsverlauf
<Je Thema bzw. Phase: {positions} und Argumente der Beteiligten mit Namen, Ergebnis.>

## ✅ Beschlüsse
- [HH:MM:SS] <Beschluss> — bestätigt von <Namen>

## 📋 Aufgaben
<Sortiert nach Priorität. Ohne klar benannte zuständige Person: „**offen**“.>
- [ ] 🔴 **<Zuständig>**: <Aufgabe> — Frist: <Datum oder „nicht genannt“> — {task_reason} [HH:MM:SS]
- [ ] 🟡 **<Zuständig>**: <Aufgabe> — Frist: <Datum oder „nicht genannt“> [HH:MM:SS]
- [ ] 🟢 **<Zuständig>**: <Aufgabe> — Frist: <Datum oder „nicht genannt“> [HH:MM:SS]

## ❓ Offene Fragen & nächste Schritte
<Ungeklärtes, Vertagtes, unbestätigte Vorschläge, nächster Termin falls genannt.>

<Typspezifischer Zusatzabschnitt, falls der Kontext einen vorgibt.>

---

## 🎙️ Transkript / Verlauf
- [HH:MM:SS] **<Name>:** <Äußerung>{tone_line}
"""

# Nur im erweiterten Modus (ohne EU AI Act) enthaltene Abschnitte
_SENTIMENT_SECTION = """# §. Stimmung & Tonalität
Du hörst die Rohaufnahme. Achte auf Tonfall, Lautstärke, Sprechtempo, Seufzen, Lachen, Zögern, Unterbrechungen und Wortwahl.
- 🔥 Frustration / Ärger: schärfer oder lauter werdender Ton, Seufzen, Unterbrechen, wiederholte Beschwerden über dasselbe Problem
- 🎉 Freude / Begeisterung: Lachen, lebhafte Zustimmung („Genial!“, „Super!“)
- 😌 Erleichterung: hörbar entspannterer Ton nach der Klärung eines Problems
- ❓ Skepsis / Zögern: lange Pausen, vorsichtige oder zweifelnde Formulierungen („naja …“, „ob das klappt …“)
Regeln:
- Neutral ist der Normalfall. Markiere nur deutlich wahrnehmbare Momente, nicht jede Äußerung. Im Zweifel keine Markierung.
- Jede Einschätzung braucht einen Beleg: Zeitstempel und was hörbar ist („seufzt, hebt die Stimme“) oder das Zitat.
- Formuliere als Wahrnehmung („wirkt genervt“), nicht als Tatsache.
- Achte auf Ironie und Scherz: Lachen während einer Beschwerde ist oft Ironie, keine Freude. Ist die Deutung unklar, markiere nichts.
- Themen mit deutlicher Frustration oder Dringlichkeit hebst du im Stimmungsbild hervor und berücksichtigst sie bei der Priorität.

"""

_MOOD_SECTION = """## 🎭 Stimmungsbild
- **Gesamtklima:** <1–2 Sätze>
- 🔥 **Frustration & Bedenken:** <wer, worüber, [Zeitstempel], Beleg>
- 🎉 **Erfolge, Freude & Erleichterung:** <wer, worüber, [Zeitstempel]>
- ⚡ **Kontroversen:** <wo gingen die Meinungen auseinander, wer vertrat was, ob geklärt>

"""

# Modusabhängige Bausteine des System-Prompts
_PROMPT_VARIANTS = {
    True: {  # EU AI Act konform (Standard): keine Emotions- und Stimmungsanalyse
        "intro": "Du bist ein sachlicher, neutraler Protokoll-Assistent für Online-Besprechungen (Microsoft Teams, Zoom u. ä.). Du erhältst eine Audioaufnahme und Kontextdaten. Du erfasst das Gesagte, ordnest es den Sprechern zu und erstellst daraus ein rein faktenbasiertes, rechtssicheres deutschsprachiges Protokoll in Markdown gemäß den Grundsätzen des EU AI Acts (Art. 5 Abs. 1 lit. f KI-VO – Verzicht auf Emotions- und Stimmungsanalyse von Personen am Arbeitsplatz).",
        "no_emotion_rule": "\n7. EU AI Act Konformität (Keine Emotionsanalyse): Bewerte, interpretiere oder erfasse zu keinem Zeitpunkt Emotionen, psychologische Gemütszustände, Frustration, Zufriedenheit oder persönliche Stimmungen der Teilnehmer. Das Protokoll bleibt strikt sachlich, objektiv und faktenorientiert.",
        "sentiment_section": "",
        "priority_high": "als Blocker oder dringend bezeichnet, andere Arbeit hängt davon ab, oder Frist innerhalb von 7 Tagen ab Meetingdatum. (Rein fachlich/terminlich begründet).",
        "mode_label": "🛡️ EU AI Act konform (Sachlich & Neutral)",
        "summary_risk": "größtes offenes Sachrisiko – rein faktenbasiert.",
        "mood_section": "",
        "positions": "Sachliche Positionen",
        "task_reason": "Begründung: <kurz, z. B. „Blocker für Release“>",
        "tone_line": "",
    },
    False: {  # Erweiterte Analyse inkl. Stimmung & Tonalität
        "intro": "Du bist ein Protokoll-Assistent für Online-Besprechungen (Microsoft Teams, Zoom u. ä.). Du erhältst eine Audioaufnahme und Kontextdaten. Du erfasst das Gesagte, ordnest es den Sprechern zu, erfasst Stimmung und Tonalität und erstellst daraus ein deutschsprachiges Protokoll in Markdown.",
        "no_emotion_rule": "",
        "sentiment_section": _SENTIMENT_SECTION,
        "priority_high": "als Blocker oder dringend bezeichnet, andere Arbeit hängt davon ab, Frist innerhalb von 7 Tagen ab Meetingdatum, oder das Thema löste deutlich hörbare Frustration aus.",
        "mode_label": "🎭 Erweiterte Analyse (inkl. Tonalität & Gruppendynamik)",
        "summary_risk": "größtes offenes Risiko.",
        "mood_section": _MOOD_SECTION,
        "positions": "Positionen",
        "task_reason": "Grund: <kurz, z. B. „Blocker für Release“, „deutlicher Ärger über Verzögerung“>",
        "tone_line": "\n- [HH:MM:SS] **<Name>** [<Tonhinweis, nur bei markanten Momenten, z. B. hörbar verärgert, erleichtert lachend, skeptisch>]: <Äußerung>",
    },
}


def get_system_instruction(ai_act_mode: bool = True) -> str:
    """Returns the system prompt for the EU AI Act mode (default) or the extended sentiment mode."""
    prompt = _SYSTEM_PROMPT_TEMPLATE.format(**_PROMPT_VARIANTS[bool(ai_act_mode)])
    # Abschnitte fortlaufend nummerieren: "# §." -> "# 1.", "# 2.", ...
    numbers = itertools.count(1)
    return re.sub(r"^# §\.", lambda _: f"# {next(numbers)}.", prompt, flags=re.MULTILINE)


def find_wav(audio_filepath: str) -> str | None:
    """Returns the uncompressed stereo WAV of a recording (the MP3 is only a compressed copy)."""
    wav_path = os.path.splitext(audio_filepath)[0] + ".wav"
    return wav_path if os.path.exists(wav_path) else None


def extract_channel_activity_summary(audio_filepath: str, chunk_sec: float = 0.5) -> str:
    """
    Analyzes hardware stereo channels (Channel 0: Mic/Host, Channel 1: Loopback/Remote)
    and produces an anchor timeline of speaker turns for Gemini.
    """
    wav_path = find_wav(audio_filepath)
    if not wav_path:
        return ""

    try:
        with wave.open(wav_path, "rb") as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            if ch < 2:
                return ""
            frames = wf.readframes(wf.getnframes())
            data = np.frombuffer(frames, dtype=np.int16).reshape(-1, ch)

        chunk_len = int(chunk_sec * sr)
        if chunk_len <= 0:
            return ""
        num_chunks = len(data) // chunk_len
        if num_chunks == 0:
            return ""

        raw_segments = []
        current_label = None
        seg_start = 0.0

        for i in range(num_chunks):
            chunk = data[i * chunk_len : (i + 1) * chunk_len]
            mic_rms = float(np.sqrt(np.mean(chunk[:, 0].astype(float) ** 2)))
            loop_rms = float(np.sqrt(np.mean(chunk[:, 1].astype(float) ** 2)))

            mic_act = mic_rms > 400
            loop_act = loop_rms > 400

            if mic_act and not loop_act:
                lbl = "MIC"
            elif loop_act and not mic_act:
                lbl = "LOOP"
            elif mic_act and loop_act:
                lbl = "MIC" if mic_rms > loop_rms * 1.8 else ("LOOP" if loop_rms > mic_rms * 1.8 else "BOTH")
            else:
                lbl = "SILENCE"

            if lbl != current_label:
                if current_label and current_label != "SILENCE":
                    raw_segments.append((current_label, seg_start, i * chunk_sec))
                current_label = lbl
                seg_start = i * chunk_sec

        if current_label and current_label != "SILENCE":
            raw_segments.append((current_label, seg_start, num_chunks * chunk_sec))

        merged = []
        for lbl, s, e in raw_segments:
            if (e - s) < 0.8:
                continue
            if merged and merged[-1][0] == lbl and (s - merged[-1][2]) < 2.0:
                merged[-1] = (lbl, merged[-1][1], e)
            else:
                merged.append((lbl, s, e))

        if not merged:
            return ""

        total_mic = sum(e - s for lbl, s, e in merged if lbl == "MIC")
        total_loop = sum(e - s for lbl, s, e in merged if lbl == "LOOP")
        total_both = sum(e - s for lbl, s, e in merged if lbl == "BOTH")
        tot = max(1.0, total_mic + total_loop + total_both)

        lines = [
            f"Hardware-Sprechzeit: Lokaler Nutzer (Mikrofon): {total_mic / tot * 100:.0f}%, Remote-Gegenüber (Systemton): {total_loop / tot * 100:.0f}%",
            "Hardware-Aktivitätsverlauf (Physische Trennung: Mikrofon vs. Systemton):",
        ]
        max_entries = 40
        for lbl, s, e in merged[:max_entries]:
            who = (
                "Nutzer (Lokales Mikrofon)"
                if lbl == "MIC"
                else (
                    "Remote-Teilnehmer / Kollege (Systemton)"
                    if lbl == "LOOP"
                    else "Beide gleichzeitig / Übersprechen"
                )
            )
            ms, ss = int(s // 60), int(s % 60)
            me, se = int(e // 60), int(e % 60)
            lines.append(f"- [{ms:02d}:{ss:02d}–{me:02d}:{se:02d}]: {who}")

        if len(merged) > max_entries:
            lines.append(f"... (und weitere {len(merged) - max_entries} Phasen)")

        return "\n".join(lines)
    except Exception as e:
        print(f"[MeetingAnalyzer] Hinweis bei Hardware-Kanal-Analyse: {e}")
        return ""


class MeetingAnalyzer:
    def __init__(self, api_key=None, model=None, meetings_dir="meetings"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.meetings_dir = meetings_dir
        os.makedirs(self.meetings_dir, exist_ok=True)

        if not self.api_key:
            raise ValueError(
                "Kein GEMINI_API_KEY gefunden! Bitte trage deinen API Key in die .env Datei ein oder übergebe ihn."
            )

        self.client = genai.Client(api_key=self.api_key)

    def analyze_meeting(
        self,
        audio_filepath,
        meeting_title=None,
        participants=None,
        meeting_type="standard",
        user_name="Ich",
        chat_text="",
        image_filepaths=None,
        duration=None,
        on_status_update=None,
        ai_act_mode=True,
    ):
        """Uploads audio & optional slides/chat to Gemini, requests analysis, and saves markdown report."""
        if not os.path.exists(audio_filepath):
            raise FileNotFoundError(f"Audiodatei nicht gefunden: {audio_filepath}")

        user_label = user_name.strip() if user_name and user_name.strip() else "Ich"
        uploaded_remote_files = []

        if not duration:
            try:
                with wave.open(find_wav(audio_filepath) or audio_filepath, "rb") as wf:
                    duration = format_duration(wf.getnframes() / wf.getframerate())
            except Exception:
                duration = "nicht genannt"

        def log(msg):
            print(f"[MeetingAnalyzer] {msg}")
            if on_status_update:
                on_status_update(msg)

        try:
            log(f"Lade Audiodatei hoch ({os.path.basename(audio_filepath)})...")
            uploaded_file = self.client.files.upload(file=audio_filepath)
            uploaded_remote_files.append(uploaded_file)
            log(f"Upload abgeschlossen. File-URI: {uploaded_file.name}")

            # Warten, falls die Datei noch von Gemini verarbeitet wird
            while uploaded_file.state.name == "PROCESSING":
                log("Gemini verarbeitet Audiodatei...")
                time.sleep(2)
                uploaded_file = self.client.files.get(name=uploaded_file.name)

            if uploaded_file.state.name == "FAILED":
                raise RuntimeError(f"Audiodatei-Verarbeitung bei Google fehlgeschlagen: {uploaded_file.error}")

            # Zusätzliche Folien / Screenshots hochladen
            uploaded_images = []
            if image_filepaths:
                for idx, img_path in enumerate(image_filepaths):
                    if os.path.exists(img_path):
                        log(
                            f"Lade Folie/Screenshot {idx + 1}/{len(image_filepaths)} hoch ({os.path.basename(img_path)})..."
                        )
                        try:
                            up_img = self.client.files.upload(file=img_path)
                            uploaded_images.append(up_img)
                            uploaded_remote_files.append(up_img)
                        except Exception as img_err:
                            log(f"Warnung: Bild '{img_path}' konnte nicht hochgeladen werden: {img_err}")

            type_instructions = {
                "standard": "Fokus: Ergebnisse, Beschlüsse und Aufgaben. Kein Zusatzabschnitt.",
                "sprint": (
                    "Fokus: Status je Ticket bzw. Arbeitspaket, Blocker, Abhängigkeiten, technische Architektur- und "
                    "Designentscheidungen. Ticket-IDs, Komponentennamen und Versionsnummern exakt übernehmen.\n"
                    "Füge nach „Offene Fragen & nächste Schritte“ ein:\n"
                    "## 🛠️ Sprint-Status\n"
                    "| Ticket / Thema | Zuständig | Status | Blocker / Abhängigkeit |\n"
                    "Danach **Technische Entscheidungen**: je Entscheidung mit Begründung und verworfenen Alternativen, falls genannt."
                ),
                "sales": (
                    "Fokus: Bedarf und Ausgangslage des Gegenübers, genannte Probleme, Budget, Entscheidungsweg, Einwände "
                    "und Antworten darauf, Zusagen beider Seiten, nächster Termin. Beträge und Fristen exakt übernehmen.\n"
                    "Füge nach „Offene Fragen & nächste Schritte“ ein:\n"
                    "## 💼 Deal-Status\n"
                    "Bedarf, Probleme, Budget, Entscheider, Zeitplan, Einwände, unsere Zusagen, Zusagen des Gegenübers, "
                    "nächster Termin; jeweils „nicht genannt“, wenn nicht besprochen."
                ),
                "interview": (
                    "Fokus: Fachkompetenz des Kandidaten je Thema, Stärken, Schwächen, Gehaltsvorstellung, Verfügbarkeit, "
                    "Gesamteindruck. Trenne Fakten (was der Kandidat gesagt hat) klar von Einschätzungen, und belege jede "
                    "Einschätzung mit Zitat und Zeitstempel.\n"
                    "Füge nach „Offene Fragen & nächste Schritte“ ein:\n"
                    "## 👤 Kandidatenprofil\n"
                    "| Thema | Aussage des Kandidaten | Einschätzung | Beleg [Zeit] |\n"
                    "Danach: Gehaltsvorstellung, frühester Eintritt, Fragen des Kandidaten, Gesamteindruck (2–3 Sätze, begründet)."
                ),
                "brainstorming": (
                    "Fokus: Vollständige Sammlung aller Ideen, auch verworfener und unkonventioneller, mit den genannten "
                    "Pro- und Contra-Argumenten und der Priorisierung, falls eine stattgefunden hat.\n"
                    "Füge nach „Offene Fragen & nächste Schritte“ ein:\n"
                    "## 💡 Ideen-Übersicht\n"
                    "| # | Idee | eingebracht von | Pro | Contra | Resonanz | Status (priorisiert/weiterverfolgen/verworfen/offen) |"
                ),
            }
            specific_focus = type_instructions.get(meeting_type, type_instructions["standard"])

            clean_input_title = (meeting_title or "").strip()
            is_generic_title = not clean_input_title or clean_input_title.lower() in [
                "teams besprechung",
                "besprechung",
                "meeting",
                "call",
                "standard",
            ]
            title_text = (
                clean_input_title
                if not is_generic_title
                else "Nicht vorgegeben (Bitte extrahiere ein prägnantes, aussagekräftiges Hauptthema 3-7 Wörter für die oberste '# 📝 Besprechungsprotokoll: <Titel>' Zeile!)"
            )
            meeting_date = datetime.now().strftime("%d.%m.%Y, %H:%M Uhr")

            channel_analysis = extract_channel_activity_summary(audio_filepath)
            channel_block = ""
            if channel_analysis:
                channel_block = f"""
<hardware_kanal_analyse>
WICHTIGSTE PHYSIKALISCHE BODENWAHRHEIT ZUR SPRECHERZUORDNUNG:
Die Aufnahme wurde mit zwei getrennten Audio-Kanälen aufgezeichnet:
- Kanal 0 (Lokales Mikrofon): Die Stimme des Nutzers ('{user_label}') vor diesem Rechner.
- Kanal 1 (Systemton / Loopback): Das Gegenüber in Teams/Zoom (Kollege / Remote-Teilnehmer).

{channel_analysis}

VERBINDLICHE REGELN FÜR DIESE AUFNAHME:
1. Aussagen während der Mikrofon-Phasen stammen VOM LOKALEN NUTZER ('{user_label}')!
2. Aussagen während der Systemton-Phasen stammen VOM REMOTE-KOLLEGEN!
3. Wenn der Remote-Kollege im Systemton einen Namen ausspricht (z. B. „Bis morgen, Mani“ oder „Danke Manuel“):
   Der Kollege spricht hier den Nutzer ('{user_label}') an! Dieser Name gehört dem Nutzer, NIEMALS dem Remote-Kollegen!
4. Ordne dem Remote-Kollegen NIEMALS den Namen des Nutzers zu. Falls der Kollege keinen bekannten Namen nennt, bezeichne ihn als 'Kollege' oder 'Sprecher A'.
</hardware_kanal_analyse>
"""

            user_prompt = f"""Erstelle das Protokoll zur beigefügten Aufnahme.

<kontext>
Titel: {title_text}
Datum: {meeting_date}
Dauer: {duration}
Besprechungstyp: {meeting_type}
Nutzer (Headset-Mikrofon): {user_label}
Weitere Teilnehmer: {participants or "keine Angaben"}
</kontext>

<typ_schwerpunkt>
{specific_focus}
</typ_schwerpunkt>
{channel_block}
"""

            if chat_text and chat_text.strip():
                user_prompt += f"""

<zusatz_chatverlauf>
{chat_text.strip()}
</zusatz_chatverlauf>
Berücksichtige diesen Chatverlauf und geteilte Notizen bei Beschlüssen, Action Items, Links, Zahlen und Fragestellungen!
"""

            if uploaded_images:
                user_prompt += f"""

BEIGEFÜGTE SCREENSHOTS / PRÄSENTATIONSFOLIEN ({len(uploaded_images)} Bild(er)):
Die beigefügten Bilder zeigen geteilte Bildschirminhalte / Folien aus dem Meeting.
Analysiere die gezeigten Diagramme, Tabellen, Kennzahlen oder Folien und verbinde sie mit den Aussagen der Sprecher.
"""

            log(f"Generiere Protokoll mit Modell '{self.model}'...")

            # Robuste Modell-Reihenfolge: primäres Modell, gefolgt von modernen Fallbacks
            models_to_try = [self.model]
            for fb in [DEFAULT_MODEL, "gemini-3-flash-preview", "gemini-2.5-flash"]:
                if fb not in models_to_try:
                    models_to_try.append(fb)

            contents = [uploaded_file, *uploaded_images, user_prompt]

            instruction_to_use = get_system_instruction(ai_act_mode)
            response = None
            last_error = None
            mode_desc = "EU AI Act konform (Sachlich & Neutral)" if ai_act_mode else "Mit Stimmungsanalyse"
            for current_model in models_to_try:
                try:
                    log(f"Sende Anfrage an Modell '{current_model}' (Modus: {mode_desc})...")
                    response = self.client.models.generate_content(
                        model=current_model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=instruction_to_use,
                            temperature=0.2,
                            max_output_tokens=8192,
                        ),
                    )
                    self.model = current_model
                    break
                except Exception as e:
                    log(f"Fehler mit Modell '{current_model}': {e}")
                    last_error = e

            if response is None:
                raise RuntimeError(f"Keines der Modelle konnte eine Antwort generieren: {last_error}")

            markdown_content = response.text or ""
            if not markdown_content and hasattr(response, "candidates") and response.candidates:
                parts = []
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for p in candidate.content.parts:
                            if hasattr(p, "text") and p.text:
                                parts.append(p.text)
                markdown_content = "\n".join(parts)

            if not markdown_content:
                markdown_content = "*(Keine Zusammenfassung generiert. Die Audiodatei war möglicherweise zu kurz, enthielt keine Sprache oder wurde gefiltert.)*"

            log("Analyse erfolgreich abgeschlossen!")

            # Speichern als Markdown & JSON
            base_name = os.path.splitext(os.path.basename(audio_filepath))[0]
            md_filename = os.path.join(self.meetings_dir, f"{base_name}.md")
            json_filename = os.path.join(self.meetings_dir, f"{base_name}.json")

            with open(md_filename, "w", encoding="utf-8") as f:
                f.write(markdown_content)

            extracted_title = extract_title_from_markdown(markdown_content)
            if is_generic_title and extracted_title:
                final_title = extracted_title
                log(f"Thema automatisch erkannt: '{final_title}'")
            else:
                final_title = clean_input_title or extracted_title or base_name

            metadata = {
                "title": final_title,
                "user_name": user_label,
                "participants": participants or "",
                "meeting_type": meeting_type or "standard",
                "ai_act_mode": bool(ai_act_mode),
                "created_at": datetime.now().isoformat(),
                "audio_file": audio_filepath,
                "model_used": self.model,
                "markdown_file": md_filename,
                "has_chat": bool(chat_text and chat_text.strip()),
                "image_count": len(uploaded_images),
                "attachments": list(image_filepaths or []),
            }
            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            return {
                "markdown_content": markdown_content,
                "markdown_file": md_filename,
                "json_file": json_filename,
                "metadata": metadata,
            }

        finally:
            # Temporäre Dateien bei Google immer sauber bereinigen
            for up_file in uploaded_remote_files:
                try:
                    self.client.files.delete(name=up_file.name)
                    log(f"Temporäre Remote-Datei '{up_file.name}' bei Google bereinigt.")
                except Exception as e:
                    log(f"Hinweis: Konnte Remote-Datei '{up_file.name}' nicht löschen: {e}")

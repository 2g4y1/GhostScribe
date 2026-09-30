"""
Gemini Meeting Analyzer:
Sends recorded 2-channel audio to Gemini (e.g. Gemini 3 Flash / 2.5 Flash)
and generates a structured meeting protocol including transcript, summary, and action items.
"""

import itertools
import logging
import os
import re
import time
import wave
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Literal

import numpy as np
from google import genai
from google.genai import errors, types

from ghostscribe import edition
from ghostscribe.i18n import LocalizedError
from ghostscribe.utils import format_duration, write_json_atomic, write_text_atomic
from ghostscribe.voices import recognize_voices, voice_context

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-latest"
FALLBACK_MODELS = (DEFAULT_MODEL, "gemini-3-flash-preview", "gemini-2.5-flash")  # tried after the configured model

MeetingType = Literal["standard", "sprint", "sales", "interview", "brainstorming"]

# Additional instructions per meeting type
MEETING_TYPE_FOCUS: dict[str, str] = {
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


# Company edition: an interview is documented without assessing the person. Evaluating candidates with AI is a
# high-risk use under the EU AI Act (Annex III no. 4), which comes with obligations that a meeting tool cannot meet.
NEUTRAL_INTERVIEW_FOCUS = (
    "Fokus: Fragen und Antworten je Thema, Vereinbarungen, offene Punkte und nächste Schritte. Halte fest, was "
    "gesagt wurde, und bewerte die befragte Person nicht: keine Einschätzung von Stärken, Schwächen, Eignung, "
    "Persönlichkeit oder Gesamteindruck.\n"
    "Füge nach „Offene Fragen & nächste Schritte“ ein:\n"
    "## 👤 Gesprächsverlauf\n"
    "| Thema | Frage | Antwort | [Zeit] |\n"
    "Danach: Vereinbarungen, Fragen der befragten Person und nächste Schritte."
)

# Company edition: the minutes say that they were generated and must be checked
GENERATED_NOTE = (
    "\n\n---\n*Automatisch erstellt mit GhostScribe und Google Gemini ({model}). Vor der Weitergabe prüfen.*\n"
)


def type_focus(meeting_type: str) -> str:
    """Additional instructions for the type of meeting; in the company edition interviews stay neutral."""
    if meeting_type == "interview" and edition.is_company():
        return NEUTRAL_INTERVIEW_FOCUS
    return MEETING_TYPE_FOCUS.get(meeting_type, MEETING_TYPE_FOCUS["standard"])


# What stands in front of the title in the first heading of the minutes, e.g. "📝 Besprechungsprotokoll: "
_TITLE_PREFIX = re.compile(
    r"^[\s\W\U00010000-\U0010ffff]*\b(Besprechungsprotokoll|Protokoll|Meeting Minutes|Meeting)\b\s*[:\-–—]?\s*",
    re.IGNORECASE,
)


def extract_title_from_markdown(markdown_text: str, fallback: str = "") -> str:
    """Extracts a clean meeting title from the first Markdown H1 heading."""
    if not markdown_text:
        return fallback
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            raw_title = stripped.lstrip("#").strip()
            clean_title = _TITLE_PREFIX.sub("", raw_title).strip()
            if clean_title:
                return clean_title
            if raw_title:
                return raw_title
    return fallback


def retitle_markdown(markdown_text: str, title: str) -> str:
    """Puts a new title into the first heading of the minutes; a prefix like "📝 Besprechungsprotokoll: " stays.
    Minutes that start with a section instead of a title keep their text."""
    lines = markdown_text.split("\n")
    for index, line in enumerate(lines):
        if line.strip().startswith("#"):
            if line.startswith("# "):
                prefix = _TITLE_PREFIX.match(line[2:].strip())
                kept = prefix.group(0).rstrip() if prefix else ""
                lines[index] = f"# {kept} {title}" if kept[-1:] in (":", "-", "–", "—") else f"# {title}"
            break
    return "\n".join(lines)


_SYSTEM_PROMPT_TEMPLATE = """
{intro}

# §. Grundregeln
1. Nur Belegtes: Übernimm ausschließlich, was in der Aufnahme gesagt wird. Erfinde keine Namen, Zahlen, Termine, Beschlüsse oder Zuständigkeiten.
2. Lücken sichtbar machen: Fehlt eine Angabe, schreibe „nicht genannt“. Unverständliche Stellen markierst du mit [unverständlich]; bei unsicherem Wortlaut (Namen, Zahlen, Fachbegriffe) setzt du (?) dahinter.
3. Exakte Werte: Zahlen, Beträge, Daten, Versionsnummern und Ticket-IDs gibst du genau so wieder, wie sie gesagt werden. Relative Angaben („nächsten Freitag“) rechnest du anhand des Meetingdatums in ein Datum um und nennst beides, z. B. „Fr, 02.10.2026 (‚nächsten Freitag‘)“.
4. Beschlüsse und Aufgaben: Ein Beschluss liegt nur vor, wenn die Beteiligten etwas ausdrücklich vereinbaren oder bestätigen. Eine Aufgabe liegt nur vor, wenn jemand sie übernimmt oder ausdrücklich zugewiesen bekommt. Ankündigungen und Zusagen in Reden, Vorträgen oder Präsentationen sind weder Beschlüsse noch Aufgaben, sondern gehören zu den Kernpunkten. Unbestätigte Vorschläge gehören zu „Offene Fragen & nächste Schritte“.
5. Sprache: Du schreibst auf Deutsch, unabhängig von der Sprache der Aufnahme. Ausnahmen: Das vollständige Transkript gibt jede Äußerung in der Originalsprache wieder; ist sie weder Deutsch noch Englisch, steht direkt darunter die deutsche Übersetzung als eingerückte Zitatzeile („  > …“). Zitate in den übrigen Abschnitten bleiben in der Originalsprache; ist ein Zitat weder Deutsch noch Englisch, folgt die deutsche Übersetzung in Klammern. Deutschen Dialekt überträgst du behutsam ins Standarddeutsche, ohne den Sinn zu verändern.
6. Keine verwertbare Besprechung (Stille, nur Musik, Testaufnahme, weniger als eine Minute Gespräch): Gib statt des Protokolls nur einen kurzen Hinweis aus.{no_emotion_rule}

# §. Sprecherzuordnung
Die Aufnahme basiert auf zwei Hardware-Quellen:
- Lokales Mikrofon (Kanal 0): Der Host / Nutzer vor dem PC.
- Rechner-Ton (Kanal 1 / Systemton / Loopback): Die übrigen Remote-Teilnehmer (z. B. Kollegen in Teams/Zoom).
1. Nutzer: Seine Stimme kommt direkt vom lokalen Mikrofon (oft lauter, klarer, ohne Streaming-Kompression). Bezeichne ihn mit dem übergebenen Namen bzw. seinem Vornamen. Ist das Mikrofon laut Kanal-Analyse stumm, hat er nicht gesprochen: Ordne ihm dann keine Äußerungen zu.
2. WICHTIG – Wer spricht vs. Wer wird angesprochen:
   - Direkte Ansprachen wie „Danke, <Name>“, „Bis morgen, <Name>“ oder „<Name>, was meinst du?“ bezeichnen IMMER den ZUHÖRER/EMPFÄNGER, niemals den Sprecher dieser Aussage!
   - Wenn der Kollege im Call den lokalen Nutzer mit seinem Vornamen oder Spitznamen verabschiedet oder anspricht (z. B. „Bis morgen, <Vorname>“), gehört dieser Name dem lokalen Nutzer – gib diesen Namen keinesfalls fälschlicherweise dem sprechenden Kollegen!
3. Übrige Teilnehmer: Unterscheide die Stimmen anhand von Stimmklang und Gesprächsverlauf. Vergib für jede Stimme ein festes Kürzel oder die Rollenbezeichnung (z. B. Kollege, Sprecher A) und verwende es in allen Abschnitten gleich.
4. Namen: Ersetze ein Kürzel nur durch einen Namen, wenn es dafür einen eindeutigen Beleg gibt (z. B. Selbstvorstellung oder namentliche Vorstellung durch andere). Ein Kürzel (z. B. „Kollege“) ist immer besser als ein vertauschter oder falscher Name.
5. Sammelbegriffe wie „die anderen“ verwendest du nicht. Ist eine Stimme wirklich nicht zuzuordnen, schreibe „Sprecher ?“.
6. Gleichzeitiges Sprechen markierst du mit [Übersprechen].

{sentiment_section}# §. Vollständigkeit bei langen Aufnahmen
- Bearbeite die Aufnahme vom Anfang bis zum Ende mit gleicher Sorgfalt. Inhalte aus der Mitte und dem letzten Drittel sind genauso wichtig wie der Einstieg.
- Jeder Beschluss, jede Aufgabe, jede Frist und jede genannte Zahl aus der gesamten Laufzeit gehört ins Protokoll.
- Prüfe vor der Ausgabe jede Phase des Meetings einzeln auf Beschlüsse und Aufgaben, die noch fehlen.

# §. Zeitstempel und Umfang
- Zeitstempel in allen Abschnitten immer im Format [HH:MM:SS] ab Beginn der Aufnahme, auch bei Aufnahmen unter einer Stunde (also [00:05:18], nie [05:18]); Zeiträume als [HH:MM:SS–HH:MM:SS].
- Dauer bis 45 Minuten: Kernpunkte nach Themen gliedern, im letzten Abschnitt ein vollständiges Transkript. Vollständig heißt: jeder Redebeitrag vom Anfang bis zum Ende der Aufnahme, Satz für Satz – nichts zusammenfassen, kürzen oder auslassen. Bereinigt werden nur Füllwörter, Versprecher und Wortwiederholungen. Setze bei jedem Sprecherwechsel einen Zeitstempel und teile längere Beiträge so auf, dass spätestens jede Minute ein neuer Eintrag mit Zeitstempel beginnt – auch dann, wenn unter den Einträgen Übersetzungen stehen.
- Dauer über 45 Minuten: Kernpunkte in chronologische Phasen gliedern („### Phase 1 [00:00:00–00:42:10]: <Thema>“). Die Phasen schließen lückenlos aneinander an und überschneiden sich nicht: Jede beginnt dort, wo die vorige endet, die letzte endet mit der Aufnahme. Ein Thema, das später wieder aufgegriffen wird, erscheint in der Phase, in der es besprochen wird. Im letzten Abschnitt ein verdichtetes Verlaufsprotokoll auf Deutsch mit Schlüsselzitaten in der Originalsprache, Wendepunkten und Entscheidungen. Smalltalk, Pausen und Technikprobleme lässt du weg, damit das Ausgabelimit für Inhalte reicht.

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
  - **<Name des Nutzers>** – Headset-Mikrofon (nur, wenn er spricht)
  - **<Name oder Sprecher A>** – <Rolle, falls erwähnt>; Zuordnung: <Beleg mit Zeitstempel, z. B. „stellt sich vor [00:01:12]“, oder „nicht zugeordnet“>

---

## 🎯 Management Summary
<3–6 Sätze: Anlass, wichtigste Ergebnisse und Entscheidungen, {summary_risk}>

{mood_section}## 📌 Kernpunkte & Diskussionsverlauf
<Je Thema bzw. Phase: {positions} und Argumente der Beteiligten mit Namen und [HH:MM:SS], Ergebnis.>

## ✅ Beschlüsse
- [HH:MM:SS] <Beschluss> — bestätigt von <Namen>

## 📋 Aufgaben
<Sortiert nach Priorität. Zuständig ist genau die Person oder Stelle, die im Gespräch genannt wird; ergänze keine Abteilungen, Rollen oder Organisationen. Ohne klar benannte Zuständigkeit: „**offen**“.>
- [ ] 🔴 **<Zuständig>**: <Aufgabe> — Frist: <Datum oder „nicht genannt“> — {task_reason} [HH:MM:SS]
- [ ] 🟡 **<Zuständig>**: <Aufgabe> — Frist: <Datum oder „nicht genannt“> [HH:MM:SS]
- [ ] 🟢 **<Zuständig>**: <Aufgabe> — Frist: <Datum oder „nicht genannt“> [HH:MM:SS]

## ❓ Offene Fragen & nächste Schritte
<Ungeklärtes, Vertagtes, unbestätigte Vorschläge, nächster Termin falls genannt.>

<Typspezifischer Zusatzabschnitt, falls der Kontext einen vorgibt.>

---

## 🎙️ Transkript / Verlauf
- [HH:MM:SS] **<Name>:** <Äußerung in der Originalsprache>
  > <Deutsche Übersetzung – nur, wenn die Äußerung weder Deutsch noch Englisch ist>{tone_line}
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
- Hörbare Reaktionen der Zuhörer (Applaus, Gelächter, Buhrufe, Zwischenrufe) vermerkst du im Transkript an der passenden Stelle in eckigen Klammern, z. B. [Applaus], und berücksichtigst sie im Stimmungsbild.

"""

_MOOD_SECTION = """## 🎭 Stimmungsbild
- **Gesamtklima:** <1–2 Sätze>
- 🔥 **Frustration & Bedenken:** <wer, worüber, [HH:MM:SS], Beleg>
- 🎉 **Erfolge, Freude & Erleichterung:** <wer, worüber, [HH:MM:SS]>
- ⚡ **Kontroversen:** <wo gingen die Meinungen auseinander, wer vertrat was, ob geklärt>

"""

# Mode-dependent parts of the system prompt
_PROMPT_VARIANTS = {
    True: {  # EU AI Act compliant (default): no emotion or sentiment analysis
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
    False: {  # Extended analysis including mood and tone
        "intro": "Du bist ein Protokoll-Assistent für Online-Besprechungen (Microsoft Teams, Zoom u. ä.). Du erhältst eine Audioaufnahme und Kontextdaten. Du erfasst das Gesagte, ordnest es den Sprechern zu, erfasst Stimmung und Tonalität und erstellst daraus ein deutschsprachiges Protokoll in Markdown.",
        "no_emotion_rule": "",
        "sentiment_section": _SENTIMENT_SECTION,
        "priority_high": "als Blocker oder dringend bezeichnet, andere Arbeit hängt davon ab, Frist innerhalb von 7 Tagen ab Meetingdatum, oder das Thema löste deutlich hörbare Frustration aus.",
        "mode_label": "🎭 Erweiterte Analyse (inkl. Tonalität & Gruppendynamik)",
        "summary_risk": "größtes offenes Risiko.",
        "mood_section": _MOOD_SECTION,
        "positions": "Positionen",
        "task_reason": "Grund: <kurz, z. B. „Blocker für Release“, „deutlicher Ärger über Verzögerung“>",
        "tone_line": "\n- [HH:MM:SS] **<Name>** [<Tonhinweis, nur bei markanten Momenten, z. B. hörbar verärgert, erleichtert lachend, skeptisch>]: <Äußerung in der Originalsprache>",
    },
}


def default_ai_act_mode() -> bool:
    """AI_ACT_MODE from .env: the EU AI Act compliant mode unless it is explicitly "false" (never in the company
    edition)."""
    return edition.is_company() or os.getenv("AI_ACT_MODE", "true").strip().lower() != "false"


def get_system_instruction(ai_act_mode: bool = True) -> str:
    """Returns the system prompt for the EU AI Act mode (default) or the extended sentiment mode."""
    prompt = _SYSTEM_PROMPT_TEMPLATE.format(**_PROMPT_VARIANTS[bool(ai_act_mode)])
    # Number the sections consecutively: "# §." -> "# 1.", "# 2.", ...
    numbers = itertools.count(1)
    return re.sub(r"^# §\.", lambda _: f"# {next(numbers)}.", prompt, flags=re.MULTILINE)


def check_api_key(api_key: str) -> bool | None:
    """Asks Google whether the key works (one entry of the model list, costs no tokens): True or False, None if
    Google cannot be reached (the key is then checked by the first analysis)."""
    try:
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=10_000))
        next(iter(client.models.list(config={"page_size": 1})), None)
    except errors.ClientError as e:
        return False if e.code in (400, 401, 403) else None
    except Exception:
        return None
    return True


def find_wav(audio_filepath: str) -> str | None:
    """Returns the uncompressed stereo WAV of a recording (the MP3 is a compressed mono copy)."""
    wav_path = os.path.splitext(audio_filepath)[0] + ".wav"
    return wav_path if os.path.exists(wav_path) else None


def recording_start(audio_filepath: str) -> datetime:
    """Start time from the file name (meeting_YYYY-MM-DD_HH-MM-SS), else the file's modification time."""
    stem = os.path.splitext(os.path.basename(audio_filepath))[0]
    try:
        return datetime.strptime(stem, "meeting_%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return datetime.fromtimestamp(os.path.getmtime(audio_filepath))


# Channel activity: each channel is judged against its own levels, because the microphone is often far quieter than
# the system audio (20 dB on a real Teams call) and the user often speaks while others do
ACTIVE_ABOVE_FLOOR_DB = 20.0  # a channel is active this far above its quiet level (10th percentile) ...
ACTIVE_MIN_DB = -50.0  # ... but not below this level ...
ACTIVE_ALWAYS_DB = -40.0  # ... and always from this level on (a channel that is busy almost all the time)
LEAK_MARGIN_DB = 10.0  # the user speaks when the microphone is this far above the system audio that reaches it
DOMINANCE_DB = 6.0  # both speak: the channel this much nearer to its usual speaking level wins, otherwise both


def _chunk_levels(data: np.ndarray, chunk_len: int) -> np.ndarray:
    """Level in dBFS per chunk of the microphone (column 0) and the system audio (column 1)."""
    num_chunks = len(data) // chunk_len
    power = np.empty((num_chunks, 2))
    for start in range(0, num_chunks, 256):  # in blocks: a long recording as floats would take gigabytes
        end = min(num_chunks, start + 256)
        block = data[start * chunk_len : end * chunk_len, :2].astype(np.float64)
        power[start:end] = (block.reshape(-1, chunk_len, 2) ** 2).mean(axis=1)
    return 10 * np.log10(power / 32768**2 + 1e-12)


def _channel_labels(levels: np.ndarray) -> np.ndarray:
    """MIC, LOOP, BOTH or SILENCE per chunk."""
    mic_db, loop_db = levels[:, 0], levels[:, 1]

    def active(db):
        return db > min(max(np.percentile(db, 10) + ACTIVE_ABOVE_FLOOR_DB, ACTIVE_MIN_DB), ACTIVE_ALWAYS_DB)

    mic_on, loop_on = active(mic_db), active(loop_db)
    # System audio that reaches the microphone (speakers, open headset) follows the system level at a fixed distance
    leak = np.median(mic_db[loop_on] - loop_db[loop_on]) if loop_on.sum() >= 10 else -60.0
    user = mic_on & (~loop_on | (mic_db - loop_db > leak + LEAK_MARGIN_DB))
    labels = np.where(user & ~loop_on, "MIC", np.where(loop_on & ~user, "LOOP", "SILENCE"))
    both = user & loop_on
    if both.any():
        mic_rel = mic_db - np.percentile(mic_db[user], 90)
        loop_rel = loop_db - np.percentile(loop_db[loop_on], 90)
        louder = np.where(
            mic_rel > loop_rel + DOMINANCE_DB, "MIC", np.where(loop_rel > mic_rel + DOMINANCE_DB, "LOOP", "BOTH")
        )
        labels[both] = louder[both]
    return labels


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

        raw_segments: list[tuple[str, float, float]] = []
        current_label: str | None = None
        seg_start = 0.0

        for i, lbl in enumerate(_channel_labels(_chunk_levels(data, chunk_len))):
            if lbl != current_label:
                if current_label and current_label != "SILENCE":
                    raw_segments.append((current_label, seg_start, i * chunk_sec))
                current_label = lbl
                seg_start = i * chunk_sec

        if current_label and current_label != "SILENCE":
            raw_segments.append((current_label, seg_start, num_chunks * chunk_sec))

        merged: list[tuple[str, float, float]] = []
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
        mic_share = total_mic / tot * 100

        lines = [
            f"Sprechanteil laut Hardware: Mikrofon (Nutzer) {mic_share:.0f} %, Systemton (Remote) {total_loop / tot * 100:.0f} %"
        ]
        if total_mic + total_both < 3:
            lines.append("Das Mikrofon war nahezu stumm: Der Nutzer hat höchstens einzelne Wörter gesagt.")
        lines.append("Verlauf (M = Mikrofon/Nutzer, S = Systemton/Remote, B = beide gleichzeitig):")
        labels = {"MIC": "M", "LOOP": "S", "BOTH": "B"}
        lines += [f"[{format_duration(s)}–{format_duration(e)}] {labels[lbl]}" for lbl, s, e in merged]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Channel analysis skipped: %s", e)
        return ""


GENERIC_TITLES = ("teams besprechung", "besprechung", "meeting", "call", "standard")
PROCESSING_TIMEOUT = 600  # seconds Google may take to process an uploaded recording
PROCESSING_POLL = 2  # seconds between two checks


def pauses_line(cuts: list[str] | None) -> str:
    """The places where the recording was paused: the conversation there is missing, not over."""
    if not cuts:
        return ""
    places = ", ".join(f"[{cut}]" for cut in cuts)
    return (
        f"\nPausen: Die Aufnahme wurde bei {places} pausiert; dort fehlt jeweils ein Teil der Besprechung. "
        "Dauer und Zeitstempel zählen ohne die Pausen."
    )


def build_user_prompt(
    title_text: str,
    meeting_date: str,
    duration: str,
    meeting_type: str,
    user_label: str,
    participants: str | None,
    channel_analysis: str,
    voices: list[dict],
    chat_text: str | None,
    image_count: int,
    cuts: list[str] | None = None,
) -> str:
    """The request for one recording: context, focus of the meeting type, channel timeline, voices, chat, slides."""
    specific_focus = type_focus(meeting_type)
    channel_block = ""
    if channel_analysis:
        channel_block = f"""
<hardware_kanal_analyse>
WICHTIGSTE PHYSIKALISCHE BODENWAHRHEIT ZUR SPRECHERZUORDNUNG:
Die Aufnahme hat zwei getrennte Kanäle: Kanal 0 = lokales Mikrofon des Nutzers ('{user_label}'),
Kanal 1 = Systemton mit den Remote-Teilnehmern (Teams/Zoom).

{channel_analysis}

VERBINDLICHE REGELN FÜR DIESE AUFNAHME:
1. Äußerungen in M-Phasen stammen vom Nutzer ('{user_label}'), Äußerungen in S-Phasen von Remote-Teilnehmern.
2. Ordne dem Nutzer keine Äußerung aus einer S-Phase zu – auch nicht, wenn dort sein Name fällt:
   Wer „Danke, …“ oder „Bis morgen, …“ sagt, spricht den Nutzer an.
3. Ordne einem Remote-Teilnehmer niemals den Namen des Nutzers zu. Ohne bekannten Namen heißt er „Kollege“ oder „Sprecher A“.
</hardware_kanal_analyse>
"""

    user_prompt = f"""Erstelle das Protokoll zur beigefügten Aufnahme.

<kontext>
Titel: {title_text}
Datum: {meeting_date}
Dauer: {duration}{pauses_line(cuts)}
Besprechungstyp: {meeting_type}
Nutzer (Headset-Mikrofon): {user_label}
Weitere Teilnehmer: {participants or "keine Angaben"}
</kontext>

<typ_schwerpunkt>
{specific_focus}
</typ_schwerpunkt>
{channel_block}{voice_context(voices)}
"""

    if chat_text and chat_text.strip():
        user_prompt += f"""

<zusatz_chatverlauf>
{chat_text.strip()}
</zusatz_chatverlauf>
Berücksichtige diesen Chatverlauf und geteilte Notizen bei Beschlüssen, Action Items, Links, Zahlen und Fragestellungen!
"""

    if image_count:
        user_prompt += f"""

BEIGEFÜGTE SCREENSHOTS / PRÄSENTATIONSFOLIEN ({image_count} Bild(er)):
Die beigefügten Bilder zeigen geteilte Bildschirminhalte / Folien aus dem Meeting.
Analysiere die gezeigten Diagramme, Tabellen, Kennzahlen oder Folien und verbinde sie mit den Aussagen der Sprecher.
"""
    return user_prompt


def response_markdown(response: Any) -> str:
    """The text of the answer; an answer without text leaves a note in the minutes."""
    markdown_content = response.text or ""
    if not markdown_content and getattr(response, "candidates", None):
        parts = [
            part.text
            for candidate in response.candidates
            if candidate.content and candidate.content.parts
            for part in candidate.content.parts
            if getattr(part, "text", None)
        ]
        markdown_content = "\n".join(parts)
    if not markdown_content:
        markdown_content = "*(Keine Zusammenfassung generiert. Die Audiodatei war möglicherweise zu kurz, enthielt keine Sprache oder wurde gefiltert.)*"
    return markdown_content


def recording_duration(audio_filepath: str) -> str:
    """HH:MM:SS of the WAV original (or the file itself), "nicht genannt" if it cannot be read."""
    try:
        with wave.open(find_wav(audio_filepath) or audio_filepath, "rb") as wf:
            return format_duration(wf.getnframes() / wf.getframerate())
    except (OSError, EOFError, wave.Error):
        return "nicht genannt"


Report = Callable[..., None]  # report(key, **params): progress as a translation key of the locale files


class MeetingAnalyzer:
    def __init__(self, api_key=None, model=None, meetings_dir="meetings", client=None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.meetings_dir = meetings_dir

        if not self.api_key:
            raise LocalizedError("error.no_api_key")

        os.makedirs(self.meetings_dir, exist_ok=True)
        self.client = client or genai.Client(api_key=self.api_key)

    def _upload_audio(self, audio_filepath: str, uploaded: list, report: Report) -> Any:
        """Uploads the recording and waits until Google has processed it."""
        report("step.uploading_audio", name=os.path.basename(audio_filepath))
        uploaded_file = self.client.files.upload(file=audio_filepath)
        uploaded.append(uploaded_file)
        report("step.upload_done")

        deadline = time.monotonic() + PROCESSING_TIMEOUT
        while getattr(uploaded_file.state, "name", None) == "PROCESSING":
            if time.monotonic() > deadline:
                raise LocalizedError("error.google_processing_timeout", minutes=PROCESSING_TIMEOUT // 60)
            report("step.gemini_processing")
            time.sleep(PROCESSING_POLL)
            uploaded_file = self.client.files.get(name=uploaded_file.name or "")

        if getattr(uploaded_file.state, "name", None) == "FAILED":
            raise LocalizedError("error.google_processing_failed", error=uploaded_file.error)
        return uploaded_file

    def _upload_images(self, image_filepaths: list[str], uploaded: list, report: Report) -> list:
        """Uploads the slides and screenshots; one that fails is left out."""
        images = []
        for idx, img_path in enumerate(image_filepaths):
            if not os.path.exists(img_path):
                continue
            name = os.path.basename(img_path)
            report("step.uploading_image", index=idx + 1, total=len(image_filepaths), name=name)
            try:
                image = self.client.files.upload(file=img_path)
            except Exception as img_err:
                report("step.image_upload_failed", name=name, error=img_err)
                continue
            images.append(image)
            uploaded.append(image)
        return images

    def _generate(self, contents: list, ai_act_mode: bool, report: Report) -> Any:
        """Asks the configured model first, then the fallback models."""
        last_error = None
        instruction = get_system_instruction(ai_act_mode)
        for current_model in dict.fromkeys([self.model, *FALLBACK_MODELS]):
            try:
                report("step.requesting", model=current_model)
                response = self.client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=instruction,
                        temperature=0.2,
                        # No tools are used; also avoids the SDK's AFC warning on every request
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
            except Exception as e:
                report("step.model_failed", model=current_model, error=e)
                last_error = e
                continue
            self.model = current_model
            return response
        raise LocalizedError("error.all_models_failed", error=last_error)

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
        cuts=None,
        on_status_update=None,
        ai_act_mode=True,
        voice_recognition=False,
        voice_workers=1,
    ):
        """
        Uploads audio & optional slides/chat to Gemini, requests analysis, and saves markdown report.
        on_status_update(key, **params) receives progress as translation keys of the locale files.
        cuts are the positions ("HH:MM:SS") where the recording was paused.
        With voice_recognition the voices on the system-audio channel are separated and recognized locally while
        the files are uploaded.
        """
        if not os.path.exists(audio_filepath):
            raise LocalizedError("error.audio_file_missing", path=audio_filepath)

        ai_act_mode = bool(ai_act_mode) or edition.is_company()  # the company edition has no sentiment mode
        user_label = user_name.strip() if user_name and user_name.strip() else "Ich"
        duration = duration or recording_duration(audio_filepath)
        uploaded_remote_files: list = []

        def report(key, **params):
            if on_status_update:
                on_status_update(key, **params)

        # The local voice recognition runs while the files are uploaded; the request needs its result only
        wav_path = find_wav(audio_filepath)
        recognition = None
        if voice_recognition and wav_path:
            report("step.recognizing_voices")
            background = ThreadPoolExecutor(1)
            recognition = background.submit(recognize_voices, wav_path, workers=voice_workers, report=report)
            background.shutdown(wait=False)

        try:
            uploaded_file = self._upload_audio(audio_filepath, uploaded_remote_files, report)
            uploaded_images = self._upload_images(image_filepaths or [], uploaded_remote_files, report)

            voices = []
            if recognition:
                try:
                    if not recognition.done():
                        report("step.recognizing_voices")
                    voices = recognition.result()
                    report("step.voices_recognized", count=len(voices))
                except Exception as e:  # optional feature: the minutes are still created without it
                    logger.warning("Voice recognition failed: %s", e)
                    report("step.voice_recognition_failed", error=e)

            clean_input_title = (meeting_title or "").strip()
            is_generic_title = not clean_input_title or clean_input_title.lower() in GENERIC_TITLES
            title_text = (
                clean_input_title
                if not is_generic_title
                else "Nicht vorgegeben (Bitte extrahiere ein prägnantes, aussagekräftiges Hauptthema 3-7 Wörter für die oberste '# 📝 Besprechungsprotokoll: <Titel>' Zeile!)"
            )
            meeting_start = recording_start(audio_filepath)
            user_prompt = build_user_prompt(
                title_text=title_text,
                meeting_date=meeting_start.strftime("%d.%m.%Y, %H:%M Uhr"),
                duration=duration,
                meeting_type=meeting_type,
                user_label=user_label,
                participants=participants,
                channel_analysis=extract_channel_activity_summary(audio_filepath),
                voices=voices,
                chat_text=chat_text,
                image_count=len(uploaded_images),
                cuts=cuts,
            )

            response = self._generate([uploaded_file, *uploaded_images, user_prompt], ai_act_mode, report)
            markdown_content = response_markdown(response)
            if response.candidates and response.candidates[0].finish_reason == types.FinishReason.MAX_TOKENS:
                report("step.output_truncated")
                markdown_content += "\n\n> ⚠️ **Hinweis:** Das Protokoll wurde am Ausgabelimit des Modells abgeschnitten und ist unvollständig."

            # Save as Markdown & JSON
            base_name = os.path.splitext(os.path.basename(audio_filepath))[0]
            md_filename = os.path.join(self.meetings_dir, f"{base_name}.md")
            json_filename = os.path.join(self.meetings_dir, f"{base_name}.json")

            if edition.is_company():
                markdown_content = markdown_content.rstrip() + GENERATED_NOTE.format(model=self.model)
            write_text_atomic(md_filename, markdown_content)

            extracted_title = extract_title_from_markdown(markdown_content)
            if is_generic_title and extracted_title:
                final_title = extracted_title
                report("step.title_detected", title=final_title)
            else:
                final_title = clean_input_title or extracted_title or base_name

            metadata = {
                "title": final_title,
                "user_name": user_label,
                "participants": participants or "",
                "meeting_type": meeting_type or "standard",
                "ai_act_mode": bool(ai_act_mode),
                "meeting_start": meeting_start.isoformat(timespec="seconds"),
                "created_at": datetime.now().isoformat(),
                "audio_file": audio_filepath,
                "model_used": self.model,
                "markdown_file": md_filename,
                "has_chat": bool(chat_text and chat_text.strip()),
                "image_count": len(uploaded_images),
                "attachments": list(image_filepaths or []),
                "voices": voices,
            }
            write_json_atomic(json_filename, metadata)

            return {
                "markdown_content": markdown_content,
                "markdown_file": md_filename,
                "json_file": json_filename,
                "metadata": metadata,
            }

        finally:
            # Always delete the temporary files at Google
            for up_file in uploaded_remote_files:
                try:
                    self.client.files.delete(name=up_file.name)
                    report("step.remote_file_deleted", name=up_file.name)
                except Exception as e:
                    report("step.remote_file_delete_failed", name=up_file.name, error=e)

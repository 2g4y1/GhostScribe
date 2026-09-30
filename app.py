"""
FastAPI Server for GhostScribe - Meeting Recorder & Analyzer
"""

import base64
import glob
import json
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analyzer import DEFAULT_MODEL, MeetingAnalyzer, recording_start
from recorder import MeetingRecorder
from utils import APP_URL, PORT, format_duration, update_env_file

load_dotenv(".env")  # dieselbe Datei, die update_env_file() beschreibt


# Filtert hochfrequente Polling-Aufrufe von /api/status aus dem Terminal,
# damit Aufnahme-Meldungen und Status-Updates im CMD-Fenster immer klar lesbar bleiben.
class StatusEndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/status" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(StatusEndpointFilter())

app = FastAPI(title="GhostScribe - Bot-Free AI Meeting Recorder")

# Only the local UI may talk to the server: requests from foreign websites (CSRF)
# and via foreign host names (DNS rebinding) are rejected.
ALLOWED_HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}


@app.middleware("http")
async def allow_only_local_ui(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.headers.get("host") not in ALLOWED_HOSTS or (
        origin and origin.removeprefix("http://") not in ALLOWED_HOSTS
    ):
        return JSONResponse(status_code=403, content={"detail": "Zugriff nur über die lokale GhostScribe-Oberfläche."})
    return await call_next(request)


app.mount("/static", StaticFiles(directory="static"), name="static")

RECORDINGS_DIR = "recordings"
MEETINGS_DIR = "meetings"
ATTACHMENTS_DIR = os.path.join(RECORDINGS_DIR, "attachments")
AUDIO_EXTENSIONS = (".mp3", ".wav")


def _default_ai_act_mode() -> bool:
    return os.getenv("AI_ACT_MODE", "true").strip().lower() != "false"


recorder = MeetingRecorder(output_dir=RECORDINGS_DIR)
app_state = {
    "status": "idle",  # "idle", "recording", "processing", "error"
    "process_step": "",
    "current_title": "",
    "current_participants": "",
    "current_meeting_type": "standard",
    "current_user_name": "Ich",
    "ai_act_mode": _default_ai_act_mode(),
    "last_meeting_id": None,
    "last_error": None,
}


class StartRequest(BaseModel):
    title: str = ""
    participants: str = ""
    meeting_type: str = "standard"
    user_name: str = "Ich"
    ai_act_mode: bool = True
    mic_device: int | None = None  # None = Windows default device
    loopback_device: int | None = None


class AttachmentItem(BaseModel):
    filename: str = "screenshot.png"
    data: str  # Base64 data URL or raw base64 string


class StopRequest(BaseModel):
    chat_text: str = ""
    images: list[AttachmentItem] = []
    ai_act_mode: bool = True


class AnalyzeRequest(BaseModel):
    ai_act_mode: bool = True
    user_name: str = ""


class SettingsRequest(BaseModel):
    api_key: str = ""
    model: str = DEFAULT_MODEL
    default_ai_act_mode: bool | None = None


def _safe_filename(name: str) -> str:
    """Rejects anything but a plain file name (path traversal protection, e.g. '../.env')."""
    if name in ("", ".", "..") or name != os.path.basename(name):
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname.")
    return name


def _recording_path(filename: str) -> str:
    return os.path.join(RECORDINGS_DIR, _safe_filename(filename))


def _meeting_paths(meeting_id: str) -> tuple[str, str]:
    """Returns the (JSON, Markdown) paths of a meeting protocol."""
    base = os.path.join(MEETINGS_DIR, _safe_filename(meeting_id))
    return base + ".json", base + ".md"


def _context_path(audio_base: str) -> str:
    """Analysis input of a recording, kept until its protocol exists so a failed analysis can be retried."""
    return os.path.join(RECORDINGS_DIR, f"{audio_base}.context.json")


def _load_context(audio_base: str) -> dict:
    try:
        with open(_context_path(audio_base), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _recording_files(audio_base: str) -> list[str]:
    """All files of one recording: MP3, WAV original, saved analysis context and its screenshots."""
    files = [os.path.join(RECORDINGS_DIR, audio_base + ext) for ext in AUDIO_EXTENSIONS]
    files += [
        os.path.join(ATTACHMENTS_DIR, os.path.basename(p)) for p in _load_context(audio_base).get("image_paths", [])
    ]
    files.append(_context_path(audio_base))
    return files


def _delete_files(paths) -> list[str]:
    deleted = []
    for path in paths:
        if os.path.isfile(path):
            try:
                os.remove(path)
                deleted.append(path)
            except OSError:
                pass
    return deleted


def _processed_audio_bases() -> set[str]:
    """Base names of all recordings that already have a protocol."""
    bases = set()
    for json_path in glob.glob(os.path.join(MEETINGS_DIR, "*.json")):
        bases.add(os.path.splitext(os.path.basename(json_path))[0])
        try:
            with open(json_path, encoding="utf-8") as f:
                audio_file = json.load(f).get("audio_file")
        except (OSError, ValueError):
            continue
        if audio_file:
            bases.add(os.path.splitext(os.path.basename(audio_file))[0])
    return bases


@app.get("/")
def get_index():
    return FileResponse("static/index.html")


@app.get("/favicon.ico")
def get_favicon():
    if os.path.exists("static/logo.png"):
        return FileResponse("static/logo.png", media_type="image/png")
    raise HTTPException(status_code=404, detail="Favicon nicht gefunden")


@app.get("/api/status")
def get_status():
    devices_in_use = app_state["status"] in ("recording", "processing")
    return {
        "status": app_state["status"],
        "process_step": app_state["process_step"],
        "duration": recorder.get_duration(),
        "mic_level": recorder.mic_level if recorder.is_recording else 0.0,
        "loopback_level": recorder.loopback_level if recorder.is_recording else 0.0,
        "mic_device": recorder.mic_info.get("name") if devices_in_use else None,
        "loopback_device": recorder.loopback_info.get("name") if devices_in_use else None,
        "has_api_key": len(os.getenv("GEMINI_API_KEY", "").strip()) > 5,
        "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        "ai_act_mode": app_state["ai_act_mode"],
        "default_ai_act_mode": _default_ai_act_mode(),
        "last_meeting_id": app_state["last_meeting_id"],
        "last_error": app_state["last_error"],
        "current_title": app_state["current_title"],
        "current_participants": app_state["current_participants"],
        "current_meeting_type": app_state["current_meeting_type"],
        "current_user_name": app_state["current_user_name"],
    }


@app.get("/api/devices")
def list_devices():
    """Selectable microphones and loopback devices (not available while recording)."""
    if recorder.is_recording:
        raise HTTPException(status_code=409, detail="Während einer Aufnahme nicht verfügbar.")
    try:
        return MeetingRecorder.list_devices()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audiogeräte konnten nicht ermittelt werden: {e}") from e


@app.post("/api/record/start")
def start_recording(req: StartRequest):
    if app_state["status"] in ["recording", "processing"]:
        raise HTTPException(status_code=400, detail="Aufnahme oder Verarbeitung läuft bereits.")

    try:
        app_state["current_title"] = req.title.strip() or "Teams Besprechung"
        app_state["current_participants"] = req.participants.strip()
        app_state["current_meeting_type"] = req.meeting_type.strip() or "standard"
        app_state["current_user_name"] = req.user_name.strip() or "Ich"
        app_state["ai_act_mode"] = req.ai_act_mode
        app_state["last_error"] = None
        recorder.start(mic_index=req.mic_device, loopback_index=req.loopback_device)
        app_state["status"] = "recording"

        print("\n" + "=" * 68)
        print("🔴 [AUFNAHME GESTARTET]")
        print(f"   Thema:        {app_state['current_title']}")
        print(f"   Eigener Name: {app_state['current_user_name']} (Kanal 0 / Mikrofon)")
        if app_state["current_participants"]:
            print(f"   Teilnehmer:   {app_state['current_participants']} (Kanal 1 / Teams)")
        print(f"   Mikrofon:     {recorder.mic_info['name']}")
        print(f"   Systemton:    {recorder.loopback_info['name']}")
        print(f"   Startzeit:    {datetime.now().strftime('%H:%M:%S')}")
        print("   ℹ️  HINWEIS:    Die Aufnahme läuft stabil als Dienst im Hintergrund,")
        print("                 selbst wenn alle Browserfenster geschlossen werden!")
        print(f"   ➡️  Web-UI:     {APP_URL} (jederzeit wieder aufrufbar)")
        print("=" * 68 + "\n")

        return {"success": True, "title": app_state["current_title"]}
    except Exception as e:
        import traceback

        traceback.print_exc()
        app_state["status"] = "error"
        app_state["last_error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/record/cancel")
def cancel_recording():
    if app_state["status"] != "recording":
        raise HTTPException(status_code=400, detail="Keine aktive Aufnahme zum Abbrechen.")

    recorder.cancel()
    app_state["status"] = "idle"
    app_state["process_step"] = "Aufnahme abgebrochen."
    print("\n" + "=" * 68)
    print("❌ [AUFNAHME ABGEBROCHEN] Aufnahmedaten verworfen.")
    print("=" * 68 + "\n")
    return {"success": True, "message": "Aufnahme erfolgreich verworfen."}


def save_attachments(images: list[AttachmentItem]) -> list[str]:
    """Decodes base64 attachments and stores them in recordings/attachments/."""
    saved_paths = []
    if not images:
        return saved_paths

    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for idx, item in enumerate(images):
        try:
            raw_data = item.data.strip()
            ext = ".png"
            if raw_data.startswith("data:image/"):
                header, b64_str = raw_data.split(",", 1)
                if "jpeg" in header or "jpg" in header:
                    ext = ".jpg"
                elif "webp" in header:
                    ext = ".webp"
                elif "png" in header:
                    ext = ".png"
            elif "," in raw_data:
                _, b64_str = raw_data.split(",", 1)
            else:
                b64_str = raw_data

            img_bytes = base64.b64decode(b64_str)
            clean_name = f"attachment_{ts}_{idx + 1}{ext}"
            file_path = os.path.join(ATTACHMENTS_DIR, clean_name)
            with open(file_path, "wb") as f:
                f.write(img_bytes)
            saved_paths.append(file_path)
        except Exception as e:
            print(f"[Attachment] Fehler beim Speichern von Bild {idx + 1}: {e}")

    return saved_paths


def run_gemini_analysis(audio_path: str, context: dict):
    """Runs the Gemini analysis. On failure the context file stays, so the recording can be analyzed again."""
    try:
        app_state["status"] = "processing"
        app_state["process_step"] = "Starte Analyse..."

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            app_state["status"] = "idle"
            app_state["process_step"] = "Audiodatei gespeichert (Kein API-Key für Analyse vorhanden)."
            return

        def update_step(msg):
            app_state["process_step"] = msg

        MeetingAnalyzer(api_key=api_key).analyze_meeting(
            audio_filepath=audio_path,
            meeting_title=context.get("title", ""),
            participants=context.get("participants", ""),
            meeting_type=context.get("meeting_type", "standard"),
            user_name=context.get("user_name", "Ich"),
            chat_text=context.get("chat_text", ""),
            image_filepaths=context.get("image_paths", []),
            duration=context.get("duration"),
            on_status_update=update_step,
            ai_act_mode=context.get("ai_act_mode", True),
        )

        audio_base = os.path.splitext(os.path.basename(audio_path))[0]
        _delete_files([_context_path(audio_base)])
        app_state["last_meeting_id"] = audio_base
        app_state["status"] = "idle"
        app_state["process_step"] = "Analyse erfolgreich abgeschlossen!"
    except Exception as e:
        app_state["status"] = "error"
        app_state["last_error"] = str(e)
        app_state["process_step"] = f"Fehler: {e}"


def _save_and_analyze(context: dict):
    """Background task after stopping: writes the audio files, keeps the context for retries, analyzes."""
    try:
        audio_path = recorder.save(compress=True)
    except Exception as e:
        app_state["status"] = "error"
        app_state["last_error"] = f"Audiodatei konnte nicht gespeichert werden: {e}"
        return

    audio_base = os.path.splitext(os.path.basename(audio_path))[0]
    with open(_context_path(audio_base), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2, ensure_ascii=False)
    print(f"   Audiodatei gespeichert: {audio_path}")
    run_gemini_analysis(audio_path, context)


@app.post("/api/record/stop")
def stop_recording(background_tasks: BackgroundTasks, req: StopRequest | None = None):
    if app_state["status"] != "recording":
        raise HTTPException(status_code=400, detail="Keine aktive Aufnahme.")

    recorder.stop_capture()
    req = req or StopRequest(ai_act_mode=app_state["ai_act_mode"])
    context = {
        "title": app_state["current_title"],
        "participants": app_state["current_participants"],
        "meeting_type": app_state["current_meeting_type"],
        "user_name": app_state["current_user_name"],
        "chat_text": req.chat_text.strip(),
        "image_paths": save_attachments(req.images),
        "ai_act_mode": req.ai_act_mode,
        "duration": format_duration(recorder.end_time - recorder.start_time),
    }
    app_state["status"] = "processing"
    app_state["process_step"] = "Audio wird synchronisiert und gespeichert..."
    background_tasks.add_task(_save_and_analyze, context)

    mode_text = "EU AI Act Modus" if req.ai_act_mode else "Stimmungsanalyse-Modus"
    print("\n" + "=" * 68)
    print(f"⏹️ [AUFNAHME BEENDET] Gesamtlaufzeit: {context['duration']} ({mode_text})")
    if context["chat_text"]:
        print(f"   Chatverlauf:  {len(context['chat_text'])} Zeichen übergeben")
    if context["image_paths"]:
        print(f"   Screenshots:  {len(context['image_paths'])} Bild(er) beigefügt")
    print("   🤖 Speichere Audio und starte Gemini KI-Analyse im Hintergrund...")
    print("=" * 68 + "\n")

    return {"success": True}


@app.get("/api/unprocessed-recordings")
def list_unprocessed_recordings():
    """Recordings without a protocol (e.g. after a failed analysis), one entry each with MP3 preferred."""
    processed = _processed_audio_bases()
    recordings = {}
    for ext in (".wav", ".mp3"):  # MP3 is inserted last and therefore replaces the WAV entry
        for path in glob.glob(os.path.join(RECORDINGS_DIR, "*" + ext)):
            base = os.path.splitext(os.path.basename(path))[0]
            if base not in processed and os.path.getsize(path) >= 10000:  # Ignoriere winzige Klick-Tests
                recordings[base] = path
    return [
        {
            "filename": os.path.basename(path),
            "title": _load_context(base).get("title", ""),
            "time": recording_start(path).strftime("%d.%m.%Y %H:%M"),
            "size_kb": round(os.path.getsize(path) / 1024),
        }
        for base, path in sorted(recordings.items(), reverse=True)
    ]


@app.post("/api/recordings/{filename}/analyze")
def analyze_existing_recording(filename: str, background_tasks: BackgroundTasks, req: AnalyzeRequest | None = None):
    audio_path = _recording_path(filename)
    if not os.path.isfile(audio_path):
        raise HTTPException(status_code=404, detail="Audiodatei nicht gefunden.")
    if app_state["status"] in ["recording", "processing"]:
        raise HTTPException(status_code=400, detail="Aktuell läuft bereits eine Aufnahme oder Analyse.")

    req = req or AnalyzeRequest(ai_act_mode=_default_ai_act_mode())
    context = {"ai_act_mode": req.ai_act_mode, "user_name": req.user_name.strip() or "Ich"}
    # Die gespeicherten Angaben der ursprünglichen Aufnahme (Titel, Chat, Screenshots, Modus) haben Vorrang
    context.update(_load_context(os.path.splitext(filename)[0]))

    app_state["status"] = "processing"
    app_state["process_step"] = f"Starte Analyse für {filename}..."
    app_state["last_error"] = None
    background_tasks.add_task(run_gemini_analysis, audio_path, context)
    return {"success": True, "message": "Analyse gestartet."}


@app.delete("/api/recordings/{filename}")
def delete_recording(filename: str):
    """Deletes a recording without protocol: MP3, WAV original, saved context and screenshots."""
    audio_base = os.path.splitext(_safe_filename(filename))[0]
    if app_state["status"] in ["recording", "processing"]:
        raise HTTPException(status_code=400, detail="Während einer Aufnahme oder Analyse nicht möglich.")
    if audio_base in _processed_audio_bases():
        raise HTTPException(
            status_code=409, detail="Zu dieser Aufnahme gibt es ein Protokoll. Bitte das Meeting löschen."
        )

    deleted_files = _delete_files(_recording_files(audio_base))
    if not deleted_files:
        raise HTTPException(status_code=404, detail="Aufnahme nicht gefunden.")
    return {"success": True, "deleted_files": deleted_files}


@app.get("/api/meetings")
def list_meetings():
    meetings = []
    json_files = sorted(glob.glob(os.path.join(MEETINGS_DIR, "*.json")), key=os.path.getmtime, reverse=True)
    for jf in json_files:
        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
                base_id = os.path.splitext(os.path.basename(jf))[0]
                data["id"] = base_id

                # Volltext für Suche (Transkript, Diskussionen, Beschlüsse)
                md_path = os.path.join(MEETINGS_DIR, f"{base_id}.md")
                if os.path.exists(md_path):
                    with open(md_path, encoding="utf-8") as mf:
                        data["content"] = mf.read()
                else:
                    data["content"] = ""

                meetings.append(data)
        except Exception:
            continue
    return meetings


@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str):
    json_path, md_path = _meeting_paths(meeting_id)

    if not os.path.exists(json_path) or not os.path.exists(md_path):
        raise HTTPException(status_code=404, detail="Meeting nicht gefunden.")

    with open(json_path, encoding="utf-8") as f:
        meta = json.load(f)

    with open(md_path, encoding="utf-8") as f:
        markdown = f.read()

    audio_filename = os.path.basename(meta.get("audio_file", ""))
    return {
        "metadata": meta,
        "markdown": markdown,
        "audio_url": f"/recordings/{audio_filename}" if audio_filename else None,
    }


@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: str):
    """Deletes the protocol and every file of the meeting: MP3, WAV original and screenshots."""
    json_path, md_path = _meeting_paths(meeting_id)

    metadata = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception:
            pass

    audio_base = os.path.splitext(os.path.basename(metadata.get("audio_file") or meeting_id))[0]
    candidates = _recording_files(audio_base)
    candidates += [os.path.join(ATTACHMENTS_DIR, os.path.basename(p)) for p in metadata.get("attachments") or []]
    candidates += [md_path, json_path]

    deleted_files = _delete_files(candidates)
    if not deleted_files:
        raise HTTPException(status_code=404, detail="Meeting nicht gefunden.")

    if app_state["last_meeting_id"] == meeting_id:
        app_state["last_meeting_id"] = None

    return {"success": True, "deleted_files": deleted_files}


@app.get("/recordings/{filename}")
def get_audio_file(filename: str):
    filepath = _recording_path(filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Audiodatei nicht gefunden.")
    media_type = "audio/mpeg" if filename.lower().endswith(".mp3") else "audio/wav"
    return FileResponse(filepath, media_type=media_type)


@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    updates = {"GEMINI_MODEL": req.model.strip() or DEFAULT_MODEL}
    # Nur aktualisieren wenn ein echter Key übergeben wurde (nicht maskiert mit • oder *)
    new_key = req.api_key.strip()
    if new_key and "•" not in new_key and "*" not in new_key:
        updates["GEMINI_API_KEY"] = new_key
    if req.default_ai_act_mode is not None:
        updates["AI_ACT_MODE"] = "true" if req.default_ai_act_mode else "false"

    try:
        update_env_file(updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"success": True, "message": "Einstellungen gespeichert."}

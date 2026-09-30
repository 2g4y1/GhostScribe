"""
FastAPI Server for GhostScribe - Meeting Recorder & Analyzer
"""

import base64
import glob
import json
import logging
import os
import time
from datetime import datetime

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analyzer import DEFAULT_MODEL, MeetingAnalyzer
from recorder import MeetingRecorder
from utils import APP_URL, format_duration, update_env_file

load_dotenv()


# Filtert hochfrequente Polling-Aufrufe von /api/status aus dem Terminal,
# damit Aufnahme-Meldungen und Status-Updates im CMD-Fenster immer klar lesbar bleiben.
class StatusEndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/status" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(StatusEndpointFilter())

app = FastAPI(title="GhostScribe - Bot-Free AI Meeting Recorder")

app.mount("/static", StaticFiles(directory="static"), name="static")

RECORDINGS_DIR = "recordings"
MEETINGS_DIR = "meetings"
ATTACHMENTS_DIR = os.path.join(RECORDINGS_DIR, "attachments")

recorder = MeetingRecorder()
app_state = {
    "status": "idle",  # "idle", "recording", "processing", "error"
    "process_step": "",
    "current_title": "",
    "current_participants": "",
    "current_meeting_type": "standard",
    "current_user_name": "Ich",
    "ai_act_mode": True,
    "last_meeting_id": None,
    "last_error": None,
}


class StartRequest(BaseModel):
    title: str = ""
    participants: str = ""
    meeting_type: str = "standard"
    user_name: str = "Ich"
    ai_act_mode: bool = True


class AttachmentItem(BaseModel):
    filename: str = "screenshot.png"
    data: str  # Base64 data URL or raw base64 string


class StopRequest(BaseModel):
    chat_text: str = ""
    images: list[AttachmentItem] = []
    ai_act_mode: bool = True


class SettingsRequest(BaseModel):
    api_key: str = ""
    model: str = DEFAULT_MODEL
    default_ai_act_mode: bool | None = None


# Caching device discovery to avoid PortAudio C-runtime race conditions on 300ms polling
cached_devices = {"mic_name": "Erkenne...", "loopback_name": "Erkenne...", "last_check": 0}


def update_cached_devices(force=False):
    now = time.time()
    if not force and (now - cached_devices["last_check"]) < 60:
        return cached_devices["mic_name"], cached_devices["loopback_name"]
    try:
        mic_info, loopback_info = recorder.find_devices()
        cached_devices["mic_name"] = mic_info["name"]
        cached_devices["loopback_name"] = loopback_info["name"]
        cached_devices["last_check"] = now
    except Exception:
        pass
    return cached_devices["mic_name"], cached_devices["loopback_name"]


# Initial discovery on startup
update_cached_devices(force=True)


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
    mic_name = cached_devices["mic_name"]
    loopback_name = cached_devices["loopback_name"]

    has_api_key = len(os.getenv("GEMINI_API_KEY", "").strip()) > 5

    return {
        "status": app_state["status"],
        "process_step": app_state["process_step"],
        "duration": recorder.get_duration(),
        "mic_level": recorder.mic_level if recorder.is_recording else 0.0,
        "loopback_level": recorder.loopback_level if recorder.is_recording else 0.0,
        "mic_device": mic_name,
        "loopback_device": loopback_name,
        "has_api_key": has_api_key,
        "model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        "ai_act_mode": app_state.get("ai_act_mode", True),
        "last_meeting_id": app_state["last_meeting_id"],
        "last_error": app_state["last_error"],
        "current_title": app_state["current_title"],
        "current_participants": app_state["current_participants"],
        "current_meeting_type": app_state["current_meeting_type"],
        "current_user_name": app_state["current_user_name"],
    }


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
        recorder.start()
        app_state["status"] = "recording"

        print("\n" + "=" * 68)
        print("🔴 [AUFNAHME GESTARTET]")
        print(f"   Thema:        {app_state['current_title']}")
        print(f"   Eigener Name: {app_state['current_user_name']} (Kanal 0 / Mikrofon)")
        if app_state["current_participants"]:
            print(f"   Teilnehmer:   {app_state['current_participants']} (Kanal 1 / Teams)")
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


def _analysis_context(req: StopRequest | None) -> tuple[bool, str, list[str]]:
    """Returns (ai_act_mode, chat_text, saved screenshot paths) from an optional stop/analyze request."""
    if req is None:
        return app_state["ai_act_mode"], "", []
    saved_images = save_attachments(req.images) if req.images else []
    return req.ai_act_mode, req.chat_text.strip(), saved_images


def run_gemini_analysis(
    audio_path,
    title,
    participants="",
    meeting_type="standard",
    user_name="Ich",
    chat_text="",
    image_paths=None,
    duration=None,
    ai_act_mode=True,
):
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

        analyzer = MeetingAnalyzer(api_key=api_key)
        analyzer.analyze_meeting(
            audio_filepath=audio_path,
            meeting_title=title,
            participants=participants,
            meeting_type=meeting_type,
            user_name=user_name,
            chat_text=chat_text,
            image_filepaths=image_paths,
            duration=duration,
            on_status_update=update_step,
            ai_act_mode=ai_act_mode,
        )

        base_id = os.path.splitext(os.path.basename(audio_path))[0]
        app_state["last_meeting_id"] = base_id
        app_state["status"] = "idle"
        app_state["process_step"] = "Analyse erfolgreich abgeschlossen!"
    except Exception as e:
        app_state["status"] = "error"
        app_state["last_error"] = str(e)
        app_state["process_step"] = f"Fehler: {e}"


@app.post("/api/record/stop")
def stop_recording(background_tasks: BackgroundTasks, req: StopRequest | None = None):
    if app_state["status"] != "recording":
        raise HTTPException(status_code=400, detail="Keine aktive Aufnahme.")

    # Mit MP3-Kompression für 10x schnellere Uploads
    audio_path = recorder.stop(compress=True)
    if not audio_path or not os.path.exists(audio_path):
        app_state["status"] = "idle"
        raise HTTPException(status_code=500, detail="Fehler beim Speichern der Audiodatei.")

    ai_act_mode, chat_text, saved_images = _analysis_context(req)
    dur_str = format_duration(recorder.end_time - recorder.start_time)

    background_tasks.add_task(
        run_gemini_analysis,
        audio_path=audio_path,
        title=app_state["current_title"],
        participants=app_state["current_participants"],
        meeting_type=app_state["current_meeting_type"],
        user_name=app_state["current_user_name"],
        chat_text=chat_text,
        image_paths=saved_images,
        duration=dur_str,
        ai_act_mode=ai_act_mode,
    )
    app_state["status"] = "processing"
    mode_text = "EU AI Act Modus" if ai_act_mode else "Stimmungsanalyse-Modus"
    app_state["process_step"] = f"Audio synchronisiert ({mode_text}). Übergebe an Gemini..."

    print("\n" + "=" * 68)
    print(f"⏹️ [AUFNAHME BEENDET] Gesamtlaufzeit: {dur_str} ({mode_text})")
    print(f"   Audiodatei:   {audio_path}")
    if chat_text:
        print(f"   Chatverlauf:  {len(chat_text)} Zeichen übergeben")
    if saved_images:
        print(f"   Screenshots:  {len(saved_images)} Bild(er) beigefügt")
    print("   🤖 Starte Gemini KI-Analyse im Hintergrund...")
    print("=" * 68 + "\n")

    return {"success": True, "audio_file": audio_path}


@app.get("/api/unprocessed-recordings")
def list_unprocessed_recordings():
    """Findet Aufnahmen in recordings/, zu denen kein Protokoll existiert."""
    unprocessed = []
    for ext in ["*.mp3", "*.wav"]:
        for f in glob.glob(os.path.join(RECORDINGS_DIR, ext)):
            base = os.path.splitext(os.path.basename(f))[0]
            if os.path.exists(os.path.join(MEETINGS_DIR, f"{base}.json")):
                continue
            # Ignoriere winzige Klick-Tests (< 10 KB)
            if os.path.getsize(f) < 10000:
                continue
            unprocessed.append(
                {
                    "filename": os.path.basename(f),
                    "filepath": f,
                    "size_kb": round(os.path.getsize(f) / 1024, 1),
                    "time": datetime.fromtimestamp(os.path.getmtime(f)).strftime("%d.%m.%Y %H:%M:%S"),
                }
            )
    return unprocessed


@app.post("/api/recordings/{filename}/analyze")
def analyze_existing_recording(filename: str, background_tasks: BackgroundTasks, req: StopRequest | None = None):
    audio_path = _recording_path(filename)
    if not os.path.isfile(audio_path):
        raise HTTPException(status_code=404, detail="Audiodatei nicht gefunden.")
    if app_state["status"] in ["recording", "processing"]:
        raise HTTPException(status_code=400, detail="Aktuell läuft bereits eine Aufnahme oder Analyse.")

    ai_act_mode, chat_text, saved_images = _analysis_context(req)
    background_tasks.add_task(
        run_gemini_analysis,
        audio_path=audio_path,
        title=f"Besprechung ({filename})",
        user_name=app_state["current_user_name"],
        chat_text=chat_text,
        image_paths=saved_images,
        ai_act_mode=ai_act_mode,
    )
    app_state["status"] = "processing"
    app_state["process_step"] = f"Starte Analyse für {filename}..."
    return {"success": True, "message": "Analyse gestartet."}


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
    candidates = [os.path.join(RECORDINGS_DIR, audio_base + ext) for ext in (".mp3", ".wav")]
    candidates += [os.path.join(ATTACHMENTS_DIR, os.path.basename(p)) for p in metadata.get("attachments") or []]
    candidates += [md_path, json_path]

    deleted_files = []
    for path in candidates:
        if os.path.isfile(path):
            try:
                os.remove(path)
                deleted_files.append(path)
            except OSError:
                pass

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

    try:
        update_env_file(updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if req.default_ai_act_mode is not None:
        app_state["ai_act_mode"] = req.default_ai_act_mode

    return {"success": True, "message": "Einstellungen gespeichert."}

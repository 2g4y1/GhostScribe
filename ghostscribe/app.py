"""
FastAPI Server for GhostScribe - Meeting Recorder & Analyzer
"""

import base64
import glob
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ghostscribe.analyzer import DEFAULT_MODEL, MeetingAnalyzer, recording_start
from ghostscribe.i18n import available_languages, configured_language, translate
from ghostscribe.recorder import MeetingRecorder
from ghostscribe.utils import APP_URL, PORT, format_duration, print_banner, update_env_file
from ghostscribe.voices import (
    configured_workers,
    delete_profile,
    load_profiles,
    max_workers,
    recognition_enabled,
    rename_speaker,
    save_profile,
    valid_name,
)

load_dotenv(".env")  # the same file update_env_file() writes

logger = logging.getLogger(__name__)


# Hides the frequent /api/status polling requests from the access log,
# so recording messages and progress updates in the terminal stay readable.
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
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        # Always revalidate (cheap with ETag): after an update, page and scripts must come from the same version
        response.headers["Cache-Control"] = "no-cache"
    return response


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Runtime data lives in the working directory (start.bat runs from the app folder)
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
    "pending_recording": None,  # saved recording waiting for chat history, slides and the start of its analysis
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


class RecordingContextRequest(BaseModel):
    """Input added after the recording: corrected title and participants, chat history and slides."""

    title: str | None = None
    participants: str | None = None
    meeting_type: str | None = None
    chat_text: str = ""
    images: list[AttachmentItem] = []


class AnalyzeRequest(RecordingContextRequest):
    ai_act_mode: bool = True
    user_name: str = ""


class SettingsRequest(BaseModel):
    """Every field is optional; only the fields that are sent are changed."""

    api_key: str = ""
    model: str | None = None
    default_ai_act_mode: bool | None = None
    ui_language: str | None = None
    voice_recognition: bool | None = None
    voice_workers: int | None = None


class VoiceNameRequest(BaseModel):
    label: str
    name: str
    consent: bool = False


def api_error(status_code: int, key: str, **params) -> HTTPException:
    """HTTP error with a message in the configured UI language."""
    return HTTPException(status_code=status_code, detail=translate(key, **params))


def _safe_filename(name: str) -> str:
    """Rejects anything but a plain file name (path traversal protection, e.g. '../.env')."""
    if name in ("", ".", "..") or name != os.path.basename(name):
        raise api_error(400, "api.invalid_filename")
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


def _recording_heartbeat(started_at: float):
    """Prints the recording status to the terminal every 5 seconds while this recording runs."""
    while True:
        time.sleep(5)
        if not recorder.is_recording or recorder.start_time != started_at:
            return
        print(
            translate(
                "terminal.heartbeat",
                duration=format_duration(recorder.get_duration()),
                mic=int(recorder.mic_level * 100),
                playback=int(recorder.loopback_level * 100),
            )
        )


@app.get("/")
def get_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def get_favicon():
    return FileResponse(STATIC_DIR / "logo.png", media_type="image/png")


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
        "default_ai_act_mode": _default_ai_act_mode(),
        "voice_recognition": recognition_enabled(),
        "voice_workers": configured_workers(),
        "voice_workers_max": max_workers(),
        "last_meeting_id": app_state["last_meeting_id"],
        "last_error": app_state["last_error"],
        "pending_recording": app_state["pending_recording"],
        "current_title": app_state["current_title"],
        "current_participants": app_state["current_participants"],
        "current_meeting_type": app_state["current_meeting_type"],
        "current_user_name": app_state["current_user_name"],
    }


@app.get("/api/languages")
def list_languages():
    """Available UI languages; current is None until a language was chosen (the UI then uses the browser language)."""
    return {"current": configured_language(), "available": available_languages()}


@app.get("/api/devices")
def list_devices():
    """Selectable microphones and loopback devices (not available while recording)."""
    if recorder.is_recording:
        raise api_error(409, "api.busy")
    try:
        return MeetingRecorder.list_devices()
    except Exception as e:
        raise api_error(500, "api.devices_failed", error=e) from e


@app.post("/api/record/start")
def start_recording(req: StartRequest):
    if app_state["status"] in ["recording", "processing"]:
        raise api_error(400, "api.busy")

    try:
        app_state["current_title"] = req.title.strip()
        app_state["current_participants"] = req.participants.strip()
        app_state["current_meeting_type"] = req.meeting_type.strip() or "standard"
        app_state["current_user_name"] = req.user_name.strip() or "Ich"
        app_state["ai_act_mode"] = req.ai_act_mode
        app_state["last_error"] = None
        app_state["pending_recording"] = None  # an unanalyzed recording stays in the list of recordings
        recorder.start(mic_index=req.mic_device, loopback_index=req.loopback_device)
        app_state["status"] = "recording"
        threading.Thread(target=_recording_heartbeat, args=(recorder.start_time,), daemon=True).start()
    except Exception as e:
        logger.exception("Recording could not be started")
        app_state["status"] = "error"
        app_state["last_error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    rows = [
        ("terminal.topic", app_state["current_title"] or translate("terminal.topic_auto")),
        ("terminal.own_name", translate("terminal.own_name_value", name=app_state["current_user_name"])),
    ]
    if app_state["current_participants"]:
        rows.append(
            ("terminal.participants", translate("terminal.participants_value", names=app_state["current_participants"]))
        )
    rows += [
        ("terminal.microphone", recorder.mic_info["name"]),
        ("terminal.system_audio", recorder.loopback_info["name"]),
        ("terminal.start_time", datetime.now().strftime("%H:%M:%S")),
        ("terminal.web_ui", translate("terminal.web_ui_value", url=APP_URL)),
    ]
    print_banner(
        translate("terminal.recording_started"),
        *(f"   {translate(label):<15}{value}" for label, value in rows),
        "   " + translate("terminal.background_note"),
    )
    return {"success": True, "title": app_state["current_title"]}


@app.post("/api/record/cancel")
def cancel_recording():
    if app_state["status"] != "recording":
        raise api_error(400, "api.no_active_recording")

    recorder.cancel()
    app_state["status"] = "idle"
    app_state["process_step"] = translate("step.cancelled")
    print_banner(translate("terminal.recording_cancelled"))
    return {"success": True}


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
            logger.warning("Could not save attachment %d: %s", idx + 1, e)

    return saved_paths


def _set_step(key: str, **params):
    """Shows a progress message in the web UI and the terminal."""
    app_state["process_step"] = translate(key, **params)
    print(f"   → {app_state['process_step']}")


def run_gemini_analysis(audio_path: str, context: dict):
    """Runs the Gemini analysis. On failure the context file stays, so the recording can be analyzed again."""
    try:
        app_state["status"] = "processing"
        _set_step("step.starting_analysis")

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            app_state["status"] = "idle"
            _set_step("step.saved_without_key")
            return

        MeetingAnalyzer(api_key=api_key).analyze_meeting(
            audio_filepath=audio_path,
            meeting_title=context.get("title", ""),
            participants=context.get("participants", ""),
            meeting_type=context.get("meeting_type", "standard"),
            user_name=context.get("user_name", "Ich"),
            chat_text=context.get("chat_text", ""),
            image_filepaths=context.get("image_paths", []),
            duration=context.get("duration"),
            on_status_update=_set_step,
            ai_act_mode=context.get("ai_act_mode", True),
            voice_recognition=recognition_enabled(),
            voice_workers=configured_workers(),
        )

        audio_base = os.path.splitext(os.path.basename(audio_path))[0]
        _delete_files([_context_path(audio_base)])
        app_state["last_meeting_id"] = audio_base
        app_state["status"] = "idle"
        _set_step("step.done")
    except Exception as e:
        logger.exception("Analysis failed")
        app_state["status"] = "error"
        app_state["last_error"] = str(e)
        app_state["process_step"] = ""


def _save_context(audio_base: str, context: dict):
    with open(_context_path(audio_base), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2, ensure_ascii=False)


def _save_recording(context: dict):
    """Background task after stopping: writes the audio files and the context of the recording.
    The analysis starts from the web interface once chat history and slides could be added."""
    try:
        audio_path = recorder.save(compress=True)
    except Exception as e:
        logger.exception("Audio could not be saved")
        app_state["status"] = "error"
        app_state["last_error"] = translate("error.save_audio_failed", error=e)
        return

    _save_context(os.path.splitext(os.path.basename(audio_path))[0], context)
    print("   " + translate("terminal.audio_saved", path=audio_path))
    app_state["pending_recording"] = os.path.basename(audio_path)
    app_state["status"] = "idle"
    app_state["process_step"] = translate("step.recording_saved")


@app.post("/api/record/stop")
def stop_recording(background_tasks: BackgroundTasks):
    if app_state["status"] != "recording":
        raise api_error(400, "api.no_active_recording")

    recorder.stop_capture()
    context = {
        "title": app_state["current_title"],
        "participants": app_state["current_participants"],
        "meeting_type": app_state["current_meeting_type"],
        "user_name": app_state["current_user_name"],
        "ai_act_mode": app_state["ai_act_mode"],
        "duration": format_duration(recorder.end_time - recorder.start_time),
    }
    app_state["status"] = "processing"
    app_state["process_step"] = translate("step.saving_audio")
    background_tasks.add_task(_save_recording, context)

    mode = translate("mode.ai_act" if context["ai_act_mode"] else "mode.sentiment")
    print_banner(
        translate("terminal.recording_stopped", duration=context["duration"], mode=mode),
        "   " + translate("terminal.waiting_for_analysis"),
    )
    return {"success": True}


@app.get("/api/unprocessed-recordings")
def list_unprocessed_recordings():
    """Recordings without a protocol (e.g. after a failed analysis), one entry each with MP3 preferred."""
    processed = _processed_audio_bases()
    recordings = {}
    for ext in (".wav", ".mp3"):  # MP3 is inserted last and therefore replaces the WAV entry
        for path in glob.glob(os.path.join(RECORDINGS_DIR, "*" + ext)):
            base = os.path.splitext(os.path.basename(path))[0]
            if base not in processed and os.path.getsize(path) >= 10000:  # ignore accidental test clicks
                recordings[base] = path
    items = []
    for base, path in sorted(recordings.items(), reverse=True):
        context = _load_context(base)
        items.append(
            {
                "filename": os.path.basename(path),
                "title": context.get("title", ""),
                "participants": context.get("participants", ""),
                "meeting_type": context.get("meeting_type", "standard"),
                "chat_text": context.get("chat_text", ""),
                "recorded_at": recording_start(path).isoformat(timespec="minutes"),
                "size_kb": round(os.path.getsize(path) / 1024),
            }
        )
    return items


def _complete_context(filename: str, req: RecordingContextRequest, defaults: dict) -> tuple[str, dict]:
    """Saved context of a recording, completed by the input after the recording and saved again for retries."""
    audio_path = _recording_path(filename)
    if not os.path.isfile(audio_path):
        raise api_error(404, "api.audio_not_found")
    audio_base = os.path.splitext(os.path.basename(audio_path))[0]
    # The saved input of the recording (title, mode, earlier chat and slides) takes precedence over the defaults;
    # what was entered after the recording completes or corrects it
    context = {**defaults, **_load_context(audio_base)}
    for key in ("title", "participants", "meeting_type"):
        value = getattr(req, key)
        if value is not None:
            context[key] = value.strip()
    if req.chat_text.strip():
        context["chat_text"] = req.chat_text.strip()
    if req.images:
        context["image_paths"] = [*context.get("image_paths", []), *save_attachments(req.images)]
    _save_context(audio_base, context)
    if app_state["pending_recording"] == os.path.basename(audio_path):
        app_state["pending_recording"] = None
    return audio_path, context


@app.put("/api/recordings/{filename}/context")
def save_recording_context(filename: str, req: RecordingContextRequest):
    """Keeps title, chat history and slides of a recording that is analyzed later."""
    _complete_context(filename, req, {})
    return {"success": True}


@app.post("/api/recordings/{filename}/analyze")
def analyze_existing_recording(filename: str, background_tasks: BackgroundTasks, req: AnalyzeRequest | None = None):
    if app_state["status"] in ["recording", "processing"]:
        raise api_error(400, "api.busy")
    req = req or AnalyzeRequest(ai_act_mode=_default_ai_act_mode())
    defaults = {"ai_act_mode": req.ai_act_mode, "user_name": req.user_name.strip() or "Ich"}
    audio_path, context = _complete_context(filename, req, defaults)

    app_state["status"] = "processing"
    app_state["process_step"] = translate("step.starting_analysis_for", name=filename)
    app_state["last_error"] = None
    background_tasks.add_task(run_gemini_analysis, audio_path, context)

    lines = [translate("terminal.analysis_started", name=filename)]
    if context.get("chat_text"):
        lines.append("   " + translate("terminal.chat_attached", count=len(context["chat_text"])))
    if context.get("image_paths"):
        lines.append("   " + translate("terminal.screenshots_attached", count=len(context["image_paths"])))
    print_banner(*lines)
    return {"success": True}


@app.delete("/api/recordings/{filename}")
def delete_recording(filename: str):
    """Deletes a recording without protocol: MP3, WAV original, saved context and screenshots."""
    audio_base = os.path.splitext(_safe_filename(filename))[0]
    if app_state["status"] in ["recording", "processing"]:
        raise api_error(400, "api.busy")
    if audio_base in _processed_audio_bases():
        raise api_error(409, "api.recording_has_protocol")

    deleted_files = _delete_files(_recording_files(audio_base))
    if not deleted_files:
        raise api_error(404, "api.recording_not_found")
    if os.path.splitext(app_state["pending_recording"] or "")[0] == audio_base:
        app_state["pending_recording"] = None
    return {"success": True, "deleted_files": deleted_files}


def _without_fingerprints(meta: dict) -> dict:
    """Meeting metadata for the web interface: the voice fingerprints (biometric data) stay on the server."""
    voices = [{k: v for k, v in voice.items() if k != "embedding"} for voice in meta.get("voices", [])]
    return {**meta, "voices": voices}


@app.get("/api/meetings")
def list_meetings():
    """All protocols, newest meeting first. Not sorted by file date: a retried analysis writes an older meeting later."""
    meetings = []
    for jf in glob.glob(os.path.join(MEETINGS_DIR, "*.json")):
        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
                base_id = os.path.splitext(os.path.basename(jf))[0]
                data["id"] = base_id

                # Full text for the search (transcript, discussion, decisions)
                md_path = os.path.join(MEETINGS_DIR, f"{base_id}.md")
                if os.path.exists(md_path):
                    with open(md_path, encoding="utf-8") as mf:
                        data["content"] = mf.read()
                else:
                    data["content"] = ""

                meetings.append(_without_fingerprints(data))
        except Exception:
            continue
    meetings.sort(key=lambda m: m.get("meeting_start") or m.get("created_at") or "", reverse=True)
    return meetings


@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str):
    json_path, md_path = _meeting_paths(meeting_id)

    if not os.path.exists(json_path) or not os.path.exists(md_path):
        raise api_error(404, "api.meeting_not_found")

    with open(json_path, encoding="utf-8") as f:
        meta = json.load(f)

    with open(md_path, encoding="utf-8") as f:
        markdown = f.read()

    audio_filename = os.path.basename(meta.get("audio_file", ""))
    return {
        "metadata": _without_fingerprints(meta),
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
        raise api_error(404, "api.meeting_not_found")

    if app_state["last_meeting_id"] == meeting_id:
        app_state["last_meeting_id"] = None

    return {"success": True, "deleted_files": deleted_files}


@app.get("/recordings/{filename}")
def get_audio_file(filename: str):
    filepath = _recording_path(filename)
    if not os.path.isfile(filepath):
        raise api_error(404, "api.audio_not_found")
    media_type = "audio/mpeg" if filename.lower().endswith(".mp3") else "audio/wav"
    return FileResponse(filepath, media_type=media_type)


@app.get("/api/voices")
def list_voice_profiles():
    """Saved voice profiles without their fingerprints."""
    return [{key: p[key] for key in ("id", "name", "seconds", "samples", "updated_at")} for p in load_profiles()]


@app.delete("/api/voices/{profile_id}")
def delete_voice_profile(profile_id: str):
    if not delete_profile(profile_id):
        raise api_error(404, "api.voice_profile_not_found")
    return {"success": True}


@app.post("/api/meetings/{meeting_id}/voices")
def name_voice(meeting_id: str, req: VoiceNameRequest):
    """Names a voice of the meeting: saves the voice profile (consent required) and updates the minutes."""
    json_path, md_path = _meeting_paths(meeting_id)
    if not os.path.exists(json_path) or not os.path.exists(md_path):
        raise api_error(404, "api.meeting_not_found")
    if not req.consent:
        raise api_error(400, "api.voice_consent_required")
    name = req.name.strip()
    if not valid_name(name):
        raise api_error(400, "api.invalid_voice_name")

    with open(json_path, encoding="utf-8") as f:
        meta = json.load(f)
    voice = next((v for v in meta.get("voices", []) if v["label"] == req.label), None)
    if voice is None:
        raise api_error(404, "api.voice_not_found")

    profile = save_profile(name, voice["embedding"], voice["seconds"])
    with open(md_path, encoding="utf-8") as f:
        markdown = rename_speaker(f.read(), voice["label"], name)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    voice.update(label=name, profile_id=profile["id"], similarity=None, confirmed=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return {"success": True}


@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    updates = {}
    if req.model is not None:
        updates["GEMINI_MODEL"] = req.model.strip() or DEFAULT_MODEL
    # Only update when a real key was sent, not the masked placeholder (• or *)
    new_key = req.api_key.strip()
    if new_key and "•" not in new_key and "*" not in new_key:
        updates["GEMINI_API_KEY"] = new_key
    if req.default_ai_act_mode is not None:
        updates["AI_ACT_MODE"] = "true" if req.default_ai_act_mode else "false"
    if req.ui_language is not None:
        if req.ui_language not in available_languages():
            raise api_error(400, "api.unknown_language", language=req.ui_language)
        updates["UI_LANGUAGE"] = req.ui_language
    if req.voice_recognition is not None:
        updates["VOICE_RECOGNITION"] = "true" if req.voice_recognition else "false"
    if req.voice_workers is not None:
        if not 1 <= req.voice_workers <= max_workers():
            raise api_error(400, "api.invalid_setting")
        updates["VOICE_WORKERS"] = str(req.voice_workers)

    try:
        update_env_file(updates)
    except ValueError as e:
        raise api_error(400, "api.invalid_setting") from e

    return {"success": True}

<div align="center">
  <img src="ghostscribe/static/logo.png" alt="GhostScribe logo" width="120">

# GhostScribe

**Bot-free meeting recorder for Windows that turns Teams and Zoom calls into structured minutes with Google Gemini.**

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)
![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6)
![Python 3.11–3.14](https://img.shields.io/badge/Python-3.11--3.14-3776AB)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

</div>

![Recording in progress](docs/screenshots/recording.png)

GhostScribe records your microphone and your computer's audio output as two separate channels, so no meeting bot has to join the call. When you stop the recording, Gemini turns it into structured minutes with summary, decisions and action items. The interface is available in English and German; the minutes are currently written in German.

## Features

- **Two-channel recording:** microphone and system audio (WASAPI loopback) are stored on separate channels; a channel timeline tells Gemini when you and when the others were speaking.
- **Structured minutes:** management summary, decisions, prioritized action items, open questions and a cleaned-up transcript (condensed to key quotes for meetings over 45 minutes), with focus templates for sprints, sales calls, interviews and brainstorming.
- **Meeting context:** add chat history, notes and screenshots of shared slides (paste with Ctrl+V).
- **EU AI Act mode (default):** no emotion or sentiment analysis. The optional sentiment mode requires explicit confirmation.
- **Local storage:** recordings and minutes stay on your PC; files uploaded to Gemini are deleted after the analysis.
- **Search and playback:** full-text search across all meetings; play back both channels, only yourself or only the other participants.

## Requirements

- Windows 10 or 11 (x64)
- Python 3.11 to 3.14
- A Google Gemini API key, free at [Google AI Studio](https://aistudio.google.com/app/apikey)
- Optional: [FFmpeg](https://ffmpeg.org/) in `PATH`, which compresses recordings to MP3 so that uploads are about five times smaller

## Installation

1. Download `GhostScribe-v1.0.0-windows.zip` from the [latest release](../../releases/latest) and extract it.
2. Double-click `start.bat`. The first start creates a virtual environment and installs the dependencies; no admin rights are needed.
3. The browser opens http://localhost:8765. Enter your Gemini API key under **Settings**, where you can also switch the language.

To run from source instead, clone the repository and start `start.bat` in the same way. `.venv\Scripts\python -m ghostscribe --cli` starts a terminal version without the web interface.

## Usage

1. Select your microphone and the output device your meeting app plays through, and optionally enter topic, participants and meeting type.
2. Click **Start recording**. The recording continues even if you close the browser tab, as long as the GhostScribe console window stays open.
3. Optionally add chat history, notes or screenshots of shared slides during the meeting. They are kept in the open tab and sent when you stop the recording:

   ![Meeting context with chat history and two slides](docs/screenshots/attachments.png)

4. Click **Stop & analyze**. Gemini then writes the minutes in the background, which takes from under a minute to a few minutes depending on the length of the recording. They open automatically when ready:

   ![Saved meetings with minutes and audio playback](docs/screenshots/protocol.png)

If an analysis fails, for example because of a rate limit, the recording is listed under **Recordings not yet analyzed** and can be analyzed again.

## Configuration

Settings are stored in `.env`, which is created from `.env.example` and can be edited in the web interface.

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-flash-latest` | Gemini model used for the minutes |
| `AI_ACT_MODE` | `true` | Default mode: `true` is EU AI Act compliant, `false` adds sentiment analysis |
| `UI_LANGUAGE` | browser language | Interface language, for example `en` or `de` |

## Adding a language

Each language is one JSON file in `ghostscribe/static/locales/`. Copy `en.json` to a file named after the two-letter language code (for example `fr.json`), translate the values, keep the `{placeholders}`, and set `meta.name` (shown in the language list) and `meta.locale` (date and number format). After a restart, the language appears in the settings. `pytest` checks that every language has the same keys and placeholders as English.

## Privacy and legal notes

- Recordings (`recordings/`) and minutes (`meetings/`) are stored locally only.
- For the analysis, the audio file, the attached screenshots and the entered context (topic, participants, chat and notes) are sent to the Google Gemini API; uploaded files are deleted there afterwards. [Google's API terms](https://ai.google.dev/gemini-api/terms) apply; on the free tier, Google may use submitted content to improve its products.
- **Inform all participants and get their consent before recording.** Recording conversations without consent is a criminal offence in many countries (for example § 201 StGB in Germany), and processing voice data is subject to the GDPR.
- The EU AI Act prohibits emotion recognition in the workplace and in education (Art. 5(1)(f)). Keep the default mode for meetings at work or in education.

## Development

```
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest
python scripts/build_release.py
```

The application is the `ghostscribe` package (`python -m ghostscribe`): `app.py` serves the web interface and API, `recorder.py` captures the audio, `analyzer.py` runs the Gemini analysis, and `static/` contains the web interface. `scripts/build_release.py` creates `dist/GhostScribe-v<version>-windows.zip`, which contains only the files end users need.

## License

[MIT](LICENSE)

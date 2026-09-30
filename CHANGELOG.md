# Changelog

All notable changes to GhostScribe are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-09-30

The first release.

### Added

- Bot-free two-channel recording of the microphone and the system audio on Windows (WASAPI loopback of the playback
  device), Linux (its PulseAudio/PipeWire monitor) and macOS (a virtual audio device such as BlackHole); a channel
  timeline tells Gemini when you and when the others were speaking.
- Crash-safe recording: the audio is written to disk while recording, and a recording that was interrupted by a
  crash or a closed console window is recovered at the next start. Both channels stay in time even if an input
  delivers nothing for a while.
- Pause and resume a recording (web interface and **P** in the terminal version): the pause is cut out of the
  recording, both channels stay in sync, and Gemini is told where parts of the meeting are missing.
- Structured minutes with Google Gemini, with focus templates for sprints, sales calls, interviews and brainstorming;
  the EU AI Act compliant mode (no emotion analysis) is the default.
- Meeting context after the recording: chat history, notes and screenshots of shared slides.
- Optional local voice recognition with voice profiles that are only saved with the person's consent.
- Full-text search across all meetings, playback of every recording, renaming of meetings.
- Web interface and terminal version in English and German; `--version` and `--help` on the command line.
- Console window with the address and its keys always at the bottom: **R** restarts the server after a question that
  appears right there with a countdown, **D** puts a shortcut on the desktop (Windows, macOS and Linux, where it also
  goes into the applications menu).
- Portable release archive with start scripts for Windows (`start.bat`), macOS (`start.command`) and Linux
  (`start.sh`) that install the dependencies from lock files with pinned checksums.

### Security

- The web interface is only reachable from this computer and rejects requests from other websites (Host, Origin
  and Fetch Metadata checks) as well as framing; a strict Content-Security-Policy allows no inline scripts or styles.
- Attachments must be PNG, JPEG or WebP images; only audio files are served from the recordings folder.
- Releases are built reproducibly with a SHA-256 checksum and a signed build provenance.

[Unreleased]: https://github.com/2g4y1/GhostScribe/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/2g4y1/GhostScribe/releases/tag/v1.0.0

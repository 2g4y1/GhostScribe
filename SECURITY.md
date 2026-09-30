# Security policy

GhostScribe handles recordings of conversations, minutes, a Google API key and optionally voice profiles (biometric
data), so security reports are very welcome.

## Supported versions

Security fixes are made for the latest release.

## Reporting a vulnerability

Please do **not** open a public issue. Report it privately via
[GitHub's private vulnerability reporting](https://github.com/2g4y1/GhostScribe/security/advisories/new) (Security tab →
"Report a vulnerability"). Include the affected version, the steps to reproduce and the impact you expect. You will
get an answer within a week; please give us a reasonable time to fix the problem before you disclose it.

## Design notes

- The web server only listens on 127.0.0.1. It rejects requests with a foreign `Host` (DNS rebinding) or `Origin`
  header (CSRF) and requests that browsers mark as coming from other websites, and it sends a strict
  Content-Security-Policy that also forbids framing the interface.
- Minutes are rendered with DOMPurify; file names in the API are checked against path traversal.
- Settings, including the API key, are stored in `.env` in the application folder. Recordings, minutes and voice
  profiles are stored unencrypted in the application folder; protect it like any other personal data.
- Dependencies are installed from lock files with SHA-256 checksums; the voice recognition models are checked against
  their checksums after the download.

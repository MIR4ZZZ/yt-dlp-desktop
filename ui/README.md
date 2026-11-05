# Unofficial yt-dlp Desktop

A community-built Windows desktop interface for yt-dlp, built with PySide6.
This application is not published by the yt-dlp maintainers.

## Download workflow

Paste a link and choose Video or Audio. Analyze to see a title and, for playlists,
the Full playlist / Single video / Range choice. If analysis is unavailable,
Download with defaults remains available. Options holds subtitles, metadata,
overwrite behavior, and expert arguments. Settings holds the default folder,
network limits, and explicit session-only browser or cookie-file access.
Download and Add to queue each ask you to confirm a destination before creating
the job.

## Run from source

```powershell
python -m pip install -e ".[default,gui]"
python -m ui
```

The source version uses this checkout's `python -m yt_dlp` engine. It uses FFmpeg
from `PATH` when available. Build from the 2026.10.26 upstream tag; the release
script checks that the upstream engine source is unchanged.

## Build the Windows installer

```powershell
powershell -ExecutionPolicy Bypass -File ui\build_windows_exe.ps1
```

The build creates a per-user installer containing:

- The PySide6 desktop app
- A yt-dlp 2026.10.26 Windows engine built from this checkout with EJS scripts
- A bundled, SHA-256-verified Deno runtime for YouTube challenges
- Bundled FFmpeg and FFprobe binaries (the default download is SHA-256 verified)
- Matching license and third-party notice files

Inno Setup 6 must be installed. The script creates an isolated Python environment
under `build`, verifies pinned Deno and FFmpeg archives, and writes a release
manifest, dependency list, and FFmpeg source archives beside the unsigned preview
installer. Keep the installer and source archives together when distributing it.

## Privacy

Settings and the latest 100 successful downloads are stored under
`%LOCALAPPDATA%\yt-dlp-ui`. Passwords, proxy settings, cookie contents, failed
downloads, logs, queued jobs, and advanced arguments are not persisted. Links
with credential-like query fields are omitted from history; retrying them asks
for the original link again.

The unsigned preview can trigger Windows SmartScreen warnings. Do not publish
it as a stable release until clean Windows 10/11 acceptance checks and the
third-party source and notice review have passed.

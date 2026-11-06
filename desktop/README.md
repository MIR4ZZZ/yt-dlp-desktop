# Unofficial yt-dlp Desktop

An independent Windows 10/11 x64 desktop interface for yt-dlp. The UI is
Svelte and TypeScript inside Tauri 2; Rust builds argument lists and runs a
bundled yt-dlp engine. Downloads are sequential. The program does not ask for
passwords or read browser cookies without an explicit session choice.

## Source development

This `desktop` directory lives beside a clean checkout of yt-dlp
`2026.10.26`. Install the Windows MSVC Rust toolchain, Node.js, and WebView2.
Run `npm ci` then `npm run tauri dev` here. For a local engine, set
`YTDLP_DESKTOP_ENGINE` to an absolute `yt-dlp.exe` path and
`YTDLP_DESKTOP_TOOLS` to a folder containing FFmpeg and FFprobe.

## Preview build

From the repository root, run `powershell -ExecutionPolicy Bypass -File
desktop\build_payload.ps1`. It verifies pinned Deno, shared FFmpeg, and
WebView2 downloads already in `build`, rebuilds yt-dlp from this source, builds
the Tauri executable, and produces a versioned payload ZIP and SHA-256
manifest under `dist\tauri-preview`. The payload is roughly 145 MB.

The online setup is built only after that exact ZIP is uploaded to a public
GitHub Release. Run `desktop\build_online_installer.ps1 -PayloadUrl <anonymous
release asset URL>`; it downloads the asset anonymously, verifies its hash,
pins that hash in Inno Setup, and rejects an installer at or above 20,000,000
bytes. The setup detects WebView2, installs Microsoft's Evergreen runtime if
missing, downloads the app ZIP, verifies it, and extracts to the current
user's Local AppData. It has a separate AppId and folder from the Qt preview.

The current artifacts are **unsigned local preview candidates**. Public
publication requires clean Windows 10 and 11 install, cancellation, scaling,
and notice checks. No automatic updater is included.

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlparse


PROGRESS_PREFIX = "__YTDLP_PROGRESS__"
DEFAULT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"

VIDEO_FORMATS = {
    "Best": "bv*+ba/b",
    "2160p": "bv*[height<=2160]+ba/b[height<=2160]",
    "1440p": "bv*[height<=1440]+ba/b[height<=1440]",
    "1080p": "bv*[height<=1080]+ba/b[height<=1080]",
    "720p": "bv*[height<=720]+ba/b[height<=720]",
    "480p": "bv*[height<=480]+ba/b[height<=480]",
}


@dataclass(slots=True)
class DownloadSpec:
    url: str
    output_dir: str
    title: str = ""
    mode: str = "video"
    video_quality: str = "Best"
    video_container: str = "Auto"
    audio_format: str = "mp3"
    subtitle_mode: str = "None"
    subtitle_languages: str = "en"
    automatic_subtitles: bool = False
    embed_metadata: bool = True
    embed_thumbnail: bool = False
    playlist_mode: str = "Single video"
    playlist_start: int | None = None
    playlist_end: int | None = None
    overwrite: str = "Skip existing"
    cookie_source: str = "None"
    browser: str = "chrome"
    cookie_file: str = ""
    proxy: str = ""
    rate_limit_kbps: int | None = None
    retries: int = 10
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    def safe_dict(self) -> dict:
        data = asdict(self)
        data["extra_args"] = []
        data["cookie_source"] = "None"
        data["cookie_file"] = ""
        data.pop("proxy", None)
        data["url"] = history_safe_url(self.url)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> DownloadSpec:
        allowed = cls.__dataclass_fields__
        values = {key: value for key, value in data.items() if key in allowed}
        values["extra_args"] = tuple(values.get("extra_args", ()))
        return cls(**values)


@dataclass(slots=True)
class QueueJob:
    job_id: str
    spec: DownloadSpec
    status: str = "Queued"
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    log: list[str] = field(default_factory=list)


def validate_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a complete http:// or https:// link.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Remove the username or password from the link before continuing.")
    return value


def history_safe_url(value: str) -> str:
    """Keep ordinary links retryable without retaining obvious URL credentials."""
    try:
        parsed = urlparse(validate_url(value))
    except ValueError:
        return ""
    sensitive = re.compile(r"(?:token|auth|key|sig|secret|pass|session|cookie|credential|code)", re.I)
    if any(sensitive.search(name) for name, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        return ""
    return parsed._replace(fragment="").geturl()


def _authentication_args(spec: DownloadSpec) -> list[str]:
    if spec.cookie_source == "Browser":
        return ["--cookies-from-browser", spec.browser]
    if spec.cookie_source == "Cookie file":
        return ["--cookies", spec.cookie_file]
    return []


def _network_args(spec: DownloadSpec) -> list[str]:
    args = ["--retries", str(max(0, spec.retries))]
    if spec.proxy:
        args += ["--proxy", spec.proxy]
    if spec.rate_limit_kbps:
        args += ["--limit-rate", f"{spec.rate_limit_kbps}K"]
    return args


def build_analysis_args(spec: DownloadSpec) -> list[str]:
    return [
        "--dump-single-json",
        "--flat-playlist",
        "--skip-download",
        "--socket-timeout", "10",
        "--retries", "1",
        "--no-warnings",
        "--no-colors",
        *_authentication_args(spec),
        *(["--proxy", spec.proxy] if spec.proxy else []),
        "--",
        validate_url(spec.url),
    ]


def build_download_args(spec: DownloadSpec, ffmpeg_dir: str | None = None) -> list[str]:
    url = validate_url(spec.url)
    if not spec.output_dir.strip():
        raise ValueError("Choose a download folder.")
    output_dir = str(Path(spec.output_dir).expanduser())

    args = [
        "--newline",
        "--no-colors",
        "--progress-template",
        f"download:{PROGRESS_PREFIX}%(progress)j",
        "--paths",
        output_dir,
        "--output",
        DEFAULT_TEMPLATE,
        *_network_args(spec),
        *_authentication_args(spec),
    ]
    if ffmpeg_dir:
        args += ["--ffmpeg-location", ffmpeg_dir]

    if spec.overwrite == "Overwrite":
        args.append("--force-overwrites")
    else:
        args.append("--no-overwrites")

    if spec.playlist_mode == "Full playlist":
        args.append("--yes-playlist")
    elif spec.playlist_mode == "Playlist range":
        args.append("--yes-playlist")
        if spec.playlist_start is not None:
            args += ["--playlist-start", str(spec.playlist_start)]
        if spec.playlist_end is not None:
            args += ["--playlist-end", str(spec.playlist_end)]
    else:
        args.append("--no-playlist")

    if spec.mode == "audio":
        args += ["--extract-audio", "--audio-format", spec.audio_format, "--audio-quality", "0"]
    else:
        args += ["--format", VIDEO_FORMATS.get(spec.video_quality, VIDEO_FORMATS["Best"])]
        if spec.video_container in {"MP4", "MKV"}:
            args += ["--remux-video", spec.video_container.lower()]

    if spec.subtitle_mode != "None":
        args.append("--write-subs")
        if spec.automatic_subtitles:
            args.append("--write-auto-subs")
        languages = ",".join(part.strip() for part in spec.subtitle_languages.split(",") if part.strip())
        if languages:
            args += ["--sub-langs", languages]
        if spec.subtitle_mode == "Embed":
            args.append("--embed-subs")

    if spec.embed_metadata:
        args.append("--embed-metadata")
    if spec.embed_thumbnail:
        args.append("--embed-thumbnail")

    args += list(spec.extra_args)
    args += ["--", url]
    return args


def parse_progress_line(line: str) -> dict | None:
    line = line.strip()
    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        value = json.loads(line[len(PROGRESS_PREFIX):])
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def progress_values(data: dict) -> tuple[float, str, str]:
    percent = data.get("_percent_str") or data.get("percent") or ""
    match = re.search(r"(\d+(?:\.\d+)?)", str(percent))
    value = min(100.0, max(0.0, float(match.group(1)))) if match else 0.0
    speed = str(data.get("_speed_str") or data.get("speed") or "").strip()
    eta = str(data.get("_eta_str") or data.get("eta") or "").strip()
    return value, speed, eta

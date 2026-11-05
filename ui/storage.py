from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 2
DEFAULT_SETTINGS = {
    "schema_version": SCHEMA_VERSION,
    "download_dir": str(Path.home() / "Videos"),
    "open_folder_on_done": True,
    "mode": "video",
    "video_quality": "Best",
    "video_container": "Auto",
    "audio_format": "mp3",
    "subtitle_mode": "None",
    "subtitle_languages": "en",
    "automatic_subtitles": False,
    "embed_metadata": True,
    "embed_thumbnail": False,
    "overwrite": "Skip existing",
    "retries": 10,
    "rate_limit_kbps": None,
}

CHOICES = {
    "mode": {"video", "audio"},
    "video_quality": {"Best", "2160p", "1440p", "1080p", "720p", "480p"},
    "video_container": {"Auto", "MP4", "MKV"},
    "audio_format": {"mp3", "m4a", "opus", "flac", "wav"},
    "subtitle_mode": {"None", "Embed", "Separate file"},
    "overwrite": {"Skip existing", "Overwrite"},
}


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    return Path(base) / "yt-dlp-ui"


class JsonStore:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or default_data_dir()
        self.settings_path = self.data_dir / "settings.json"
        self.history_path = self.data_dir / "history.json"

    @staticmethod
    def _backup(path: Path) -> None:
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
                redacted = re.sub(
                    r'("(?:proxy|cookie_file|url|extra_args)"\s*:\s*)"(?:\\.|[^"\\])*"',
                    r'\1"[redacted]"', raw, flags=re.I,
                )
                path.with_name(f"{path.stem}.corrupt-{stamp}.bak").write_text(redacted, encoding="utf-8")
                path.unlink()
            except OSError:
                pass

    def _read(self, path: Path, default):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value
        except FileNotFoundError:
            return deepcopy(default)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self._backup(path)
            return deepcopy(default)

    def _write(self, path: Path, value) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)

    def load_settings(self) -> dict:
        loaded = self._read(self.settings_path, DEFAULT_SETTINGS)
        if not isinstance(loaded, dict) or loaded.get("schema_version", 1) not in (1, SCHEMA_VERSION):
            self._backup(self.settings_path)
            return deepcopy(DEFAULT_SETTINGS)
        settings = deepcopy(DEFAULT_SETTINGS)
        settings.update({key: value for key, value in loaded.items() if key in settings})
        settings["schema_version"] = SCHEMA_VERSION
        for key, value in settings.items():
            if key == "schema_version":
                continue
            if key in CHOICES:
                valid = isinstance(value, str) and value in CHOICES[key]
            elif key in {"download_dir", "subtitle_languages"}:
                valid = isinstance(value, str)
            elif key in {"open_folder_on_done", "automatic_subtitles", "embed_metadata", "embed_thumbnail"}:
                valid = isinstance(value, bool)
            elif key == "retries":
                valid = type(value) is int and 0 <= value <= 1000
            else:
                valid = value is None or (type(value) is int and 0 <= value <= 100000000)
            if not valid:
                self._backup(self.settings_path)
                return deepcopy(DEFAULT_SETTINGS)
        if "proxy" in loaded or loaded.get("schema_version") != SCHEMA_VERSION:
            self.save_settings(settings)
        return settings

    def save_settings(self, settings: dict) -> None:
        safe = deepcopy(DEFAULT_SETTINGS)
        safe.update({key: value for key, value in settings.items() if key in safe})
        safe["schema_version"] = SCHEMA_VERSION
        self._write(self.settings_path, safe)

    def load_history(self) -> list[dict]:
        loaded = self._read(self.history_path, {"schema_version": SCHEMA_VERSION, "items": []})
        if not isinstance(loaded, dict) or not isinstance(loaded.get("items"), list):
            self._backup(self.history_path)
            return []
        history = []
        for item in loaded["items"][:100]:
            if not isinstance(item, dict):
                continue
            history.append(self._clean_history_item(item))
        if history != loaded["items"] or loaded.get("schema_version") != SCHEMA_VERSION:
            self._write(self.history_path, {"schema_version": SCHEMA_VERSION, "items": history})
        return history

    def add_success(self, item: dict) -> list[dict]:
        history = self.load_history()
        clean = self._clean_history_item(item)
        clean["completed_at"] = clean.get("completed_at") or datetime.now(timezone.utc).isoformat()
        history.insert(0, clean)
        history = history[:100]
        self._write(self.history_path, {"schema_version": SCHEMA_VERSION, "items": history})
        return history

    @staticmethod
    def _clean_history_item(item: dict) -> dict:
        from .core import history_safe_url

        clean = dict(item)
        for key in ("proxy", "cookie_source", "cookie_file", "extra_args"):
            clean.pop(key, None)
        previous_url = str(clean.get("url") or "")
        safe_url = history_safe_url(previous_url)
        clean["url"] = safe_url
        if not safe_url and clean.get("title") == previous_url:
            clean["title"] = "Completed download"
        spec = clean.get("spec")
        if isinstance(spec, dict):
            spec = dict(spec)
            spec["url"] = safe_url
            for key in ("proxy", "cookie_source", "cookie_file", "browser", "extra_args"):
                spec.pop(key, None)
            clean["spec"] = spec
        return clean

    def clear_history(self) -> None:
        self._write(self.history_path, {"schema_version": SCHEMA_VERSION, "items": []})

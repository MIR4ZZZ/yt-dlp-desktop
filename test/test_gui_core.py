import json
from pathlib import Path

import pytest

from ui.core import (
    PROGRESS_PREFIX,
    DownloadSpec,
    build_analysis_args,
    build_download_args,
    history_safe_url,
    parse_progress_line,
    progress_values,
    validate_url,
)
from ui.storage import JsonStore


def make_spec(tmp_path, **changes):
    values = {
        "url": "https://example.com/watch?v=abc",
        "output_dir": str(tmp_path),
    }
    values.update(changes)
    return DownloadSpec(**values)


def test_validate_url_accepts_http_and_rejects_commands():
    assert validate_url(" https://example.com/video ") == "https://example.com/video"
    with pytest.raises(ValueError):
        validate_url("example.com/video")
    with pytest.raises(ValueError):
        validate_url("--exec calc.exe")
    with pytest.raises(ValueError):
        validate_url("https://name:secret@example.com/video")
    assert history_safe_url("https://example.com/watch?v=abc#chapter") == "https://example.com/watch?v=abc"
    assert history_safe_url("https://example.com/video?access_token=secret") == ""


def test_analysis_arguments_keep_url_after_separator(tmp_path):
    args = build_analysis_args(make_spec(tmp_path, cookie_source="Browser", browser="firefox"))
    assert args[-2:] == ["--", "https://example.com/watch?v=abc"]
    assert args[args.index("--cookies-from-browser") + 1] == "firefox"
    assert args[args.index("--retries") + 1] == "1"
    assert args[args.index("--socket-timeout") + 1] == "10"


def test_download_rejects_empty_folder(tmp_path):
    with pytest.raises(ValueError, match="folder"):
        build_download_args(make_spec(tmp_path, output_dir=""))


def test_video_download_arguments_cover_playlist_subtitles_and_metadata(tmp_path):
    spec = make_spec(
        tmp_path,
        video_quality="1080p",
        video_container="MP4",
        subtitle_mode="Embed",
        subtitle_languages="en, es",
        automatic_subtitles=True,
        embed_thumbnail=True,
        playlist_mode="Playlist range",
        playlist_start=2,
        playlist_end=4,
        extra_args=("--sleep-requests", "1"),
    )
    args = build_download_args(spec, r"C:\Tools\ffmpeg")
    assert args[args.index("--format") + 1] == "bv*[height<=1080]+ba/b[height<=1080]"
    assert args[args.index("--remux-video") + 1] == "mp4"
    assert args[args.index("--playlist-start") + 1] == "2"
    assert args[args.index("--playlist-end") + 1] == "4"
    assert "--embed-subs" in args
    assert "--write-auto-subs" in args
    assert "--embed-metadata" in args
    assert "--embed-thumbnail" in args
    assert args[-4:] == ["--sleep-requests", "1", "--", spec.url]


def test_audio_arguments_and_cookie_file(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File", encoding="utf-8")
    spec = make_spec(
        tmp_path,
        mode="audio",
        audio_format="flac",
        cookie_source="Cookie file",
        cookie_file=str(cookie_file),
    )
    args = build_download_args(spec)
    assert args[args.index("--audio-format") + 1] == "flac"
    assert args[args.index("--cookies") + 1] == str(cookie_file)
    assert "--extract-audio" in args


def test_progress_parser_handles_json_and_partial_values():
    line = PROGRESS_PREFIX + json.dumps({"_percent_str": " 42.5%", "_speed_str": "2.1MiB/s", "_eta_str": "00:08"})
    parsed = parse_progress_line(line)
    assert parsed is not None
    assert progress_values(parsed) == (42.5, "2.1MiB/s", "00:08")
    assert parse_progress_line(PROGRESS_PREFIX + "not-json") is None
    assert parse_progress_line("normal output") is None


def test_settings_recover_from_corrupt_json(tmp_path):
    store = JsonStore(tmp_path)
    store.settings_path.write_text("{broken", encoding="utf-8")
    settings = store.load_settings()
    assert settings["video_quality"] == "Best"
    assert list(tmp_path.glob("settings.corrupt-*.bak"))


def test_settings_recover_from_valid_json_with_bad_types(tmp_path):
    store = JsonStore(tmp_path)
    store.settings_path.write_text('{"schema_version": 2, "retries": "bad"}', encoding="utf-8")
    assert store.load_settings()["retries"] == 10
    assert list(tmp_path.glob("settings.corrupt-*.bak"))


def test_old_proxy_values_are_removed_from_settings_and_history(tmp_path):
    store = JsonStore(tmp_path)
    store.settings_path.write_text('{"schema_version": 1, "proxy": "http://name:secret@proxy.example"}', encoding="utf-8")
    store.history_path.write_text(json.dumps({"schema_version": 1, "items": [{
        "url": "https://example.com/watch?v=abc", "title": "Video", "spec": {
            "url": "https://example.com/watch?v=abc", "proxy": "http://name:secret@proxy.example",
        },
    }]}), encoding="utf-8")
    assert "proxy" not in store.load_settings()
    assert "secret" not in store.settings_path.read_text(encoding="utf-8")
    history = store.load_history()
    assert "proxy" not in history[0]["spec"]
    assert "secret" not in store.history_path.read_text(encoding="utf-8")


def test_corrupt_backup_redacts_old_proxy_password(tmp_path):
    store = JsonStore(tmp_path)
    store.settings_path.write_text('{"proxy":"http://name:secret@proxy.example", broken', encoding="utf-8")
    store.load_settings()
    backup = next(tmp_path.glob("settings.corrupt-*.bak"))
    assert "secret" not in backup.read_text(encoding="utf-8")


def test_storage_sanitizes_new_success_even_when_called_directly(tmp_path):
    store = JsonStore(tmp_path)
    store.add_success({"url": "https://example.com/?access_token=secret", "title": "Private", "spec": {
        "url": "https://example.com/?access_token=secret", "proxy": "http://name:secret@proxy.example",
    }})
    assert "secret" not in store.history_path.read_text(encoding="utf-8")


def test_history_keeps_only_latest_100_successes(tmp_path):
    store = JsonStore(tmp_path)
    for number in range(105):
        store.add_success({"title": f"Video {number}", "url": f"https://example.com/{number}"})
    history = store.load_history()
    assert len(history) == 100
    assert history[0]["title"] == "Video 104"
    assert history[-1]["title"] == "Video 5"


def test_safe_history_spec_drops_authentication_and_expert_arguments(tmp_path):
    spec = make_spec(
        tmp_path,
        cookie_source="Cookie file",
        cookie_file=str(Path(tmp_path) / "secret.txt"),
        extra_args=("--exec", "something"),
        proxy="http://name:secret@proxy.example",
    )
    safe = spec.safe_dict()
    assert safe["cookie_source"] == "None"
    assert safe["cookie_file"] == ""
    assert safe["extra_args"] == []
    assert "proxy" not in safe

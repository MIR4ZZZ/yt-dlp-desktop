import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QLineEdit, QMessageBox, QScrollArea

from ui.app import MainWindow, resolve_engine
from ui.core import DownloadSpec, QueueJob
from ui.process import QueueController


def test_frozen_app_never_uses_its_own_executable_as_engine(tmp_path, monkeypatch):
    monkeypatch.setattr("ui.app.install_root", lambda: tmp_path)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    command = resolve_engine()
    assert command.program == str(tmp_path / "engine" / "yt-dlp.exe")
    assert command.prefix_args == ()


def make_window(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    app.processEvents()
    return app, window


def test_main_window_has_four_keyboard_accessible_workspaces(tmp_path, monkeypatch):
    _app, window = make_window(tmp_path, monkeypatch)
    assert window.navigation.count() == 4
    assert window.pages.count() == 4
    assert window.url_edit.accessibleName() == "Video or playlist link"
    assert window.queue_tree.accessibleName() == "Download queue"
    assert window.history_tree.accessibleName() == "Successful download history"
    window.deleteLater()


def test_conditional_download_controls_follow_user_choices(tmp_path, monkeypatch):
    app, window = make_window(tmp_path, monkeypatch)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("audio"))
    window.cookie_source.setCurrentText("Cookie file")
    window.subtitle_combo.setCurrentText("Embed")
    app.processEvents()
    assert window.quality_combo.isHidden()
    assert not window.audio_combo.isHidden()
    assert window.playlist_group.isHidden()
    assert window.cookie_file.isEnabled()
    assert window.subtitle_languages.isEnabled()
    window.url_edit.setText("https://example.com/playlist")
    window.analysis_url = window.url_edit.text()
    window._analysis_complete({"_type": "playlist", "title": "Mix", "entries": [{"id": "one"}]})
    assert not window.playlist_group.isHidden()
    window.playlist_combo.setCurrentText("Playlist range")
    assert not window.playlist_start.isHidden()
    window.url_edit.setText("https://example.com/video")
    assert window.playlist_group.isHidden()
    window.deleteLater()


def test_command_preview_uses_argument_separator_and_settings_exclude_secrets(tmp_path, monkeypatch):
    app, window = make_window(tmp_path, monkeypatch)
    window.url_edit.setText("https://example.com/watch?v=abc")
    window.cookie_source.setCurrentText("Browser")
    window.browser_combo.setCurrentText("firefox")
    window.proxy_edit.setText("http://name:secret@proxy.example")
    window.expert_args.setText('--sleep-requests "1"')
    app.processEvents()
    preview = window.command_preview.toPlainText()
    assert "--sleep-requests" in preview
    assert " -- https://example.com/watch?v=abc" in preview

    window._save_settings()
    settings = json.loads(window.store.settings_path.read_text(encoding="utf-8"))
    assert "cookie_source" not in settings
    assert "expert_args" not in settings
    assert "proxy" not in settings
    window.deleteLater()


def test_analysis_needs_only_a_link_and_resets_playlist(tmp_path, monkeypatch):
    _app, window = make_window(tmp_path, monkeypatch)
    window.settings_output.clear()
    window.output_edit.clear()
    window.url_edit.setText("https://example.com/playlist")
    captured = []
    monkeypatch.setattr(window.analysis_runner, "start_analysis", captured.append)
    window._analyze()
    assert captured and captured[0][-1] == "https://example.com/playlist"
    window._analysis_complete({"_type": "playlist", "title": "Mix", "entries": [{"id": "one"}]})
    assert not window.playlist_group.isHidden()
    window.url_edit.setText("https://example.com/video")
    assert window.playlist_group.isHidden()
    assert not window.pages.widget(0).findChildren(QScrollArea)
    window.deleteLater()


def test_destination_confirmation_and_cancel(tmp_path, monkeypatch):
    _app, window = make_window(tmp_path, monkeypatch)
    window.url_edit.setText("https://example.com/video")
    original = window.output_edit.text()
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window._queue_from_form(False)
    assert not window.queue.jobs
    assert window.output_edit.text() == original

    def accept(dialog):
        dialog.findChild(QLineEdit).setText(str(tmp_path))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", accept)
    window._queue_from_form(False)
    assert len(window.queue.jobs) == 1
    assert window.queue.jobs[0].spec.output_dir == str(tmp_path)
    window.deleteLater()


def test_history_keeps_safe_link_and_prompts_for_sensitive_link(tmp_path, monkeypatch):
    _app, window = make_window(tmp_path, monkeypatch)
    window.open_folder_done.setChecked(False)
    normal = DownloadSpec("https://example.com/watch?v=abc", str(tmp_path), title="Normal")
    sensitive = DownloadSpec("https://example.com/video?access_token=secret", str(tmp_path), title="Private")
    window._job_completed(QueueJob("normal", normal))
    window._job_completed(QueueJob("private", sensitive))
    saved = window.store.history_path.read_text(encoding="utf-8")
    assert "secret" not in saved
    assert window.history[0]["url"] == ""
    calls = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("https://example.com/video", True))
    monkeypatch.setattr(window.queue, "add", lambda spec, start_now: calls.append(spec))
    window.history_tree.setCurrentItem(window.history_tree.topLevelItem(0))
    window._retry_history()
    assert calls[0].url == "https://example.com/video"
    window.history_tree.setCurrentItem(window.history_tree.topLevelItem(1))
    window._retry_history()
    assert calls[1].url == normal.url
    window.deleteLater()


def test_compact_download_has_visible_actions_and_accessible_controls(tmp_path, monkeypatch):
    app, window = make_window(tmp_path, monkeypatch)
    window.resize(683, 384)
    window.show()
    app.processEvents()
    assert window.compact_nav.isVisible()
    assert not window.sidebar.isVisible()
    assert not window.pages.widget(0).findChildren(QScrollArea)
    for widget in (window.url_edit, window.mode_combo, window.options_button, window.download_button, window.add_queue_button):
        assert widget.isVisible()
        assert widget.mapTo(window, widget.rect().bottomRight()).y() < window.height()
    for widget in (window.mode_combo, window.quality_combo, window.container_combo, window.audio_combo, window.playlist_combo):
        assert widget.accessibleName()
    window.url_edit.setFocus()
    window.focusNextChild()
    app.processEvents()
    assert app.focusWidget() is window.analyze_button
    window.url_edit.setText("https://example.com/playlist")
    window.analysis_url = window.url_edit.text()
    window._analysis_complete({"_type": "playlist", "title": "Test playlist", "entries": [{"id": "1"}]})
    window.playlist_combo.setCurrentText("Playlist range")
    app.processEvents()
    assert window.preview_title.height() >= 20
    assert window.playlist_combo.height() >= 36
    assert window.playlist_start.isVisible()
    assert window.download_button.mapTo(window, window.download_button.rect().bottomRight()).y() < window.height()
    assert isinstance(window.pages.widget(3), QScrollArea)
    assert window.options_dialog.findChildren(QScrollArea)
    window.close()


def test_analysis_timeout_leaves_default_download_path(tmp_path, monkeypatch):
    _app, window = make_window(tmp_path, monkeypatch)
    window.url_edit.setText("https://example.com/video")
    window.analysis_url = window.url_edit.text()
    canceled = []
    monkeypatch.setattr(window, "_cancel_analysis", lambda: canceled.append(True))
    window._analysis_seconds = 44
    window._analysis_tick()
    assert canceled
    assert "defaults" in window.download_button.text()
    assert "45 seconds" in window.analysis_error.text()
    window.deleteLater()


def test_close_confirmation_pauses_queue_before_stopping(tmp_path, monkeypatch):
    _app, window = make_window(tmp_path, monkeypatch)
    monkeypatch.setattr(QueueController, "active", property(lambda self: True))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.queue.paused = False
    window.close()
    assert window.queue.paused
    assert window._closing_after_stop
    window.close()

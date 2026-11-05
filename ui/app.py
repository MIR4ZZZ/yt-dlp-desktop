from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, APP_VERSION
from .core import DownloadSpec, QueueJob, build_analysis_args, build_download_args, history_safe_url, validate_url
from .process import ProcessRunner, QueueController
from .storage import JsonStore
from .styles import HIGH_CONTRAST_STYLESHEET, STYLESHEET


@dataclass(frozen=True)
class EngineCommand:
    program: str
    prefix_args: tuple[str, ...] = ()


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def install_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else source_root()


def resolve_engine() -> EngineCommand:
    root = install_root()
    for candidate in (root / "engine" / "yt-dlp.exe", root / "yt-dlp.exe"):
        if candidate.exists():
            return EngineCommand(str(candidate))
    if getattr(sys, "frozen", False):
        return EngineCommand(str(root / "engine" / "yt-dlp.exe"))
    return EngineCommand(sys.executable, ("-m", "yt_dlp"))


def resolve_ffmpeg_dir() -> str | None:
    bundled = install_root() / "tools"
    if (bundled / "ffmpeg.exe").exists() and (bundled / "ffprobe.exe").exists():
        return str(bundled)
    executable = shutil.which("ffmpeg")
    return str(Path(executable).resolve().parent) if executable else None


def resolve_icon() -> Path | None:
    candidates = [
        install_root() / "assets" / "logo.ico",
        source_root() / "devscripts" / "logo.ico",
    ]
    return next((path for path in candidates if path.exists()), None)


def ffmpeg_version(ffmpeg_dir: str | None) -> str:
    if not ffmpeg_dir:
        return "Not found"
    executable = Path(ffmpeg_dir) / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    try:
        result = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return (result.stdout.splitlines()[0] if result.stdout else "Available").replace("ffmpeg version ", "")
    except (OSError, subprocess.SubprocessError):
        return "Unavailable"


def engine_version(engine: EngineCommand) -> str:
    try:
        result = subprocess.run(
            [engine.program, *engine.prefix_args, "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else "Unavailable"
    except (OSError, subprocess.SubprocessError):
        return "Unavailable"


def duration_text(seconds) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def system_high_contrast() -> bool:
    if os.environ.get("YT_DLP_UI_FORCE_HIGH_CONTRAST") == "1":
        return True
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class HighContrast(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("lpszDefaultScheme", wintypes.LPWSTR)]

    state = HighContrast()
    state.cbSize = ctypes.sizeof(state)
    return bool(ctypes.windll.user32.SystemParametersInfoW(0x42, state.cbSize, ctypes.byref(state), 0) and state.dwFlags & 1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = JsonStore()
        self.settings = self.store.load_settings()
        self.history = self.store.load_history()
        self.engine = resolve_engine()
        self.engine_version_text = engine_version(self.engine)
        self.ffmpeg_dir = resolve_ffmpeg_dir()
        self.analysis_runner = ProcessRunner(self.engine.program, list(self.engine.prefix_args), self)
        self.download_runner = ProcessRunner(self.engine.program, list(self.engine.prefix_args), self)
        self.queue = QueueController(self.download_runner, self.ffmpeg_dir, self)
        self.network = QNetworkAccessManager(self)
        self.analyzed_data: dict | None = None
        self._closing_after_stop = False
        self._compact = False
        self._analysis_seconds = 0
        self.analysis_timer = QTimer(self)
        self.analysis_timer.setInterval(1000)
        self.analysis_timer.timeout.connect(self._analysis_tick)

        self.setObjectName("root")
        self.setWindowTitle(APP_NAME)
        self.resize(1220, 800)
        self.setMinimumSize(640, 360)
        icon = resolve_icon()
        if icon:
            self.setWindowIcon(QIcon(str(icon)))

        self._build_ui()
        self._apply_compact_layout()
        self._connect_signals()
        self._apply_settings()
        self._refresh_history()
        self._refresh_command_preview()

        if not self.ffmpeg_dir:
            self.statusBar().showMessage("FFmpeg was not found. Analysis works, but media conversion may fail.")
        else:
            self.statusBar().showMessage("Ready")

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.compact_nav = QFrame()
        self.compact_nav.setObjectName("compactNav")
        compact_layout = QHBoxLayout(self.compact_nav)
        compact_layout.setContentsMargins(8, 4, 8, 4)
        compact_layout.setSpacing(4)
        compact_layout.addWidget(QLabel("yt-dlp"))
        self.compact_buttons = []
        for index, title in enumerate(("Download", "Queue", "History", "Settings")):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setAccessibleName(f"Go to {title}")
            button.clicked.connect(lambda _checked=False, row=index: self.navigation.setCurrentRow(row))
            compact_layout.addWidget(button)
            self.compact_buttons.append(button)
        self.compact_nav.hide()
        root_layout.addWidget(self.compact_nav)
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(190)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(18, 24, 18, 18)
        brand = QLabel("yt-dlp")
        brand.setObjectName("brand")
        subtitle = QLabel("Desktop")
        subtitle.setObjectName("muted")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(26)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.addItems(["Download", "Queue", "History", "Settings"])
        self.navigation.setAccessibleName("Main navigation")
        sidebar_layout.addWidget(self.navigation, 1)
        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("muted")
        sidebar_layout.addWidget(version)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_download_page())
        self.pages.addWidget(self._build_queue_page())
        self.pages.addWidget(self._build_history_page())
        self.pages.addWidget(self._build_settings_page())

        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(
            lambda row: [button.setChecked(index == row) for index, button in enumerate(self.compact_buttons)]
        )
        self.compact_buttons[0].setChecked(True)

        focus_link = QAction(self)
        focus_link.setShortcut("Ctrl+L")
        focus_link.triggered.connect(self._focus_link)
        self.addAction(focus_link)
        analyze_action = QAction(self)
        analyze_action.setShortcut("Ctrl+Return")
        analyze_action.triggered.connect(self._analyze)
        self.addAction(analyze_action)

    def _page_header(self, title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        summary = QLabel(description)
        summary.setObjectName("muted")
        summary.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(summary)
        if title == "Download":
            self.download_summary = summary
        return page, layout

    def _build_download_page(self) -> QWidget:
        page, outer = self._page_header("Download", "Paste a link and choose what to save.")
        self.download_layout = outer
        outer.setSpacing(10)

        outer.addWidget(self._label("Video or playlist link"))
        link_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setAccessibleName("Video or playlist link")
        self.analyze_button = QPushButton("Analyze")
        self.cancel_analysis_button = QPushButton("Cancel")
        self.cancel_analysis_button.setAccessibleName("Cancel link analysis")
        self.cancel_analysis_button.hide()
        link_row.addWidget(self.url_edit, 1)
        link_row.addWidget(self.analyze_button)
        link_row.addWidget(self.cancel_analysis_button)
        outer.addLayout(link_row)
        self.link_error = QLabel("")
        self.link_error.setObjectName("error")
        self.link_error.setVisible(False)
        outer.addWidget(self.link_error)

        preview = QFrame()
        self.preview_frame = preview
        preview.setObjectName("preview")
        preview_layout = QHBoxLayout(preview)
        self.preview_layout = preview_layout
        preview_layout.setContentsMargins(14, 12, 14, 12)
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(112, 63)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setVisible(False)
        meta = QVBoxLayout()
        self.preview_title = QLabel("Ready when you are")
        self.preview_title.setObjectName("previewTitle")
        self.preview_title.setWordWrap(True)
        self.preview_meta = QLabel("Analyze a link to see its title and details.")
        self.preview_meta.setObjectName("muted")
        self.preview_meta.setWordWrap(True)
        self.analysis_error = QLabel("")
        self.analysis_error.setObjectName("error")
        self.analysis_error.setWordWrap(True)
        meta.addWidget(self.preview_title)
        meta.addWidget(self.preview_meta)
        meta.addWidget(self.analysis_error)
        preview_layout.addWidget(self.thumbnail)
        preview_layout.addLayout(meta, 1)
        outer.addWidget(preview)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Video", "video")
        self.mode_combo.addItem("Audio", "audio")
        self.mode_combo.setAccessibleName("Save as video or audio")
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Best", "2160p", "1440p", "1080p", "720p", "480p"])
        self.quality_combo.setAccessibleName("Video quality")
        self.container_combo = QComboBox()
        self.container_combo.addItems(["Auto", "MP4", "MKV"])
        self.container_combo.setAccessibleName("Video container")
        self.audio_combo = QComboBox()
        self.audio_combo.addItems(["mp3", "m4a", "opus", "flac", "wav"])
        self.audio_combo.setAccessibleName("Audio format")
        format_grid = QGridLayout()
        self._grid_field(format_grid, 0, "Save as", self.mode_combo, 0)
        self.quality_label = self._label("Quality")
        self.container_label = self._label("Container")
        self.audio_label = self._label("Audio format")
        format_grid.addWidget(self.quality_label, 0, 1)
        format_grid.addWidget(self.quality_combo, 1, 1)
        format_grid.addWidget(self.container_label, 0, 2)
        format_grid.addWidget(self.container_combo, 1, 2)
        format_grid.addWidget(self.audio_label, 0, 1)
        format_grid.addWidget(self.audio_combo, 1, 1)
        format_grid.setColumnStretch(0, 2)
        format_grid.setColumnStretch(1, 1)
        format_grid.setColumnStretch(2, 1)
        outer.addLayout(format_grid)

        self.playlist_group = QWidget()
        playlist_layout = QGridLayout(self.playlist_group)
        playlist_layout.setContentsMargins(0, 0, 0, 0)
        playlist_layout.setHorizontalSpacing(8)
        self.playlist_combo = QComboBox()
        self.playlist_combo.addItems(["Full playlist", "Single video", "Playlist range"])
        self.playlist_combo.setAccessibleName("Playlist selection")
        self.playlist_start = QSpinBox()
        self.playlist_start.setRange(1, 999999)
        self.playlist_start.setValue(1)
        self.playlist_start.setAccessibleName("Playlist range start")
        self.playlist_end = QSpinBox()
        self.playlist_end.setRange(1, 999999)
        self.playlist_end.setValue(10)
        self.playlist_end.setAccessibleName("Playlist range end")
        playlist_layout.addWidget(self._label("Playlist"), 0, 0)
        playlist_layout.addWidget(self.playlist_combo, 0, 1)
        self.playlist_start_label = self._label("From")
        self.playlist_end_label = self._label("To")
        playlist_layout.addWidget(self.playlist_start_label, 0, 2)
        playlist_layout.addWidget(self.playlist_start, 0, 3)
        playlist_layout.addWidget(self.playlist_end_label, 0, 4)
        playlist_layout.addWidget(self.playlist_end, 0, 5)
        self.playlist_error = QLabel("")
        self.playlist_error.setObjectName("error")
        playlist_layout.addWidget(self.playlist_error, 1, 0, 1, 6)
        self.playlist_group.hide()
        outer.addWidget(self.playlist_group)

        self.output_edit = QLineEdit()
        self.output_edit.setAccessibleName("Download folder")
        self.options_dialog = QDialog(self)
        self.options_dialog.setWindowTitle("Download options")
        self.options_dialog.setMinimumWidth(530)
        dialog_layout = QVBoxLayout(self.options_dialog)
        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setFrameShape(QFrame.Shape.NoFrame)
        options_body = QWidget()
        options_layout = QVBoxLayout(options_body)
        options_scroll.setWidget(options_body)
        dialog_layout.addWidget(options_scroll, 1)
        extras = QFormLayout()
        self.subtitle_combo = QComboBox()
        self.subtitle_combo.addItems(["None", "Embed", "Separate file"])
        self.subtitle_combo.setAccessibleName("Subtitles")
        self.subtitle_languages = QLineEdit("en")
        self.subtitle_languages.setAccessibleName("Subtitle languages")
        self.auto_subtitles = QCheckBox("Include automatic subtitles")
        self.embed_metadata = QCheckBox("Embed metadata")
        self.embed_thumbnail = QCheckBox("Embed thumbnail")
        self.overwrite_combo = QComboBox()
        self.overwrite_combo.addItems(["Skip existing", "Overwrite"])
        self.overwrite_combo.setAccessibleName("If file exists")
        extras.addRow("Subtitles", self.subtitle_combo)
        extras.addRow("Languages", self.subtitle_languages)
        extras.addRow("", self.auto_subtitles)
        extras.addRow("", self.embed_metadata)
        extras.addRow("", self.embed_thumbnail)
        extras.addRow("If file exists", self.overwrite_combo)
        options_layout.addLayout(extras)
        self.expert_args = QLineEdit()
        self.expert_args.setAccessibleName("Additional yt-dlp arguments")
        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumHeight(75)
        self.command_preview.setAccessibleName("Command preview")
        self.advanced_toggle = QPushButton("Show expert arguments")
        self.advanced_toggle.setCheckable(True)
        self.advanced_frame = QFrame()
        advanced = QFormLayout(self.advanced_frame)
        advanced.addRow("Additional arguments", self.expert_args)
        advanced.addRow("Command preview", self.command_preview)
        advanced.addRow(QLabel("Expert arguments can override your choices and are not saved."))
        self.advanced_frame.hide()
        options_layout.addWidget(self.advanced_toggle)
        options_layout.addWidget(self.advanced_frame)
        done = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        done.rejected.connect(self.options_dialog.close)
        dialog_layout.addWidget(done)

        outer.addStretch(1)
        actions = QHBoxLayout()
        self.options_button = QPushButton("Options")
        self.add_queue_button = QPushButton("Add to queue")
        self.download_button = QPushButton("Download")
        self.download_button.setObjectName("primary")
        actions.addWidget(self.options_button)
        actions.addStretch()
        actions.addWidget(self.add_queue_button)
        actions.addWidget(self.download_button)
        outer.addLayout(actions)
        return page

    def _build_queue_page(self) -> QWidget:
        page, layout = self._page_header("Queue", "Downloads run one at a time so bandwidth, CPU and disk remain predictable.")
        controls = QHBoxLayout()
        self.start_queue_button = QPushButton("Start queue")
        self.start_queue_button.setObjectName("primary")
        self.pause_queue_button = QPushButton("Pause before next")
        self.stop_button = QPushButton("Stop current")
        self.stop_button.setObjectName("danger")
        self.retry_button = QPushButton("Retry")
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        self.remove_button = QPushButton("Remove")
        for button in (
            self.start_queue_button,
            self.pause_queue_button,
            self.stop_button,
            self.retry_button,
            self.up_button,
            self.down_button,
            self.remove_button,
        ):
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        self.queue_tree = QTreeWidget()
        self.queue_tree.setHeaderLabels(["Title", "Format", "Status", "Progress", "Speed", "ETA"])
        self.queue_tree.setAlternatingRowColors(True)
        self.queue_tree.setRootIsDecorated(False)
        self.queue_tree.setAccessibleName("Download queue")
        self.queue_tree.header().setStretchLastSection(False)
        self.queue_tree.header().resizeSection(0, 330)
        layout.addWidget(self.queue_tree, 2)
        log_label = QLabel("Selected job log")
        log_label.setObjectName("muted")
        layout.addWidget(log_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        self.log_view.setAccessibleName("Selected download log")
        layout.addWidget(self.log_view, 1)
        return page

    def _build_history_page(self) -> QWidget:
        page, layout = self._page_header("History", "Only completed downloads are remembered on this computer.")
        controls = QHBoxLayout()
        self.history_open_button = QPushButton("Open folder")
        self.history_retry_button = QPushButton("Download again")
        self.history_clear_button = QPushButton("Clear history")
        self.history_clear_button.setObjectName("danger")
        controls.addWidget(self.history_open_button)
        controls.addWidget(self.history_retry_button)
        controls.addStretch()
        controls.addWidget(self.history_clear_button)
        layout.addLayout(controls)
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderLabels(["Completed", "Title", "Format", "Folder"])
        self.history_tree.setRootIsDecorated(False)
        self.history_tree.setAlternatingRowColors(True)
        self.history_tree.setAccessibleName("Successful download history")
        self.history_tree.header().resizeSection(0, 165)
        self.history_tree.header().resizeSection(1, 360)
        self.history_tree.header().resizeSection(2, 110)
        layout.addWidget(self.history_tree, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page, layout = self._page_header("Settings", "Download defaults and optional access.")
        defaults = QGroupBox("Defaults")
        form = QFormLayout(defaults)
        self.settings_output = QLineEdit()
        self.settings_output.setAccessibleName("Default download folder")
        self.settings_output_button = QPushButton("Browse")
        row = QHBoxLayout()
        row.addWidget(self.settings_output, 1)
        row.addWidget(self.settings_output_button)
        self.open_folder_done = QCheckBox("Open the folder after a successful download")
        form.addRow("Default folder", row)
        form.addRow("", self.open_folder_done)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setAccessibleName("Proxy for this session")
        self.rate_limit = QSpinBox()
        self.rate_limit.setRange(0, 100000000)
        self.rate_limit.setSpecialValueText("Unlimited")
        self.rate_limit.setAccessibleName("Rate limit")
        self.rate_limit.setSuffix(" KB/s")
        self.retries = QSpinBox()
        self.retries.setRange(0, 1000)
        self.retries.setAccessibleName("Download retries")
        form.addRow("Proxy for this session", self.proxy_edit)
        form.addRow("Rate limit", self.rate_limit)
        form.addRow("Retries", self.retries)
        layout.addWidget(defaults)

        access = QGroupBox("Access for this session")
        access_form = QFormLayout(access)
        self.cookie_source = QComboBox()
        self.cookie_source.addItems(["None", "Browser", "Cookie file"])
        self.cookie_source.setAccessibleName("Cookie access for this session")
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["chrome", "edge", "firefox", "brave", "opera", "vivaldi"])
        self.browser_combo.setAccessibleName("Browser for cookies")
        self.cookie_file = QLineEdit()
        self.cookie_file.setAccessibleName("Cookie file for this session")
        self.cookie_file_button = QPushButton("Choose file")
        cookie_row = QHBoxLayout()
        cookie_row.addWidget(self.cookie_file, 1)
        cookie_row.addWidget(self.cookie_file_button)
        access_form.addRow("Cookies", self.cookie_source)
        access_form.addRow("Browser", self.browser_combo)
        access_form.addRow("Cookie file", cookie_row)
        note = QLabel("Access is explicit. Cookie contents are never saved by this app.")
        note.setObjectName("muted")
        access_form.addRow("", note)
        layout.addWidget(access)

        about = QGroupBox("About")
        about_layout = QFormLayout(about)
        about_layout.addRow("App", QLabel(f"{APP_NAME} {APP_VERSION}"))
        about_layout.addRow("yt-dlp", QLabel(self.engine_version_text))
        about_layout.addRow("FFmpeg", QLabel(ffmpeg_version(self.ffmpeg_dir)))
        about_layout.addRow("Engine", QLabel(self.engine.program))
        about_layout.addRow("Project", QLabel("Unofficial community app; not published by yt-dlp"))
        layout.addWidget(about)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    def _grid_field(self, grid: QGridLayout, row: int, label: str, widget: QWidget, column: int) -> None:
        grid.addWidget(self._label(label), row, column)
        grid.addWidget(widget, row + 1, column)
        grid.setColumnStretch(column, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "sidebar"):
            self._apply_compact_layout()

    def _apply_compact_layout(self) -> None:
        compact = self.width() < 900 or self.height() < 600
        if compact == self._compact:
            return
        self._compact = compact
        self.sidebar.setVisible(not compact)
        self.compact_nav.setVisible(compact)
        self.download_summary.setVisible(not compact)
        self.preview_meta.setVisible(not compact)
        self.preview_layout.setContentsMargins(*(8, 4, 8, 4) if compact else (14, 12, 14, 12))
        self.preview_title.setMinimumHeight(20 if compact else 0)
        for combo in (self.mode_combo, self.quality_combo, self.container_combo, self.audio_combo, self.playlist_combo):
            combo.setMinimumHeight(36 if compact else 0)
        pixmap = self.thumbnail.pixmap()
        self.thumbnail.setVisible(not compact and pixmap is not None and not pixmap.isNull())
        self.download_layout.setContentsMargins(*(12, 6, 12, 6) if compact else (32, 26, 32, 24))
        self.download_layout.setSpacing(2 if compact else 10)

    def _connect_signals(self) -> None:
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.analyze_button.clicked.connect(self._analyze)
        self.cancel_analysis_button.clicked.connect(self._cancel_analysis)
        self.url_edit.returnPressed.connect(self._analyze)
        self.options_button.clicked.connect(self._open_options)
        self.url_edit.textChanged.connect(self._link_changed)
        self.settings_output_button.clicked.connect(lambda: self._choose_folder(self.settings_output))
        self.cookie_file_button.clicked.connect(self._choose_cookie_file)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.mode_combo.currentIndexChanged.connect(self._update_mode_fields)
        self.playlist_combo.currentIndexChanged.connect(self._update_playlist_fields)
        self.cookie_source.currentIndexChanged.connect(self._update_cookie_fields)
        self.subtitle_combo.currentIndexChanged.connect(self._update_subtitle_fields)
        self.add_queue_button.clicked.connect(lambda: self._queue_from_form(False))
        self.download_button.clicked.connect(lambda: self._queue_from_form(True))

        for widget in (
            self.url_edit,
            self.subtitle_languages,
            self.proxy_edit,
            self.expert_args,
        ):
            widget.textChanged.connect(self._refresh_command_preview)
        for widget in (
            self.mode_combo,
            self.quality_combo,
            self.container_combo,
            self.audio_combo,
            self.subtitle_combo,
            self.playlist_combo,
            self.overwrite_combo,
            self.cookie_source,
            self.browser_combo,
        ):
            widget.currentIndexChanged.connect(self._refresh_command_preview)
        for widget in (
            self.auto_subtitles,
            self.embed_metadata,
            self.embed_thumbnail,
        ):
            widget.toggled.connect(self._refresh_command_preview)
        for widget in (self.playlist_start, self.playlist_end, self.rate_limit, self.retries):
            widget.valueChanged.connect(self._refresh_command_preview)

        self.analysis_runner.analyzed.connect(self._analysis_complete)
        self.analysis_runner.analysis_failed.connect(self._analysis_failed)
        self.analysis_runner.state_changed.connect(self._analysis_state_changed)
        self.queue.jobs_changed.connect(self._refresh_queue)
        self.queue.current_changed.connect(self._current_job_changed)
        self.queue.job_completed.connect(self._job_completed)

        self.start_queue_button.clicked.connect(self.queue.start)
        self.pause_queue_button.clicked.connect(self.queue.pause)
        self.stop_button.clicked.connect(self.queue.stop_current)
        self.retry_button.clicked.connect(lambda: self._with_selected_job(self.queue.retry))
        self.remove_button.clicked.connect(lambda: self._with_selected_job(self.queue.remove))
        self.up_button.clicked.connect(lambda: self._with_selected_job(lambda job: self.queue.move(job, -1)))
        self.down_button.clicked.connect(lambda: self._with_selected_job(lambda job: self.queue.move(job, 1)))
        self.queue_tree.itemSelectionChanged.connect(self._show_selected_log)

        self.history_open_button.clicked.connect(self._open_history_folder)
        self.history_retry_button.clicked.connect(self._retry_history)
        self.history_clear_button.clicked.connect(self._clear_history)
        self.history_tree.itemDoubleClicked.connect(lambda *_: self._open_history_folder())
        self.settings_output.textChanged.connect(self._settings_folder_changed)

    def _apply_settings(self) -> None:
        settings = self.settings
        self.output_edit.setText(str(settings["download_dir"]))
        self.settings_output.setText(str(settings["download_dir"]))
        self.open_folder_done.setChecked(bool(settings["open_folder_on_done"]))
        self._set_combo_data(self.mode_combo, settings["mode"])
        self._set_combo_text(self.quality_combo, settings["video_quality"])
        self._set_combo_text(self.container_combo, settings["video_container"])
        self._set_combo_text(self.audio_combo, settings["audio_format"])
        self._set_combo_text(self.subtitle_combo, settings["subtitle_mode"])
        self.subtitle_languages.setText(str(settings["subtitle_languages"]))
        self.auto_subtitles.setChecked(bool(settings["automatic_subtitles"]))
        self.embed_metadata.setChecked(bool(settings["embed_metadata"]))
        self.embed_thumbnail.setChecked(bool(settings["embed_thumbnail"]))
        self._set_combo_text(self.overwrite_combo, settings["overwrite"])
        self.retries.setValue(settings["retries"])
        self.rate_limit.setValue(int(settings["rate_limit_kbps"] or 0))
        self._update_mode_fields()
        self._update_playlist_fields()
        self._update_cookie_fields()
        self._update_subtitle_fields()

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _settings_folder_changed(self, value: str) -> None:
        pass

    def _toggle_advanced(self, visible: bool) -> None:
        self.advanced_frame.setVisible(visible)
        self.advanced_toggle.setText("Hide advanced options" if visible else "Show advanced options")

    def _update_mode_fields(self) -> None:
        video = self.mode_combo.currentData() == "video"
        for widget in (self.quality_label, self.quality_combo, self.container_label, self.container_combo):
            widget.setVisible(video)
        for widget in (self.audio_label, self.audio_combo):
            widget.setVisible(not video)
        self._refresh_command_preview()

    def _update_playlist_fields(self) -> None:
        enabled = not self.playlist_group.isHidden() and self.playlist_combo.currentText() == "Playlist range"
        for widget in (self.playlist_start_label, self.playlist_start, self.playlist_end_label, self.playlist_end):
            widget.setVisible(enabled)
        self.playlist_error.clear()
        self._refresh_command_preview()

    def _update_cookie_fields(self) -> None:
        source = self.cookie_source.currentText()
        self.browser_combo.setEnabled(source == "Browser")
        self.cookie_file.setEnabled(source == "Cookie file")
        self.cookie_file_button.setEnabled(source == "Cookie file")
        self._refresh_command_preview()

    def _update_subtitle_fields(self) -> None:
        enabled = self.subtitle_combo.currentText() != "None"
        self.subtitle_languages.setEnabled(enabled)
        self.auto_subtitles.setEnabled(enabled)
        self._refresh_command_preview()

    def _choose_folder(self, target: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", target.text() or str(Path.home()))
        if folder:
            target.setText(folder)

    def _open_options(self) -> None:
        available = self.screen().availableGeometry()
        self.options_dialog.resize(min(560, available.width() - 20), min(480, available.height() - 20))
        self.options_dialog.open()


    def _choose_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose cookies.txt", str(Path.home()), "Cookie files (*.txt);;All files (*)")
        if path:
            self.cookie_file.setText(path)

    def _focus_link(self) -> None:
        self.navigation.setCurrentRow(0)
        self.url_edit.setFocus()
        self.url_edit.selectAll()

    def _collect_spec(self) -> DownloadSpec:
        url = validate_url(self.url_edit.text())
        output = self.output_edit.text().strip()
        if not output:
            raise ValueError("Choose a download folder.")
        playlist_mode = self.playlist_combo.currentText() if not self.playlist_group.isHidden() else "Single video"
        start = self.playlist_start.value() if playlist_mode == "Playlist range" else None
        end = self.playlist_end.value() if playlist_mode == "Playlist range" else None
        if start and end and end < start:
            raise ValueError("Playlist end must be equal to or greater than playlist start.")
        if self.cookie_source.currentText() == "Cookie file":
            cookie_path = Path(self.cookie_file.text().strip())
            if not cookie_path.is_file():
                raise ValueError("Choose an existing cookies.txt file.")
        try:
            extra = tuple(self.download_runner.process.splitCommand(self.expert_args.text())) if self.expert_args.text().strip() else ()
        except Exception as error:
            raise ValueError(f"Additional arguments could not be read: {error}") from error
        return DownloadSpec(
            url=url,
            output_dir=output,
            title=self.preview_title.text() if self.analyzed_data else "",
            mode=str(self.mode_combo.currentData()),
            video_quality=self.quality_combo.currentText(),
            video_container=self.container_combo.currentText(),
            audio_format=self.audio_combo.currentText(),
            subtitle_mode=self.subtitle_combo.currentText(),
            subtitle_languages=self.subtitle_languages.text().strip(),
            automatic_subtitles=self.auto_subtitles.isChecked(),
            embed_metadata=self.embed_metadata.isChecked(),
            embed_thumbnail=self.embed_thumbnail.isChecked(),
            playlist_mode=playlist_mode,
            playlist_start=start,
            playlist_end=end,
            overwrite=self.overwrite_combo.currentText(),
            cookie_source=self.cookie_source.currentText(),
            browser=self.browser_combo.currentText(),
            cookie_file=self.cookie_file.text().strip(),
            proxy=self.proxy_edit.text().strip(),
            rate_limit_kbps=self.rate_limit.value() or None,
            retries=self.retries.value(),
            extra_args=extra,
        )

    def _refresh_command_preview(self, *_args) -> None:
        if not hasattr(self, "command_preview"):
            return
        try:
            spec = self._collect_spec()
            command = subprocess.list2cmdline(["yt-dlp", *build_download_args(spec, self.ffmpeg_dir)])
        except ValueError as error:
            command = str(error)
        self.command_preview.setPlainText(command)

    def _link_changed(self) -> None:
        self.analyzed_data = None
        self.playlist_group.hide()
        self.playlist_combo.setCurrentText("Full playlist")
        self.playlist_error.clear()
        self.analysis_error.clear()
        self.link_error.hide()
        self.download_button.setText("Download")
        self.preview_title.setText("Ready when you are")
        self.preview_meta.setText("Analyze a link to see its title and details.")
        self.thumbnail.clear()
        self.thumbnail.hide()
        if self.analysis_runner.running:
            self.analysis_runner.stop()

    def _analyze(self) -> None:
        if self.analysis_runner.running:
            return
        try:
            url = validate_url(self.url_edit.text())
        except ValueError as error:
            self.link_error.setText(str(error))
            self.link_error.show()
            self.url_edit.setFocus()
            return
        self.link_error.hide()
        self.analysis_url = url
        self.analyzed_data = None
        self.playlist_group.hide()
        self.analysis_error.clear()
        self.preview_title.setText("Analyzing link…")
        self.preview_meta.setText("Reading title and available media.")
        self.thumbnail.clear()
        self.thumbnail.hide()
        spec = DownloadSpec(
            url=url, output_dir="", cookie_source=self.cookie_source.currentText(),
            browser=self.browser_combo.currentText(), cookie_file=self.cookie_file.text().strip(),
            proxy=self.proxy_edit.text().strip(), retries=self.retries.value(),
        )
        try:
            self.analysis_runner.start_analysis(build_analysis_args(spec))
        except RuntimeError as error:
            self._analysis_failed(str(error))

    def _cancel_analysis(self) -> None:
        if self.analysis_runner.running:
            self.analysis_runner.stop()
            self.analysis_timer.stop()
            self._analysis_failed("Analysis canceled. You can still download with defaults.")

    def _analysis_tick(self) -> None:
        self._analysis_seconds += 1
        if self._analysis_seconds >= 45:
            self._cancel_analysis()
            self._analysis_failed("Analysis timed out after 45 seconds. You can still download with defaults.")
        else:
            self.preview_meta.setText(f"Reading title and available media… {self._analysis_seconds}s")

    def _analysis_state_changed(self, running: bool) -> None:
        self.analyze_button.setDisabled(running)
        self.analyze_button.setText("Analyzing…" if running else "Analyze")
        self.cancel_analysis_button.setVisible(running)
        if running:
            self._analysis_seconds = 0
            self.analysis_timer.start()
        else:
            self.analysis_timer.stop()

    def _analysis_complete(self, data: dict) -> None:
        if self.url_edit.text().strip() != getattr(self, "analysis_url", ""):
            return
        self.analyzed_data = data
        title = str(data.get("title") or data.get("id") or "Untitled media")
        entries = data.get("entries") if isinstance(data.get("entries"), list) else []
        duration = duration_text(data.get("duration"))
        source = str(data.get("extractor_key") or data.get("extractor") or urlparse(self.url_edit.text()).netloc)
        details = [source]
        if duration:
            details.append(duration)
        is_playlist = data.get("_type") == "playlist" or bool(entries)
        if is_playlist:
            details.append(f"{len(entries)} playlist items" if entries else "Playlist")
            self.playlist_group.show()
            self.playlist_combo.setCurrentText("Full playlist")
        else:
            self.playlist_group.hide()
        self.preview_title.setText(title)
        self.preview_meta.setText("  •  ".join(details))
        self.analysis_error.clear()
        self.download_button.setText("Download")
        thumbnail = data.get("thumbnail")
        if not thumbnail and entries:
            first = next((entry for entry in entries if isinstance(entry, dict)), {})
            thumbnail = first.get("thumbnail")
        if thumbnail:
            self.thumbnail.setVisible(not self._compact)
            self._load_thumbnail(str(thumbnail))
        self.statusBar().showMessage("Link analyzed.", 4000)

    def _analysis_failed(self, message: str) -> None:
        if self.url_edit.text().strip() != getattr(self, "analysis_url", ""):
            return
        self.analyzed_data = None
        self.preview_title.setText("Analysis unavailable")
        self.preview_meta.setText("You can still download with defaults.")
        self.playlist_group.hide()
        self.download_button.setText("Download with defaults")
        self.analysis_error.setText(message.strip().splitlines()[-1] if message.strip() else "Could not analyze this link.")
        self.thumbnail.hide()

    def _load_thumbnail(self, url: str) -> None:
        reply = self.network.get(QNetworkRequest(QUrl(url)))

        def finished() -> None:
            pixmap = QPixmap()
            if reply.error() == reply.NetworkError.NoError and pixmap.loadFromData(reply.readAll()):
                self.thumbnail.setPixmap(
                    pixmap.scaled(
                        self.thumbnail.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self.thumbnail.setText("Thumbnail unavailable")
            reply.deleteLater()

        reply.finished.connect(finished)

    def _queue_from_form(self, start_now: bool) -> None:
        try:
            validate_url(self.url_edit.text())
        except ValueError as error:
            self.link_error.setText(str(error))
            self.link_error.show()
            self.url_edit.setFocus()
            return
        self.link_error.hide()
        if not self.playlist_group.isHidden() and self.playlist_combo.currentText() == "Playlist range" and self.playlist_end.value() < self.playlist_start.value():
            self.playlist_error.setText("End must be equal to or greater than start.")
            self.playlist_end.setFocus()
            return
        self.playlist_error.clear()
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose destination")
        dialog.setMinimumWidth(470)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Save this download to"))
        folder_row = QHBoxLayout()
        folder = QLineEdit(self.settings_output.text().strip() or str(Path.home() / "Videos"))
        folder.setAccessibleName("Destination folder")
        change = QPushButton("Change…")
        change.clicked.connect(lambda: self._choose_folder(folder))
        folder_row.addWidget(folder, 1)
        folder_row.addWidget(change)
        layout.addLayout(folder_row)
        error_label = QLabel("")
        error_label.setObjectName("error")
        layout.addWidget(error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        confirm = QPushButton("Start download" if start_now else "Add to queue")
        confirm.setObjectName("primary")
        buttons.addButton(confirm, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(dialog.reject)
        def accept_destination() -> None:
            chosen = folder.text().strip()
            if not chosen or not Path(chosen).is_dir():
                error_label.setText("Choose an existing destination folder.")
                folder.setFocus()
                return
            dialog.accept()

        buttons.accepted.connect(accept_destination)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = folder.text().strip()
        self.output_edit.setText(chosen)
        try:
            spec = self._collect_spec()
        except ValueError as error:
            if "cookie" in str(error).lower():
                self.navigation.setCurrentRow(3)
            QMessageBox.warning(self, APP_NAME, str(error))
            return
        job = self.queue.add(spec, start_now=start_now)
        self.navigation.setCurrentRow(1)
        self.statusBar().showMessage(
            f"Started {job.spec.title or job.spec.url}" if start_now else "Added to queue.", 4000
        )

    def _refresh_queue(self, jobs: list[QueueJob]) -> None:
        selected = self._selected_job_id()
        self.queue_tree.clear()
        for job in jobs:
            mode = job.spec.audio_format.upper() if job.spec.mode == "audio" else job.spec.video_quality
            item = QTreeWidgetItem(
                [
                    job.spec.title or job.spec.url,
                    mode,
                    job.status,
                    f"{job.percent:.1f}%" if job.percent else "—",
                    job.speed or "—",
                    job.eta or "—",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, job.job_id)
            self.queue_tree.addTopLevelItem(item)
            if job.job_id == selected:
                item.setSelected(True)
        self.stop_button.setEnabled(self.queue.current is not None)
        self.start_queue_button.setEnabled(any(job.status == "Queued" for job in jobs) and self.queue.paused)

    def _selected_job_id(self) -> str | None:
        selected = self.queue_tree.selectedItems() if hasattr(self, "queue_tree") else []
        return selected[0].data(0, Qt.ItemDataRole.UserRole) if selected else None

    def _selected_job(self) -> QueueJob | None:
        job_id = self._selected_job_id()
        return next((job for job in self.queue.jobs if job.job_id == job_id), None)

    def _with_selected_job(self, callback) -> None:
        job = self._selected_job()
        if job:
            callback(job)

    def _show_selected_log(self) -> None:
        job = self._selected_job()
        self.log_view.setPlainText("\n".join(job.log) if job else "")

    def _current_job_changed(self, job: QueueJob | None) -> None:
        if job:
            self.log_view.setPlainText("\n".join(job.log))
            self.statusBar().showMessage(f"Downloading {job.spec.title or job.spec.url}")
        elif not self.queue.active:
            self.statusBar().showMessage("Queue idle", 4000)
        self._show_selected_log()

    def _job_completed(self, job: QueueJob) -> None:
        safe_url = history_safe_url(job.spec.url)
        item = {
            "url": safe_url,
            "title": job.spec.title or (safe_url or "Completed download"),
            "output_dir": job.spec.output_dir,
            "format": job.spec.audio_format.upper() if job.spec.mode == "audio" else job.spec.video_quality,
            "spec": job.spec.safe_dict(),
        }
        self.history = self.store.add_success(item)
        self._refresh_history()
        if self.open_folder_done.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.spec.output_dir))

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_tree"):
            return
        self.history_tree.clear()
        for index, item in enumerate(self.history):
            completed = str(item.get("completed_at", ""))
            try:
                completed = datetime.fromisoformat(completed.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
            row = QTreeWidgetItem(
                [completed, str(item.get("title", "")), str(item.get("format", "")), str(item.get("output_dir", ""))]
            )
            row.setData(0, Qt.ItemDataRole.UserRole, index)
            self.history_tree.addTopLevelItem(row)

    def _selected_history(self) -> dict | None:
        selected = self.history_tree.selectedItems()
        if not selected:
            return None
        index = selected[0].data(0, Qt.ItemDataRole.UserRole)
        return self.history[index] if isinstance(index, int) and 0 <= index < len(self.history) else None

    def _open_history_folder(self) -> None:
        item = self._selected_history()
        if item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.get("output_dir", ""))))

    def _retry_history(self) -> None:
        item = self._selected_history()
        if not item or not isinstance(item.get("spec"), dict):
            return
        try:
            spec = DownloadSpec.from_dict(item["spec"])
        except (TypeError, ValueError):
            QMessageBox.warning(self, APP_NAME, "This history item cannot be downloaded again.")
            return
        if not spec.url:
            url, accepted = QInputDialog.getText(self, "Download again", "Paste the original link to download again:")
            if not accepted:
                return
            try:
                spec = replace(spec, url=validate_url(url))
            except ValueError as error:
                QMessageBox.warning(self, APP_NAME, str(error))
                return
        if not Path(spec.output_dir).exists():
            spec = replace(spec, output_dir=self.settings_output.text())
        self.queue.add(spec, start_now=True)
        self.navigation.setCurrentRow(1)

    def _clear_history(self) -> None:
        if not self.history:
            return
        answer = QMessageBox.question(self, APP_NAME, "Clear all successful download history from this computer?")
        if answer == QMessageBox.StandardButton.Yes:
            self.store.clear_history()
            self.history = []
            self._refresh_history()

    def _save_settings(self) -> None:
        values = {
            "download_dir": self.settings_output.text().strip() or str(Path.home() / "Videos"),
            "open_folder_on_done": self.open_folder_done.isChecked(),
            "mode": self.mode_combo.currentData(),
            "video_quality": self.quality_combo.currentText(),
            "video_container": self.container_combo.currentText(),
            "audio_format": self.audio_combo.currentText(),
            "subtitle_mode": self.subtitle_combo.currentText(),
            "subtitle_languages": self.subtitle_languages.text().strip(),
            "automatic_subtitles": self.auto_subtitles.isChecked(),
            "embed_metadata": self.embed_metadata.isChecked(),
            "embed_thumbnail": self.embed_thumbnail.isChecked(),
            "overwrite": self.overwrite_combo.currentText(),
            "retries": self.retries.value(),
            "rate_limit_kbps": self.rate_limit.value() or None,
        }
        self.store.save_settings(values)

    def closeEvent(self, event: QCloseEvent) -> None:
        active = self.queue.active or self.analysis_runner.running
        if active and not self._closing_after_stop:
            answer = QMessageBox.question(
                self,
                APP_NAME,
                "A yt-dlp process is still running. Stop it and close the app?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._closing_after_stop = True
            self.queue.pause()
            self.queue.stop_current()
            self.analysis_runner.stop()
            from PySide6.QtCore import QTimer

            QTimer.singleShot(1800, self.close)
            event.ignore()
            return
        if self._closing_after_stop:
            self.download_runner._force_stop_tree()
            self.analysis_runner._force_stop_tree()
        self._save_settings()
        event.accept()


def main() -> None:
    if sys.platform == "win32":
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Unofficial yt-dlp Desktop")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET + (HIGH_CONTRAST_STYLESHEET if system_high_contrast() else ""))
    icon = resolve_icon()
    if icon:
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()

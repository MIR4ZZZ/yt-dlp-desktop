import json
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from ui.core import PROGRESS_PREFIX, DownloadSpec
from ui.process import ProcessRunner, QueueController


def qt_app():
    return QApplication.instance() or QApplication([])


class FakeRunner(QObject):
    progress = Signal(object)
    output = Signal(str)
    finished = Signal(int, bool)

    def __init__(self):
        super().__init__()
        self.running = False
        self.calls = []
        self.stopped = False

    def start_download(self, args):
        self.calls.append(args)
        self.running = True

    def stop(self):
        self.stopped = True

    def complete(self, exit_code=0, canceled=False):
        self.running = False
        self.finished.emit(exit_code, canceled)


def test_queue_runs_sequentially_and_pauses_before_next(tmp_path):
    app = qt_app()
    runner = FakeRunner()
    queue = QueueController(runner, None)
    first = queue.add(DownloadSpec("https://example.com/1", str(tmp_path)))
    second = queue.add(DownloadSpec("https://example.com/2", str(tmp_path)))

    queue.start()
    assert queue.current is first
    assert len(runner.calls) == 1
    runner.progress.emit({"_percent_str": "50%", "_speed_str": "1MiB/s", "_eta_str": "4"})
    assert first.percent == 50

    queue.pause()
    runner.complete()
    app.processEvents()
    assert first.status == "Completed"
    assert second.status == "Queued"
    assert queue.current is None

    queue.start()
    assert queue.current is second
    runner.complete(1, False)
    app.processEvents()
    assert second.status == "Failed"
    queue.retry(second)
    assert second.status == "Queued"


def test_queue_stop_marks_current_as_canceled(tmp_path):
    app = qt_app()
    runner = FakeRunner()
    queue = QueueController(runner, None)
    job = queue.add(DownloadSpec("https://example.com/1", str(tmp_path)), start_now=True)
    queue.stop_current()
    assert runner.stopped
    runner.complete(1, True)
    app.processEvents()
    assert job.status == "Canceled"


def test_process_runner_parses_progress_across_real_process(tmp_path):
    qt_app()
    script = tmp_path / "fake_engine.py"
    payload = json.dumps({"_percent_str": "75%", "_speed_str": "3MiB/s", "_eta_str": "2"})
    script.write_text(
        "import sys\n"
        f"print({(PROGRESS_PREFIX + payload)!r}, flush=True)\n"
        "print('human log', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )
    runner = ProcessRunner(sys.executable, [str(script)])
    progress = QSignalSpy(runner.progress)
    output = QSignalSpy(runner.output)
    finished = QSignalSpy(runner.finished)
    runner.start_download([])
    assert finished.wait(5000)
    assert progress.count() == 1
    assert progress.at(0)[0]["_percent_str"] == "75%"
    assert any("human log" in output.at(index)[0] for index in range(output.count()))
    assert finished.at(0) == [0, False]


def test_delayed_stop_cannot_kill_next_job(tmp_path):
    app = qt_app()
    script = tmp_path / "fake_engine.py"
    script.write_text(
        "import sys, time\n"
        "time.sleep(3 if sys.argv[-1].endswith('/next') else 0.3)\n",
        encoding="utf-8",
    )
    runner = ProcessRunner(sys.executable, [str(script)])
    queue = QueueController(runner, None)
    first = queue.add(DownloadSpec("https://example.com/first", str(tmp_path)))
    second = queue.add(DownloadSpec("https://example.com/next", str(tmp_path)))
    queue.start()
    while not runner.running:
        app.processEvents()
    queue.stop_current()
    deadline = __import__("time").monotonic() + 5
    while queue.current is not second and __import__("time").monotonic() < deadline:
        app.processEvents()
    assert first.status == "Canceled"
    assert queue.current is second
    assert not runner._stop_timer.isActive()
    runner._force_stop_tree()  # Simulates a stale callback from the canceled job.
    assert runner.running
    completed = QSignalSpy(queue.job_completed)
    assert completed.wait(5000)
    assert second.status == "Completed"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
def test_stop_reaps_child_process(tmp_path):
    import ctypes
    import subprocess

    app = qt_app()
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "parent.py"
    script.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(20)\n",
        encoding="utf-8",
    )
    runner = ProcessRunner(sys.executable, [str(script), str(pid_file)])
    finished = QSignalSpy(runner.finished)
    runner.start_download([])
    deadline = time.monotonic() + 5
    while not pid_file.exists() and time.monotonic() < deadline:
        app.processEvents()
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())

    def alive():
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, child_pid)
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        assert alive()
        runner.stop()
        assert finished.wait(5000)
        deadline = time.monotonic() + 3
        while alive() and time.monotonic() < deadline:
            app.processEvents()
        assert not alive()
    finally:
        if alive():
            subprocess.run(["taskkill", "/PID", str(child_pid), "/F"], capture_output=True, check=False)

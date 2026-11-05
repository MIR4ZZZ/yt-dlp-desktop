from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .core import DownloadSpec, QueueJob, build_download_args, parse_progress_line, progress_values


class ProcessRunner(QObject):
    analyzed = Signal(object)
    analysis_failed = Signal(str)
    progress = Signal(object)
    output = Signal(str)
    finished = Signal(int, bool)
    state_changed = Signal(bool)

    def __init__(self, program: str, prefix_args: list[str] | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.program = program
        self.prefix_args = list(prefix_args or [])
        self.process = QProcess(self)
        self.process.setProgram(program)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.started.connect(self._attach_windows_job)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self._mode = ""
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._analysis_output = ""
        self._analysis_error = ""
        self._canceled = False
        self._stopping_pid = 0
        self._job_handle = None
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._force_stop_tree)

    @property
    def running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start_analysis(self, arguments: list[str]) -> None:
        self._start("analysis", arguments)

    def start_download(self, arguments: list[str]) -> None:
        self._start("download", arguments)

    def _start(self, mode: str, arguments: list[str]) -> None:
        if self.running:
            raise RuntimeError("A process is already running.")
        self._stop_timer.stop()
        self._stopping_pid = 0
        self._mode = mode
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._analysis_output = ""
        self._analysis_error = ""
        self._canceled = False
        self.process.setArguments([*self.prefix_args, *arguments])
        self.state_changed.emit(True)
        self.process.start()

    def stop(self) -> None:
        if not self.running:
            return
        self._canceled = True
        self._stopping_pid = int(self.process.processId())
        self.output.emit("Stopping download…")
        self.process.terminate()
        self._stop_timer.start(1500)

    def _force_stop_tree(self) -> None:
        if not self._stopping_pid or int(self.process.processId()) != self._stopping_pid:
            return
        if sys.platform == "win32" and self._job_handle:
            import ctypes

            ctypes.windll.kernel32.TerminateJobObject(self._job_handle, 1)
            self._close_windows_job()
        if sys.platform == "win32" and self._stopping_pid:
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            if taskkill.exists():
                subprocess.run(
                    [str(taskkill), "/PID", str(self._stopping_pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
        if self.running:
            self.process.kill()

    def _attach_windows_job(self) -> None:
        if sys.platform != "win32" or self._job_handle:
            return
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000  # Kill child processes when the job closes.
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(information), ctypes.sizeof(information)):
            kernel32.CloseHandle(job)
            return
        process_handle = kernel32.OpenProcess(0x0100 | 0x0001, False, int(self.process.processId()))
        if not process_handle or not kernel32.AssignProcessToJobObject(job, process_handle):
            if process_handle:
                kernel32.CloseHandle(process_handle)
            kernel32.CloseHandle(job)
            return
        kernel32.CloseHandle(process_handle)
        self._job_handle = job

    def _close_windows_job(self) -> None:
        if sys.platform == "win32" and self._job_handle:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._job_handle)
            self._job_handle = None

    def _consume_lines(self, text: str, is_stderr: bool = False) -> None:
        attribute = "_stderr_buffer" if is_stderr else "_stdout_buffer"
        buffer = getattr(self, attribute) + text.replace("\r\n", "\n").replace("\r", "\n")
        lines = buffer.split("\n")
        setattr(self, attribute, lines.pop())
        for line in lines:
            if not line:
                continue
            if self._mode == "analysis" and not is_stderr:
                self._analysis_output += line + "\n"
                continue
            if self._mode == "analysis" and is_stderr:
                self._analysis_error += line + "\n"
            parsed = parse_progress_line(line) if not is_stderr else None
            if parsed is not None:
                self.progress.emit(parsed)
            else:
                self.output.emit(line)

    def _read_stdout(self) -> None:
        self._consume_lines(bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace"))

    def _read_stderr(self) -> None:
        self._consume_lines(bytes(self.process.readAllStandardError()).decode("utf-8", "replace"), is_stderr=True)

    def _flush_buffers(self) -> None:
        if self._stdout_buffer:
            self._consume_lines("\n")
        if self._stderr_buffer:
            self._consume_lines("\n", is_stderr=True)

    def _process_finished(self, exit_code: int, _exit_status) -> None:
        self._stop_timer.stop()
        self._read_stdout()
        self._read_stderr()
        self._flush_buffers()
        mode = self._mode
        self._mode = ""
        self._stopping_pid = 0
        self._close_windows_job()
        self.state_changed.emit(False)
        if mode == "analysis":
            if exit_code == 0:
                try:
                    candidates = [line for line in self._analysis_output.splitlines() if line.strip()]
                    data = json.loads(candidates[-1])
                    if not isinstance(data, dict):
                        raise ValueError
                except (IndexError, ValueError, json.JSONDecodeError):
                    self.analysis_failed.emit("yt-dlp returned metadata that could not be read.")
                else:
                    self.analyzed.emit(data)
            elif not self._canceled:
                message = self._analysis_error.strip() or "Could not analyze this link."
                self.analysis_failed.emit(message)
        else:
            self.finished.emit(exit_code, self._canceled)

    def _process_error(self, _error) -> None:
        if self.process.state() == QProcess.ProcessState.NotRunning and self._mode:
            self._stop_timer.stop()
            self._stopping_pid = 0
            message = self.process.errorString() or "The yt-dlp process could not start."
            mode = self._mode
            self._mode = ""
            self.state_changed.emit(False)
            self._close_windows_job()
            if mode == "analysis":
                self.analysis_failed.emit(message)
            else:
                self.output.emit(message)
                self.finished.emit(-1, self._canceled)


class QueueController(QObject):
    jobs_changed = Signal(object)
    current_changed = Signal(object)
    job_completed = Signal(object)

    def __init__(self, runner: ProcessRunner, ffmpeg_dir: str | None, parent: QObject | None = None):
        super().__init__(parent)
        self.runner = runner
        self.ffmpeg_dir = ffmpeg_dir
        self.jobs: list[QueueJob] = []
        self.current: QueueJob | None = None
        self.paused = True
        runner.progress.connect(self._on_progress)
        runner.output.connect(self._on_output)
        runner.finished.connect(self._on_finished)

    @property
    def active(self) -> bool:
        return self.current is not None or self.runner.running

    def add(self, spec: DownloadSpec, start_now: bool = False) -> QueueJob:
        job = QueueJob(uuid.uuid4().hex, spec)
        if start_now and self.current:
            index = self.jobs.index(self.current) + 1
            self.jobs.insert(index, job)
        else:
            self.jobs.append(job)
        self.jobs_changed.emit(self.jobs)
        if start_now:
            self.paused = False
            self._start_next()
        return job

    def start(self) -> None:
        self.paused = False
        self._start_next()

    def pause(self) -> None:
        self.paused = True
        self.jobs_changed.emit(self.jobs)

    def stop_current(self) -> None:
        if self.current:
            self.current.status = "Stopping"
            self.jobs_changed.emit(self.jobs)
            self.runner.stop()

    def retry(self, job: QueueJob) -> None:
        if job is self.current:
            return
        job.status = "Queued"
        job.percent = 0
        job.speed = ""
        job.eta = ""
        job.log.clear()
        self.jobs_changed.emit(self.jobs)

    def remove(self, job: QueueJob) -> None:
        if job is self.current:
            return
        if job in self.jobs:
            self.jobs.remove(job)
            self.jobs_changed.emit(self.jobs)

    def move(self, job: QueueJob, offset: int) -> None:
        if job is self.current or job not in self.jobs:
            return
        old = self.jobs.index(job)
        new = min(len(self.jobs) - 1, max(0, old + offset))
        if new != old:
            self.jobs.insert(new, self.jobs.pop(old))
            self.jobs_changed.emit(self.jobs)

    def _start_next(self) -> None:
        if self.paused or self.active:
            return
        job = next((item for item in self.jobs if item.status == "Queued"), None)
        if job is None:
            self.paused = True
            self.jobs_changed.emit(self.jobs)
            return
        self.current = job
        job.status = "Downloading"
        job.log.append(f"Starting {job.spec.url}")
        self.current_changed.emit(job)
        self.jobs_changed.emit(self.jobs)
        try:
            self.runner.start_download(build_download_args(job.spec, self.ffmpeg_dir))
        except Exception as error:
            job.status = "Failed"
            job.log.append(str(error))
            self.current = None
            self.current_changed.emit(None)
            self.jobs_changed.emit(self.jobs)
            QTimer.singleShot(0, self._start_next)

    def _on_progress(self, data: dict) -> None:
        if not self.current:
            return
        self.current.percent, self.current.speed, self.current.eta = progress_values(data)
        status = str(data.get("status") or "downloading")
        self.current.status = "Processing" if status == "finished" else "Downloading"
        self.jobs_changed.emit(self.jobs)

    def _on_output(self, text: str) -> None:
        if not self.current:
            return
        self.current.log.append(text)
        del self.current.log[:-1000]
        self.current_changed.emit(self.current)

    def _on_finished(self, exit_code: int, canceled: bool) -> None:
        if not self.current:
            return
        job = self.current
        if canceled:
            job.status = "Canceled"
        elif exit_code == 0:
            job.status = "Completed"
            job.percent = 100
            self.job_completed.emit(job)
        else:
            job.status = "Failed"
        self.current = None
        self.current_changed.emit(None)
        self.jobs_changed.emit(self.jobs)
        if not self.paused:
            QTimer.singleShot(0, self._start_next)

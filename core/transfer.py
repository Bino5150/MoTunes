"""
MoTunes - Transfer Engine
Handles file copy operations to/from iPhone with progress tracking
"""

import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from enum import Enum


class TransferDirection(Enum):
    FROM_DEVICE = "from_device"
    TO_DEVICE = "to_device"


class TransferStatus(Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TransferJob:
    source: str
    destination: str
    filename: str
    file_size_bytes: int = 0
    direction: TransferDirection = TransferDirection.FROM_DEVICE
    status: TransferStatus = TransferStatus.QUEUED
    bytes_transferred: int = 0
    error: str = ""

    @property
    def progress(self) -> float:
        if self.file_size_bytes == 0:
            return 1.0 if self.status == TransferStatus.COMPLETE else 0.0
        return min(self.bytes_transferred / self.file_size_bytes, 1.0)

    @property
    def progress_pct(self) -> int:
        return int(self.progress * 100)


def _sanitize_filename(name: str) -> str:
    """Strip characters that are illegal in Linux/Mac/Windows filenames."""
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = name.strip(". ")
    return name or "Unknown"


def build_export_filename(track) -> str:
    """
    Build a clean 'Artist - Title.ext' filename from a Track object.
    Falls back gracefully if tags are missing.
    """
    from pathlib import Path
    ext = Path(track.filename).suffix.lower()
    artist = _sanitize_filename(track.display_artist)
    title = _sanitize_filename(track.display_title)
    return f"{artist} - {title}{ext}"


class TransferEngine:
    def __init__(self):
        self._queue: List[TransferJob] = []
        self._running = False
        self._cancel_requested = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._on_job_start: Optional[Callable] = None
        self._on_job_progress: Optional[Callable] = None
        self._on_job_complete: Optional[Callable] = None
        self._on_all_complete: Optional[Callable] = None
        self._chunk_size = 1024 * 512  # 512KB chunks

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def cancel(self):
        """
        Request the running worker to stop. Cooperative, not preemptive:
        the worker notices this between chunks of the file it's currently
        copying (worst case one chunk's I/O time later) and between jobs,
        cleans up the partial destination file for whatever job it was
        mid-copy on, and marks it FAILED rather than leaving a truncated
        file behind. Does not block — call join() to wait for the worker
        to actually stop before doing anything that assumes it has (like
        unmounting the filesystem it's writing to/reading from).
        """
        with self._lock:
            self._cancel_requested = True

    def join(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for the worker thread to actually stop. Returns True if it's
        stopped (or there was never one running) within timeout, False if
        it's still alive when the timeout elapses. Callers that need to be
        sure no write is still in flight (e.g. before unmounting) must
        check this return value — cancel() alone only requests the stop,
        it doesn't confirm it happened.
        """
        thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def set_callbacks(
        self,
        on_job_start=None,
        on_job_progress=None,
        on_job_complete=None,
        on_all_complete=None,
    ):
        self._on_job_start = on_job_start
        self._on_job_progress = on_job_progress
        self._on_job_complete = on_job_complete
        self._on_all_complete = on_all_complete

    def add_job(self, source: str, destination: str, direction: TransferDirection) -> TransferJob:
        fname = os.path.basename(source)
        size = os.path.getsize(source) if os.path.exists(source) else 0
        job = TransferJob(
            source=source,
            destination=destination,
            filename=fname,
            file_size_bytes=size,
            direction=direction,
        )
        with self._lock:
            self._queue.append(job)
        return job

    def add_jobs(self, sources: List[str], dest_dir: str, direction: TransferDirection):
        """Add jobs using original filenames (for photos, generic files)."""
        for src in sources:
            dest = os.path.join(dest_dir, os.path.basename(src))
            self.add_job(src, dest, direction)

    def add_track_export_jobs(self, tracks: list, dest_dir: str):
        """
        Add export jobs for Track objects, renaming to 'Artist - Title.ext'.
        Handles duplicate filenames by appending a counter.
        """
        seen_names = {}
        for track in tracks:
            clean_name = build_export_filename(track)
            # Deduplicate: if 'Artist - Title.mp3' already queued, use 'Artist - Title (2).mp3'
            if clean_name in seen_names:
                seen_names[clean_name] += 1
                base, ext = os.path.splitext(clean_name)
                clean_name = f"{base} ({seen_names[clean_name]}){ext}"
            else:
                seen_names[clean_name] = 1
            dest = os.path.join(dest_dir, clean_name)
            self.add_job(track.path, dest, TransferDirection.FROM_DEVICE)

    def start(self):
        """
        Begin draining the queue in a background thread.
        A no-op if a worker is already running — safe to call repeatedly
        (e.g. from a UI button) without ever spawning a second worker.
        """
        with self._lock:
            if self._running:
                return
            self._running = True
            # A cancel() from a previous batch (e.g. one that was already
            # idle when cancelled) must not immediately kill this new run.
            self._cancel_requested = False
            thread = threading.Thread(target=self._run, daemon=True)
            self._thread = thread
        thread.start()

    def _next_queued_job(self) -> Optional[TransferJob]:
        """
        Pull the next QUEUED job under lock, unless a cancellation is
        pending — in which case stop handing out new jobs entirely rather
        than starting one only to abort it immediately. Jobs added via
        add_job/add_jobs while a worker is already draining the queue are
        picked up here too, so a second start() call is never needed to
        process them.
        """
        with self._lock:
            if self._cancel_requested:
                return None
            for job in self._queue:
                if job.status == TransferStatus.QUEUED:
                    return job
        return None

    def _run(self):
        while True:
            job = self._next_queued_job()
            if job is None:
                break
            self._execute_job(job)
        with self._lock:
            self._running = False
        if self._on_all_complete:
            self._on_all_complete()

    def _execute_job(self, job: TransferJob):
        job.status = TransferStatus.IN_PROGRESS
        if self._on_job_start:
            self._on_job_start(job)

        try:
            dest_dir = os.path.dirname(job.destination)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)

            # Skip if destination exists and same size
            if os.path.exists(job.destination):
                dest_size = os.path.getsize(job.destination)
                if dest_size == job.file_size_bytes:
                    job.status = TransferStatus.SKIPPED
                    if self._on_job_complete:
                        self._on_job_complete(job)
                    return

            # Copy with progress. Checked once per chunk (worst case one
            # chunk's I/O time before a cancel() is noticed) rather than
            # only between whole files — a multi-hundred-MB file must not
            # be able to hold up a requested cancellation indefinitely.
            src_stat = os.stat(job.source)
            cancelled = False
            with open(job.source, "rb") as src_f, open(job.destination, "wb") as dst_f:
                while True:
                    with self._lock:
                        if self._cancel_requested:
                            cancelled = True
                    if cancelled:
                        break
                    chunk = src_f.read(self._chunk_size)
                    if not chunk:
                        break
                    dst_f.write(chunk)
                    job.bytes_transferred += len(chunk)
                    if self._on_job_progress:
                        self._on_job_progress(job)

            if cancelled:
                # A truncated file left behind (on the device, for a
                # TO_DEVICE job) is worse than no file at all — this job
                # owns job.destination exclusively (just opened it in "wb"
                # truncate mode above), so removing it here is safe.
                try:
                    os.remove(job.destination)
                except Exception:
                    pass
                job.status = TransferStatus.FAILED
                job.error = "Cancelled"
                if self._on_job_complete:
                    self._on_job_complete(job)
                return

            # Preserve original timestamps so exported files retain their "date taken"
            # instead of showing the export time (ifuse doesn't expose real mtimes on copy)
            try:
                os.utime(job.destination, (src_stat.st_atime, src_stat.st_mtime))
            except Exception:
                pass

            job.status = TransferStatus.COMPLETE

        except Exception as e:
            job.status = TransferStatus.FAILED
            job.error = str(e)
            print(f"[TransferEngine] Failed: {job.filename} — {e}")

        if self._on_job_complete:
            self._on_job_complete(job)

    def clear(self):
        """
        Drop queued/completed/failed/skipped jobs; preserve anything actively
        mid-copy. Safe to call while a worker is running — it only ever
        reassigns the queue reference under lock, so the worker's own
        completion never races this and silently wipes a freshly queued batch.
        """
        with self._lock:
            self._queue = [j for j in self._queue if j.status == TransferStatus.IN_PROGRESS]

    @property
    def queued_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._queue if j.status == TransferStatus.QUEUED)

    @property
    def queue(self) -> List[TransferJob]:
        with self._lock:
            return list(self._queue)

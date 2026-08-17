"""
Regression coverage for the hardened close/unmount-safety path: a checkpoint
review found that MainWindow.closeEvent's "Quit anyway" branch unmounted
immediately on confirmation, with zero coordination with an active
TO_DEVICE transfer worker thread — the exact device-corruption risk Finding
9 was supposed to close. This file covers the mechanism that fix depends
on: TransferEngine.cancel()/join() must genuinely stop an in-flight copy
(not just set an ignored flag) and clean up the partial file it leaves
behind, rather than leaving a truncated file sitting where a device write
was headed.

All jobs operate on real temp files, never on a device. Synchronization
uses threading.Event, not sleeps, so timing is deterministic.
"""
import threading
import time

from core.transfer import TransferEngine, TransferDirection, TransferStatus


def _wait_until(predicate, timeout=5.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_cancel_stops_worker_mid_copy_and_removes_partial_file(tmp_path):
    """
    Core mechanism proof: cancel() must actually stop the worker (not just
    flip an ignored flag), and the partial destination file — exactly what
    would otherwise sit corrupted on a device after a force-unmount — must
    be cleaned up.
    """
    engine = TransferEngine()
    engine._chunk_size = 1024  # force many small chunks so cancellation has room to land mid-copy

    progressed = threading.Event()
    hold = threading.Event()

    def on_job_progress(job):
        progressed.set()
        hold.wait(timeout=5)

    engine.set_callbacks(on_job_progress=on_job_progress)

    src = tmp_path / "big.bin"
    src.write_bytes(b"x" * (1024 * 50))  # 50 chunks at the small chunk size above
    dest = tmp_path / "out" / "big.bin"
    engine.add_job(str(src), str(dest), TransferDirection.TO_DEVICE)
    engine.start()

    assert progressed.wait(timeout=5), "first chunk's progress callback never fired"
    assert dest.exists(), "destination file should exist mid-copy, before cancellation"

    engine.cancel()
    hold.set()  # let the blocked progress callback return so the copy loop can re-check cancel state

    assert engine.join(timeout=5), "join() must confirm the worker actually stopped after cancel()"
    assert engine.is_running is False
    assert not dest.exists(), (
        "a cancelled TO_DEVICE job must not leave a partial/truncated file behind"
    )

    jobs = engine.queue
    assert len(jobs) == 1
    assert jobs[0].status == TransferStatus.FAILED
    assert "cancel" in jobs[0].error.lower()


def test_cancel_prevents_remaining_queued_jobs_from_starting(tmp_path):
    """
    cancel() must stop the worker from picking up further queued jobs, not
    just abort whatever job happened to be in flight at the moment.
    """
    engine = TransferEngine()
    hold = threading.Event()
    started = []

    def on_job_start(job):
        started.append(job.filename)
        if job.filename == "first.bin":
            hold.wait(timeout=5)

    engine.set_callbacks(on_job_start=on_job_start)

    dst_dir = tmp_path / "out"
    for name in ("first.bin", "second.bin", "third.bin"):
        p = tmp_path / name
        p.write_bytes(b"x" * 4096)
        engine.add_job(str(p), str(dst_dir / name), TransferDirection.TO_DEVICE)

    engine.start()
    assert _wait_until(lambda: "first.bin" in started)

    engine.cancel()
    hold.set()

    assert engine.join(timeout=5)
    assert "second.bin" not in started, "cancel() must stop further jobs from starting"
    assert "third.bin" not in started

    statuses = {j.filename: j.status for j in engine.queue}
    assert statuses["first.bin"] == TransferStatus.FAILED
    # Untouched queued jobs are left as-is (never wrote anything, nothing
    # to clean up) — still observable in the queue, not silently dropped.
    assert statuses["second.bin"] == TransferStatus.QUEUED
    assert statuses["third.bin"] == TransferStatus.QUEUED


def test_join_is_a_safe_noop_when_nothing_is_running(tmp_path):
    engine = TransferEngine()
    assert engine.join(timeout=1) is True

    engine.cancel()  # cancelling an idle engine must not wedge the next run
    assert engine.join(timeout=1) is True


def test_cancel_flag_does_not_leak_into_next_batch(tmp_path):
    """
    A cancel() issued (or left over) while idle must not immediately
    cancel the *next* start() — start() must reset the flag for its own
    fresh run.
    """
    engine = TransferEngine()
    engine.cancel()  # simulate a stray/idle cancel with no worker running

    completed = threading.Event()
    engine.set_callbacks(on_all_complete=completed.set)

    src = tmp_path / "a.bin"
    src.write_bytes(b"x" * 4096)
    engine.add_job(str(src), str(tmp_path / "out" / "a.bin"), TransferDirection.FROM_DEVICE)
    engine.start()

    assert completed.wait(timeout=5)
    jobs = engine.queue
    assert jobs[0].status == TransferStatus.COMPLETE, (
        "a stale cancel flag from before start() must not abort the new batch"
    )


def test_uncancelled_transfer_completes_normally(tmp_path):
    """Sanity check: the cancellation machinery must not affect the
    ordinary, uninterrupted completion path."""
    engine = TransferEngine()
    completed = threading.Event()
    engine.set_callbacks(on_all_complete=completed.set)

    src = tmp_path / "a.bin"
    src.write_bytes(b"x" * 8192)
    dest = tmp_path / "out" / "a.bin"
    engine.add_job(str(src), str(dest), TransferDirection.FROM_DEVICE)
    engine.start()

    assert completed.wait(timeout=5)
    assert dest.exists()
    assert dest.read_bytes() == src.read_bytes()
    assert engine.queue[0].status == TransferStatus.COMPLETE

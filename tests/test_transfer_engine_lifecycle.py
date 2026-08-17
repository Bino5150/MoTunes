"""
Regression coverage for Finding 6 / Slice D: TransferEngine start()/clear()
lifecycle hardening.

All jobs operate on real temp files, never on a device. No sleeps are used
to synchronize with the worker thread — tests block on threading.Event
objects set from inside TransferEngine callbacks (which run on the worker
thread), so timing is deterministic.
"""
import os
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


def test_start_cannot_create_concurrent_workers(tmp_path):
    """Requirement 1: start() cannot create concurrent workers."""
    engine = TransferEngine()
    entered = threading.Event()
    proceed = threading.Event()

    def on_job_start(job):
        entered.set()
        proceed.wait(timeout=5)

    engine.set_callbacks(on_job_start=on_job_start)

    src = tmp_path / "a.bin"
    src.write_bytes(b"x" * 4096)
    engine.add_job(str(src), str(tmp_path / "out" / "a.bin"), TransferDirection.FROM_DEVICE)

    engine.start()
    assert entered.wait(timeout=5), "worker never started"
    assert engine.is_running is True

    thread_before = engine._thread
    engine.start()  # must be a no-op while a worker is active
    assert engine._thread is thread_before, "start() spawned a second worker thread"

    proceed.set()
    assert _wait_until(lambda: not engine.is_running)


def test_new_batch_not_erased_by_completing_old_batch(tmp_path):
    """
    Requirement 2: a new batch queued while a worker is still finishing its
    previous batch must not be silently wiped by that worker's own
    completion bookkeeping. This is the exact TOCTOU from the audit: the
    old code reassigned self._queue in both clear() (main thread) and at
    the end of _run() (worker thread), so whichever ran last won and could
    wipe out jobs the other side had just queued.
    """
    engine = TransferEngine()
    started = []
    hold_first = threading.Event()

    def on_job_start(job):
        started.append(job.filename)
        if job.filename == "first.bin":
            hold_first.wait(timeout=5)

    engine.set_callbacks(on_job_start=on_job_start)

    dst_dir = tmp_path / "out"
    first_src = tmp_path / "first.bin"
    first_src.write_bytes(b"a" * 2048)
    engine.add_job(str(first_src), str(dst_dir / "first.bin"), TransferDirection.FROM_DEVICE)
    engine.start()

    assert _wait_until(lambda: "first.bin" in started), "first job never started"
    assert engine.is_running is True

    # Simulate the UI queuing a second batch while the engine is still
    # "running" (as MusicTab/MyComputerTab do: clear() then add_jobs() then
    # start()).
    engine.clear()
    second_src = tmp_path / "second.bin"
    second_src.write_bytes(b"b" * 2048)
    engine.add_job(str(second_src), str(dst_dir / "second.bin"), TransferDirection.TO_DEVICE)
    engine.start()  # must not spawn a second worker, and must not lose this job

    hold_first.set()  # let the first job finish so the worker can drain the rest

    assert _wait_until(lambda: not engine.is_running), "engine never finished draining"

    statuses = {j.filename: j.status for j in engine.queue}
    assert statuses.get("first.bin") == TransferStatus.COMPLETE
    assert statuses.get("second.bin") == TransferStatus.COMPLETE, (
        "second batch was silently dropped by the first batch's completion"
    )


def test_queue_state_after_completion_is_deterministic(tmp_path):
    """
    Requirement 3: after on_all_complete fires, the queue must reflect the
    real final state of every job — not be wiped out from under the
    callback (the old _run() cleared self._queue *before* invoking
    on_all_complete).
    """
    engine = TransferEngine()
    completed = threading.Event()
    engine.set_callbacks(on_all_complete=completed.set)

    src = tmp_path / "a.bin"
    src.write_bytes(b"x" * 4096)
    engine.add_job(str(src), str(tmp_path / "out" / "a.bin"), TransferDirection.FROM_DEVICE)
    engine.start()

    assert completed.wait(timeout=5)
    assert engine.is_running is False

    jobs = engine.queue
    assert len(jobs) == 1
    assert jobs[0].status == TransferStatus.COMPLETE
    assert jobs[0].filename == "a.bin"


def test_failed_job_remains_observable(tmp_path):
    """Requirement 4: failed jobs remain observable, not silently dropped."""
    engine = TransferEngine()
    completed = threading.Event()
    engine.set_callbacks(on_all_complete=completed.set)

    missing_src = str(tmp_path / "does_not_exist.bin")
    dest = str(tmp_path / "out" / "does_not_exist.bin")
    engine.add_job(missing_src, dest, TransferDirection.FROM_DEVICE)
    engine.start()

    assert completed.wait(timeout=5)

    jobs = engine.queue
    assert len(jobs) == 1
    assert jobs[0].status == TransferStatus.FAILED
    assert jobs[0].error, "FAILED job must carry an observable error message"


def test_clear_preserves_in_progress_job(tmp_path):
    """clear() must not touch a job that's actively mid-copy."""
    engine = TransferEngine()
    entered = threading.Event()
    proceed = threading.Event()

    def on_job_start(job):
        entered.set()
        proceed.wait(timeout=5)

    engine.set_callbacks(on_job_start=on_job_start)
    src = tmp_path / "a.bin"
    src.write_bytes(b"x" * 2048)
    engine.add_job(str(src), str(tmp_path / "out" / "a.bin"), TransferDirection.FROM_DEVICE)
    engine.start()

    assert entered.wait(timeout=5)
    engine.clear()
    assert len(engine.queue) == 1, "clear() dropped a job that was actively IN_PROGRESS"
    assert engine.queue[0].status == TransferStatus.IN_PROGRESS

    proceed.set()
    assert _wait_until(lambda: not engine.is_running)

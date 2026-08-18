"""
Regression coverage for Phase 0B Slice 2, spec items 13-15: mechanical
write gating lives in TransferEngine and PhotoDeleteWorker themselves,
not just in the UI buttons that normally call them — so a caller that
invokes start()/add_jobs() directly, bypassing any disabled button,
still can't perform a device write once capability denies it.

These exercise core/transfer.py and core/photos.py directly with real
background threads (join()'d before assertions), no Qt and no UI layer
involved — core/transfer.py and core/photos.py never import
core/capability.py at all, so these predicates are plain bool callables,
proving the gate works independent of how the caller decides "can_write".
"""
import os
import threading

from core.transfer import TransferEngine, TransferDirection, TransferStatus
from core.photos import PhotoDeleteWorker, DeleteUnit, Photo


def _photo(path, is_video=False) -> Photo:
    return Photo(path=str(path), filename=os.path.basename(str(path)), is_video=is_video)


# ── 13. Direct invocation cannot bypass a disabled UI control ───────────────

def test_transfer_engine_direct_start_refuses_to_device_job_when_writes_denied(tmp_path):
    """No UI button involved at all — construct the engine, queue a
    TO_DEVICE job, and start() it directly."""
    src = tmp_path / "song.mp3"
    src.write_bytes(b"x" * 4096)
    dest = tmp_path / "on_device" / "song.mp3"

    engine = TransferEngine(can_write=lambda: False)
    job = engine.add_job(str(src), str(dest), TransferDirection.TO_DEVICE)
    engine.start()
    assert engine.join(timeout=5)

    assert job.status == TransferStatus.FAILED
    assert not dest.exists(), "no file must ever be written to the device-side destination"
    assert "disabled" in job.error.lower() or "capability" in job.error.lower()


def test_photo_delete_worker_direct_start_refuses_when_writes_denied(tmp_path):
    f = tmp_path / "IMG_0001.HEIC"
    f.write_bytes(b"x")
    worker = PhotoDeleteWorker(can_write=lambda: False)

    started = worker.start([DeleteUnit(still=_photo(f))])

    assert started is False, "start() must refuse outright, not silently no-op a spawned thread"
    assert f.exists(), "the file must not have been touched"
    assert worker.is_running is False


# ── 14. Photos deletion performs zero os.remove() calls when denied ─────────

def test_delete_worker_denied_performs_zero_os_remove_calls(tmp_path, monkeypatch):
    f = tmp_path / "IMG_0002.HEIC"
    f.write_bytes(b"x")
    remove_calls = []
    monkeypatch.setattr("core.photos.os.remove", lambda p: remove_calls.append(p))

    worker = PhotoDeleteWorker(can_write=lambda: False)
    started = worker.start([DeleteUnit(still=_photo(f))])

    assert started is False
    assert remove_calls == [], "zero os.remove() calls — the worker thread must never even spawn"


def test_delete_worker_with_live_photo_pair_performs_zero_os_remove_calls_when_denied(tmp_path, monkeypatch):
    still_f = tmp_path / "IMG_0003.HEIC"
    mov_f = tmp_path / "IMG_0003.MOV"
    still_f.write_bytes(b"x")
    mov_f.write_bytes(b"y")
    remove_calls = []
    monkeypatch.setattr("core.photos.os.remove", lambda p: remove_calls.append(p))

    still = _photo(still_f)
    companion = _photo(mov_f, is_video=True)
    worker = PhotoDeleteWorker(can_write=lambda: False)
    started = worker.start([DeleteUnit(still=still, companion=companion)])

    assert started is False
    assert remove_calls == []
    assert still_f.exists() and mov_f.exists()


def test_delete_worker_allowed_after_being_denied_still_works(tmp_path):
    """The predicate is read live at call time, not cached at
    construction — flipping it back to allowed must immediately unblock
    start(), proving this is a real gate and not a one-shot latch."""
    f = tmp_path / "IMG_0004.HEIC"
    f.write_bytes(b"x")
    state = {"can_write": False}
    worker = PhotoDeleteWorker(can_write=lambda: state["can_write"])

    assert worker.start([DeleteUnit(still=_photo(f))]) is False
    assert f.exists()

    state["can_write"] = True
    assert worker.start([DeleteUnit(still=_photo(f))]) is True
    assert worker.join(timeout=5)
    assert not f.exists()


# ── 15. TO_DEVICE transfer performs zero writes when denied; FROM_DEVICE unaffected

def test_to_device_job_writes_zero_bytes_when_denied(tmp_path):
    src = tmp_path / "track.mp3"
    src.write_bytes(b"x" * 1024 * 1024)
    dest = tmp_path / "device" / "track.mp3"

    engine = TransferEngine(can_write=lambda: False)
    engine.add_jobs([str(src)], str(dest.parent), TransferDirection.TO_DEVICE)
    engine.start()
    assert engine.join(timeout=5)

    assert not dest.parent.exists() or not any(dest.parent.iterdir()), (
        "a denied TO_DEVICE job must never create/open the destination file at all"
    )


def test_from_device_export_is_unaffected_by_write_denial(tmp_path):
    """Reading from the device (export) is not a write to it — denying
    device writes must not also block exporting."""
    src = tmp_path / "on_device.mp3"
    src.write_bytes(b"x" * 2048)
    dest_dir = tmp_path / "exported"

    engine = TransferEngine(can_write=lambda: False)
    engine.add_jobs([str(src)], str(dest_dir), TransferDirection.FROM_DEVICE)
    engine.start()
    assert engine.join(timeout=5)

    exported = dest_dir / "on_device.mp3"
    assert exported.exists(), "FROM_DEVICE jobs must not be gated by the write-capability predicate"
    assert exported.read_bytes() == src.read_bytes()


def test_mixed_queue_blocks_to_device_but_completes_from_device(tmp_path):
    """A queue with both directions (as could happen if a caller reuses
    one engine) must gate per-job, not all-or-nothing."""
    device_src = tmp_path / "on_device.mp3"
    device_src.write_bytes(b"d" * 1024)
    local_src = tmp_path / "local.mp3"
    local_src.write_bytes(b"l" * 1024)
    export_dir = tmp_path / "exported"
    device_dest = tmp_path / "device" / "local.mp3"

    engine = TransferEngine(can_write=lambda: False)
    engine.add_job(str(device_src), str(export_dir / "on_device.mp3"), TransferDirection.FROM_DEVICE)
    engine.add_job(str(local_src), str(device_dest), TransferDirection.TO_DEVICE)
    engine.start()
    assert engine.join(timeout=5)

    statuses = {j.direction: j.status for j in engine.queue}
    assert statuses[TransferDirection.FROM_DEVICE] == TransferStatus.COMPLETE
    assert statuses[TransferDirection.TO_DEVICE] == TransferStatus.FAILED
    assert not device_dest.exists()

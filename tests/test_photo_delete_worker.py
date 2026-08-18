"""
Core-level regression coverage for Finding B (background deletion) and
Finding C (Live Photo pairing) at the core/photos.py layer: PhotoDeleteWorker
and find_live_photo_companion(). UI wiring (PhotosTab) is covered separately.

All deletes operate on real temp files — no real device involved.
"""
import os
import threading

from core.photos import DeleteUnit, Photo, PhotoDeleteWorker, find_live_photo_companion


def _photo(path: str, is_video=False, is_live_photo=False) -> Photo:
    return Photo(path=path, filename=os.path.basename(path),
                 is_video=is_video, is_live_photo=is_live_photo)


# ── find_live_photo_companion ────────────────────────────────────────────────

def test_finds_companion_with_matching_dir_and_stem():
    still = _photo("/mnt/DCIM/100APPLE/IMG_0001.HEIC")
    companion = _photo("/mnt/DCIM/100APPLE/IMG_0001.MOV", is_video=True, is_live_photo=True)
    other = _photo("/mnt/DCIM/100APPLE/IMG_0002.HEIC")

    result = find_live_photo_companion(still, [still, companion, other])
    assert result is companion


def test_ordinary_still_has_no_companion():
    still = _photo("/mnt/DCIM/100APPLE/IMG_0001.HEIC")
    unrelated_video = _photo("/mnt/DCIM/100APPLE/IMG_0002.MOV", is_video=True, is_live_photo=False)

    result = find_live_photo_companion(still, [still, unrelated_video])
    assert result is None


def test_video_input_never_has_a_companion():
    video = _photo("/mnt/DCIM/100APPLE/IMG_0001.MOV", is_video=True, is_live_photo=True)
    result = find_live_photo_companion(video, [video])
    assert result is None


def test_companion_in_different_directory_is_not_matched():
    still = _photo("/mnt/DCIM/100APPLE/IMG_0001.HEIC")
    wrong_dir_companion = _photo("/mnt/DCIM/101APPLE/IMG_0001.MOV", is_video=True, is_live_photo=True)

    result = find_live_photo_companion(still, [still, wrong_dir_companion])
    assert result is None


def test_stem_matching_is_case_insensitive():
    still = _photo("/mnt/DCIM/100APPLE/img_0001.HEIC")
    companion = _photo("/mnt/DCIM/100APPLE/IMG_0001.MOV", is_video=True, is_live_photo=True)

    result = find_live_photo_companion(still, [still, companion])
    assert result is companion


def test_non_live_mov_with_matching_stem_is_not_treated_as_companion():
    """A .MOV that happens to share a stem but was never flagged
    is_live_photo by the scanner (e.g. a coincidentally-named standalone
    video) must not be treated as a companion."""
    still = _photo("/mnt/DCIM/100APPLE/IMG_0001.HEIC")
    coincidental_video = _photo("/mnt/DCIM/100APPLE/IMG_0001.MOV", is_video=True, is_live_photo=False)

    result = find_live_photo_companion(still, [still, coincidental_video])
    assert result is None


# ── PhotoDeleteWorker ─────────────────────────────────────────────────────────

def _wait_until(predicate, timeout=5.0, interval=0.01):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_deletes_standalone_unit_successfully(tmp_path):
    f = tmp_path / "IMG_0001.HEIC"
    f.write_bytes(b"x")
    still = _photo(str(f))

    worker = PhotoDeleteWorker()
    results = []
    completed = threading.Event()
    worker.set_callbacks(on_result=results.append, on_all_complete=completed.set)

    assert worker.start([DeleteUnit(still=still)]) is True
    assert completed.wait(timeout=5)

    assert not f.exists()
    assert len(results) == 1
    assert results[0].still_deleted is True
    assert results[0].companion is None
    assert results[0].fully_deleted is True


def test_deletes_paired_unit_companion_first(tmp_path):
    still_f = tmp_path / "IMG_0001.HEIC"
    mov_f = tmp_path / "IMG_0001.MOV"
    still_f.write_bytes(b"x")
    mov_f.write_bytes(b"y")
    still = _photo(str(still_f))
    companion = _photo(str(mov_f), is_video=True, is_live_photo=True)

    delete_order = []
    orig_remove = os.remove

    def tracking_remove(path):
        delete_order.append(path)
        orig_remove(path)

    worker = PhotoDeleteWorker()
    results = []
    completed = threading.Event()
    worker.set_callbacks(on_result=results.append, on_all_complete=completed.set)

    import unittest.mock
    with unittest.mock.patch("core.photos.os.remove", side_effect=tracking_remove):
        worker.start([DeleteUnit(still=still, companion=companion)])
        assert completed.wait(timeout=5)

    assert delete_order == [str(mov_f), str(still_f)], (
        "companion (motion component) must be deleted before the still"
    )
    assert not still_f.exists()
    assert not mov_f.exists()
    assert results[0].still_deleted is True
    assert results[0].companion_deleted is True
    assert results[0].fully_deleted is True


def test_companion_delete_failure_leaves_still_untouched(tmp_path):
    """If the companion delete fails, the still must not be deleted —
    the pair is reported as a failure, not silently half-completed."""
    still_f = tmp_path / "IMG_0001.HEIC"
    still_f.write_bytes(b"x")
    still = _photo(str(still_f))
    # Companion path doesn't exist on disk — os.remove() will raise.
    companion = _photo(str(tmp_path / "IMG_0001.MOV"), is_video=True, is_live_photo=True)

    worker = PhotoDeleteWorker()
    results = []
    completed = threading.Event()
    worker.set_callbacks(on_result=results.append, on_all_complete=completed.set)

    worker.start([DeleteUnit(still=still, companion=companion)])
    assert completed.wait(timeout=5)

    assert still_f.exists(), "still must NOT be deleted when the companion delete failed"
    assert results[0].companion_deleted is False
    assert results[0].still_deleted is False
    assert results[0].fully_deleted is False
    assert "companion" in results[0].error.lower()


def test_standalone_delete_failure_is_reported_truthfully(tmp_path):
    missing = _photo(str(tmp_path / "does_not_exist.jpg"))

    worker = PhotoDeleteWorker()
    results = []
    completed = threading.Event()
    worker.set_callbacks(on_result=results.append, on_all_complete=completed.set)

    worker.start([DeleteUnit(still=missing)])
    assert completed.wait(timeout=5)

    assert results[0].still_deleted is False
    assert results[0].fully_deleted is False
    assert results[0].error


def test_partial_batch_failure_reports_each_unit_independently(tmp_path):
    good_f = tmp_path / "good.jpg"
    good_f.write_bytes(b"x")
    good = _photo(str(good_f))
    missing = _photo(str(tmp_path / "missing.jpg"))

    worker = PhotoDeleteWorker()
    results = []
    completed = threading.Event()
    worker.set_callbacks(on_result=results.append, on_all_complete=completed.set)

    worker.start([DeleteUnit(still=good), DeleteUnit(still=missing)])
    assert completed.wait(timeout=5)

    assert len(results) == 2
    by_path = {r.still.path: r for r in results}
    assert by_path[str(good_f)].fully_deleted is True
    assert by_path[str(missing.path)].fully_deleted is False
    assert not good_f.exists()


def test_start_cannot_create_concurrent_workers(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"x")
    still = _photo(str(f))

    entered = threading.Event()
    proceed = threading.Event()
    orig_remove = os.remove

    def blocking_remove(path):
        entered.set()
        proceed.wait(timeout=5)
        orig_remove(path)

    worker = PhotoDeleteWorker()
    completed = threading.Event()
    worker.set_callbacks(on_all_complete=completed.set)

    import unittest.mock
    with unittest.mock.patch("core.photos.os.remove", side_effect=blocking_remove):
        assert worker.start([DeleteUnit(still=still)]) is True
        assert entered.wait(timeout=5)
        assert worker.is_running is True

        second_f = tmp_path / "b.jpg"
        second_f.write_bytes(b"y")
        assert worker.start([DeleteUnit(still=_photo(str(second_f)))]) is False, (
            "start() must refuse to spawn a second concurrent delete worker"
        )

        proceed.set()
        assert completed.wait(timeout=5)

    assert not f.exists()
    assert second_f.exists(), "the rejected second batch must never have been processed"


def test_join_confirms_worker_actually_stopped(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"x")
    still = _photo(str(f))

    worker = PhotoDeleteWorker()
    assert worker.join(timeout=1) is True  # nothing running — safe no-op

    completed = threading.Event()
    worker.set_callbacks(on_all_complete=completed.set)
    worker.start([DeleteUnit(still=still)])
    assert completed.wait(timeout=5)

    assert worker.join(timeout=5) is True
    assert worker.is_running is False

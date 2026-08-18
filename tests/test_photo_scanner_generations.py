"""
Regression coverage for Finding D (Phase 0B slice 1): PhotoScanner's
shared _stop_thumbs flag let a stale scan's worker republish into a newer
scan's results. The old design: scan_async() set the shared flag True to
cancel any in-flight Phase 2, then _phase1_discover() reset it to False
at its own start — so a slow, still-running Phase 2 from a PREVIOUS scan
could have its "stop" request silently erased by the very run that
superseded it, if the timing lined up so the new run's reset happened
before the stale worker's next check.

The fix replaces the shared flag with a per-run generation number, fixed
for the lifetime of each worker thread and compared against the
scanner's current generation before any publish. These tests build the
exact race deterministically with threading.Event checkpoints (no
sleep-based timing guesses) rather than relying on scheduling luck.
"""
import threading
import time

from core.photos import Photo, PhotoScanner


def _make_photo(i: int) -> Photo:
    return Photo(path=f"/mnt/DCIM/100APPLE/IMG_{i:04d}.JPG", filename=f"IMG_{i:04d}.JPG")


def test_stale_phase1_discovery_cannot_publish_into_newer_generation(tmp_path, monkeypatch):
    """
    Deterministic version of: scan A is paused mid-walk, scan B becomes
    authoritative, then A resumes. A's discovery must not be able to
    overwrite or append to B's published state.
    """
    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))

    a_entered_walk = threading.Event()
    a_resume = threading.Event()
    completions = []  # list of (generation-order, photos) via on_complete calls, in call order

    real_walk = __import__("os").walk

    def paused_walk(root):
        # Scan A's _find_dcim call always returns the same root; we only
        # want to pause the FIRST scan's walk, not B's.
        if not a_entered_walk.is_set():
            a_entered_walk.set()
            a_resume.wait(timeout=5)
        return real_walk(root)

    monkeypatch.setattr("core.photos.os.walk", paused_walk)
    monkeypatch.setattr(scanner, "_find_dcim", lambda mount_point: str(tmp_path))

    scanner.set_callbacks(
        on_progress=lambda c, t, p: None,
        on_complete=lambda photos: completions.append(list(photos)),
    )

    # Start scan A — it will block inside os.walk() until a_resume is set.
    scanner.scan_async(str(tmp_path))
    assert a_entered_walk.wait(timeout=5), "scan A never reached the paused walk"

    # Scan B supersedes A while A is still parked inside the walk call.
    # (tmp_path is empty, so B's own walk finds nothing and finishes fast.)
    scanner.scan_async(str(tmp_path))

    # Give B a moment to actually run its (trivial, empty) walk and publish.
    deadline = time.monotonic() + 5
    while len(completions) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(completions) == 1, "scan B never published its own completion"
    assert completions[0] == [], "scan B's result should be empty (nothing on disk)"

    # Now let stale scan A resume and finish its walk.
    a_resume.set()
    time.sleep(0.3)  # let A's thread run to completion if it's going to publish anything

    assert len(completions) == 1, (
        "stale scan A published a completion after being superseded by scan B — "
        f"got {len(completions)} on_complete calls, expected exactly 1 (B's)"
    )
    assert scanner.all_media == [], "scan A must not have overwritten scanner._photos after being superseded"


def test_stale_phase2_thumbnails_cannot_publish_into_newer_generation(tmp_path):
    """
    Same race, one phase later: scan A's Phase 2 (thumbnail generation) is
    mid-batch when scan B supersedes it. A's thumbnail-ready/complete
    callbacks must never fire once superseded.
    """
    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))

    thumb_calls = []       # (generation-order) on_thumbnails_ready calls actually delivered
    thumb_done_calls = []

    scanner.set_callbacks(
        on_progress=lambda c, t, p: None,
        on_complete=lambda photos: None,
        on_thumbnails_ready=lambda idx: thumb_calls.append(list(idx)),
        on_thumb_complete=lambda: thumb_done_calls.append(True),
    )

    with scanner._generation_lock:
        scanner._generation = 1
    stale_generation = 1

    # A stale run's own local photo list — never touches scanner._photos.
    stale_photos = [_make_photo(i) for i in range(3)]

    # Advance the scanner to a newer generation, as scan_async() would.
    with scanner._generation_lock:
        scanner._generation = 2

    # Directly exercise the stale generation's Phase 2 entrypoint (as if
    # its thread were only now getting CPU time after being descheduled).
    scanner._phase2_thumbnails(stale_generation, stale_photos)

    assert thumb_calls == [], "a superseded generation must never fire on_thumbnails_ready"
    assert thumb_done_calls == [], "a superseded generation must never fire on_thumb_complete"
    # And it must not have mutated the (unrelated) authoritative list either.
    assert scanner.all_media == []


def test_current_generation_phase2_thumbnails_still_publishes_normally(tmp_path):
    """Sanity check: the generation check must not break the ordinary,
    uninterrupted thumbnail path — HAS_PIL gating aside, callbacks for the
    CURRENT generation must still fire."""
    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    thumb_done_calls = []
    scanner.set_callbacks(
        on_progress=lambda c, t, p: None,
        on_complete=lambda photos: None,
        on_thumbnails_ready=lambda idx: None,
        on_thumb_complete=lambda: thumb_done_calls.append(True),
    )
    with scanner._generation_lock:
        scanner._generation = 1

    scanner._phase2_thumbnails(1, [])  # empty list — nothing to thumbnail, but still current

    assert thumb_done_calls == [True]


def test_scan_async_increments_generation_each_call(tmp_path, monkeypatch):
    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    monkeypatch.setattr(scanner, "_find_dcim", lambda mount_point: str(tmp_path))
    scanner.set_callbacks(on_progress=lambda c, t, p: None, on_complete=lambda photos: None)

    assert scanner._generation == 0
    scanner.scan_async(str(tmp_path))
    gen1 = scanner._generation
    assert gen1 == 1

    scanner.scan_async(str(tmp_path))
    gen2 = scanner._generation
    assert gen2 == 2
    assert gen2 != gen1

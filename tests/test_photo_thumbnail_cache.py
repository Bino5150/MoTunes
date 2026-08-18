"""
Regression coverage for Phase 0C.1 slice 1: PhotoScanner's thumbnail cache
filename used Python's built-in hash(photo.path) as its identity. hash()
on strings is salted per-process by PYTHONHASHSEED, so the exact same
source photo produced a DIFFERENT cache filename every time the app
restarted — every thumbnail was regenerated from scratch on every launch,
and old cache files accumulated forever under distinct, orphaned names.

A first pass fixed the hash-seed problem with a SHA-256 digest of
path + size + mtime, but that still keyed on photo.path directly. In
production, photo.path is rooted at DeviceManager.mount_media()'s fresh
tempfile.mkdtemp(prefix="motunes_media_") directory, created new on every
mount — so the SAME on-device photo gets a different absolute path on
every remount, and the SHA-256-of-full-path identity still missed its own
cache on every session even though it was internally consistent within
one process. Fixed by establishing a device_relative_path on each Photo
at discovery time (PhotoScanner._make_stub, relative to that call's own
mount_point argument — never a value stored on self, so a stale worker
from a superseded scan still carries its own run's identity) and keying
the cache on that instead of the volatile absolute path.

A third pass closed the remaining gap: device_relative_path alone is
relative to the MOUNT, not the DEVICE, so two different physical iPhones
with the same internal DCIM layout (e.g. both have
DCIM/100APPLE/IMG_0001.JPG — an entirely plausible collision, since Apple
numbers photos per-device) would still share one cache entry. Fixed by
threading a stable device_id (the device's UDID, established at
discovery time exactly like device_relative_path — never stored on
self on PhotoScanner) through scan_async -> _phase1_discover ->
_make_stub -> Photo.device_id, and namespacing the cache identity with
it in _generate_thumbnail.

All cache I/O below happens against pytest's tmp_path fixture — never a
real /tmp cache or any device path.
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime

from PIL import Image

from core.photos import Photo, PhotoScanner, thumbnail_cache_name


def _make_source_image(path: str, size=(40, 40), color=(200, 50, 50)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


def _photo(path: str, size_bytes=1234, mtime=None) -> Photo:
    return Photo(
        path=path,
        filename=os.path.basename(path),
        file_size_bytes=size_bytes,
        date_taken=mtime or datetime(2024, 1, 1, 12, 0, 0),
    )


def _expected_cache_name(photo: Photo) -> str:
    """Mirrors PhotoScanner._generate_thumbnail's identity composition
    exactly, so tests assert against the real contract rather than a
    second, drifting copy of it."""
    if photo.device_relative_path is not None:
        identity_path = f"{photo.device_id}:{photo.device_relative_path}"
    else:
        identity_path = photo.path
    return thumbnail_cache_name(identity_path, photo.file_size_bytes, photo.date_taken)


# ── Stable identity across independent processes / hash seeds ───────────────

def test_stable_identity_survives_different_pythonhashseed():
    """
    thumbnail_cache_name's own digest must be stable regardless of
    PYTHONHASHSEED. This spawns two real subprocesses with different,
    explicit seeds — a single-process test (even one that reseeds
    sys.hash_info) cannot exercise this, since PYTHONHASHSEED is fixed at
    interpreter startup. This fails under a hash()-based implementation,
    whose output changes every time the seed changes.

    Note: this proves hash-seed stability of the digest function itself,
    not cross-remount cache reuse — see
    test_same_device_relative_item_across_different_mount_roots_hits_same_cache_entry
    below for the product-level requirement.
    """
    script = (
        "from core.photos import thumbnail_cache_name\n"
        "from datetime import datetime\n"
        "print(thumbnail_cache_name('DCIM/100APPLE/IMG_0001.JPG', 1234, "
        "datetime(2024, 1, 1, 12, 0, 0)))\n"
    )
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run_with_seed(seed: str) -> str:
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root, env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    name_seed_1 = run_with_seed("1")
    name_seed_2 = run_with_seed("2")
    name_seed_random = run_with_seed("random")

    assert name_seed_1 == name_seed_2 == name_seed_random
    assert name_seed_1.endswith(".jpg")


def test_stable_identity_is_consistent_within_a_process_too():
    """Sanity check: calling twice in the same process is also stable
    (necessary but not sufficient — the cross-process test above is the
    one that actually catches a hash()-based regression)."""
    photo = _photo("/mnt/DCIM/100APPLE/IMG_0001.JPG")
    name_a = thumbnail_cache_name(photo.path, photo.file_size_bytes, photo.date_taken)
    name_b = thumbnail_cache_name(photo.path, photo.file_size_bytes, photo.date_taken)
    assert name_a == name_b


# ── Distinct identity ─────────────────────────────────────────────────────

def test_different_identity_paths_produce_distinct_cache_names():
    a = thumbnail_cache_name("DCIM/100APPLE/IMG_0001.JPG", 1234, datetime(2024, 1, 1))
    b = thumbnail_cache_name("DCIM/100APPLE/IMG_0002.JPG", 1234, datetime(2024, 1, 1))
    assert a != b


def test_cache_name_is_filesystem_safe():
    name = thumbnail_cache_name("DCIM/100APPLE/IMG_0001.JPG", 1234, datetime(2024, 1, 1))
    assert os.sep not in name
    assert all(c.isalnum() or c in ".-_" for c in name)


# ── Invalidation on source metadata change ──────────────────────────────────

def test_size_change_invalidates_cache_identity():
    same_identity = "DCIM/100APPLE/IMG_0001.JPG"
    mtime = datetime(2024, 1, 1)
    original = thumbnail_cache_name(same_identity, 1000, mtime)
    edited = thumbnail_cache_name(same_identity, 2000, mtime)
    assert original != edited


def test_mtime_change_invalidates_cache_identity():
    same_identity = "DCIM/100APPLE/IMG_0001.JPG"
    original = thumbnail_cache_name(same_identity, 1000, datetime(2024, 1, 1, 12, 0, 0))
    edited = thumbnail_cache_name(same_identity, 1000, datetime(2024, 6, 1, 9, 30, 0))
    assert original != edited


# ── device_relative_path: established at discovery, independent of mount root ──

def test_make_stub_strips_the_volatile_mount_root(tmp_path):
    """
    _make_stub must compute device_relative_path relative to the
    mount_point it's given, not embed the mount root in it — mount_point
    stands in for a fresh tempfile.mkdtemp(prefix="motunes_media_")
    directory in production.
    """
    mount_point = str(tmp_path / "motunes_media_abc123")
    fpath = os.path.join(mount_point, "DCIM", "100APPLE", "IMG_0001.JPG")
    _make_source_image(fpath)

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo = scanner._make_stub(fpath, mount_point)

    assert photo is not None
    assert photo.device_relative_path == os.path.join("DCIM", "100APPLE", "IMG_0001.JPG")
    assert "motunes_media_abc123" not in photo.device_relative_path


def test_same_device_relative_item_across_different_mount_roots_hits_same_cache_entry(tmp_path):
    """
    The core product-level requirement: the SAME on-device photo,
    encountered on two separate mount sessions (each with its own fresh
    tempfile.mkdtemp(prefix="motunes_media_") root, simulated here as two
    different temp directories), must produce the SAME cache filename —
    proving the fix reuses the cache across a real remount, not just
    across PYTHONHASHSEED values within one absolute path.

    This is failure-shaped: keying on photo.path (even via a stable
    SHA-256 digest) makes this fail, since the two mount roots differ.
    """
    relative = os.path.join("DCIM", "100APPLE", "IMG_0001.JPG")
    mount_session_1 = str(tmp_path / "motunes_media_session1")
    mount_session_2 = str(tmp_path / "motunes_media_session2")
    fpath_1 = os.path.join(mount_session_1, relative)
    fpath_2 = os.path.join(mount_session_2, relative)

    _make_source_image(fpath_1)
    # Same on-device file, so same bytes and same mtime on "remount" —
    # copy2 preserves mtime rather than re-encoding, which could jitter it.
    os.makedirs(os.path.dirname(fpath_2), exist_ok=True)
    shutil.copy2(fpath_1, fpath_2)

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo_session_1 = scanner._make_stub(fpath_1, mount_session_1)
    photo_session_2 = scanner._make_stub(fpath_2, mount_session_2)

    assert photo_session_1.device_relative_path == photo_session_2.device_relative_path

    name_1 = thumbnail_cache_name(
        photo_session_1.device_relative_path, photo_session_1.file_size_bytes, photo_session_1.date_taken
    )
    name_2 = thumbnail_cache_name(
        photo_session_2.device_relative_path, photo_session_2.file_size_bytes, photo_session_2.date_taken
    )
    assert name_1 == name_2, "same device photo produced different cache identities across mount roots"


def test_different_device_relative_path_under_different_mount_root_is_distinct(tmp_path):
    """Companion to the test above: two DIFFERENT on-device photos, each
    under their own mount session, must NOT collide just because both
    mount roots are unique temp dirs."""
    mount_session_1 = str(tmp_path / "motunes_media_session1")
    mount_session_2 = str(tmp_path / "motunes_media_session2")
    fpath_1 = os.path.join(mount_session_1, "DCIM", "100APPLE", "IMG_0001.JPG")
    fpath_2 = os.path.join(mount_session_2, "DCIM", "100APPLE", "IMG_0002.JPG")

    _make_source_image(fpath_1)
    _make_source_image(fpath_2)

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo_1 = scanner._make_stub(fpath_1, mount_session_1)
    photo_2 = scanner._make_stub(fpath_2, mount_session_2)

    assert photo_1.device_relative_path != photo_2.device_relative_path

    name_1 = thumbnail_cache_name(photo_1.device_relative_path, photo_1.file_size_bytes, photo_1.date_taken)
    name_2 = thumbnail_cache_name(photo_2.device_relative_path, photo_2.file_size_bytes, photo_2.date_taken)
    assert name_1 != name_2


# ── device_id: cross-device namespacing ─────────────────────────────────────

def test_generate_thumbnail_for_different_devices_with_colliding_relative_path_gets_distinct_cache_entries(tmp_path):
    """
    The cross-device case: two different physical iPhones can easily share
    the same internal DCIM layout — both commonly have
    DCIM/100APPLE/IMG_0001.JPG. Without a device namespace, identical
    relative path + identical size/mtime (e.g. both are freshly-taken
    photos of the same dimensions) collapses to the same cache identity
    and device B's thumbnail would render as a stale copy of device A's.

    device_id (device A's vs. device B's UDID) must keep them apart even
    though device_relative_path, size, and mtime are all equal. Each
    device also gets its own mount session (a real remount always creates
    a fresh tempfile.mkdtemp dir), driving home that device identity —
    not the mount root — is what's doing the separating work here.

    Failure-shaped: this fails if _generate_thumbnail stops including
    device_id in the identity it hashes.
    """
    relative = os.path.join("DCIM", "100APPLE", "IMG_0001.JPG")
    mount_device_a = str(tmp_path / "motunes_media_device_a_session")
    mount_device_b = str(tmp_path / "motunes_media_device_b_session")
    fpath_a = os.path.join(mount_device_a, relative)
    fpath_b = os.path.join(mount_device_b, relative)

    _make_source_image(fpath_a)
    os.makedirs(os.path.dirname(fpath_b), exist_ok=True)
    shutil.copy2(fpath_a, fpath_b)  # identical bytes AND identical mtime

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo_a = scanner._make_stub(fpath_a, mount_device_a, device_id="00008030-DEVICE-A-UDID")
    photo_b = scanner._make_stub(fpath_b, mount_device_b, device_id="00008030-DEVICE-B-UDID")

    # The part of identity that collides, confirmed before device_id
    # enters the picture:
    assert photo_a.device_relative_path == photo_b.device_relative_path
    assert photo_a.file_size_bytes == photo_b.file_size_bytes
    assert photo_a.date_taken == photo_b.date_taken

    scanner._generate_thumbnail(photo_a)
    scanner._generate_thumbnail(photo_b)

    assert photo_a.thumbnail_path != photo_b.thumbnail_path, (
        "two different devices' colliding on-device paths produced the same cache entry"
    )
    assert os.path.exists(photo_a.thumbnail_path)
    assert os.path.exists(photo_b.thumbnail_path)


def test_generate_thumbnail_reuses_cache_for_same_device_across_remount_with_device_id_set(tmp_path):
    """
    Companion regression: adding device_id namespacing must not break the
    remount-reuse fix from the previous pass. Same device (same
    non-empty, realistic-looking UDID) encountered across two separate
    simulated mount sessions must still land on the same cache entry.
    """
    relative = os.path.join("DCIM", "100APPLE", "IMG_0002.JPG")
    udid = "00008030-001A2D9A1401882E"
    mount_session_1 = str(tmp_path / "motunes_media_remount_session1")
    mount_session_2 = str(tmp_path / "motunes_media_remount_session2")
    fpath_1 = os.path.join(mount_session_1, relative)
    fpath_2 = os.path.join(mount_session_2, relative)

    _make_source_image(fpath_1)
    os.makedirs(os.path.dirname(fpath_2), exist_ok=True)
    shutil.copy2(fpath_1, fpath_2)

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo_session_1 = scanner._make_stub(fpath_1, mount_session_1, device_id=udid)
    scanner._generate_thumbnail(photo_session_1)
    cached_path = photo_session_1.thumbnail_path
    assert os.path.exists(cached_path)

    with open(cached_path, "wb") as f:
        f.write(b"MARKER-DO-NOT-REGENERATE")

    photo_session_2 = scanner._make_stub(fpath_2, mount_session_2, device_id=udid)
    photo_session_2.width, photo_session_2.height = 40, 40
    scanner._generate_thumbnail(photo_session_2)

    assert photo_session_2.thumbnail_path == cached_path
    with open(cached_path, "rb") as f:
        assert f.read() == b"MARKER-DO-NOT-REGENERATE", (
            "same device across a remount was not reused once device_id namespacing was added"
        )


def test_generate_thumbnail_reuses_cache_across_a_simulated_remount(tmp_path):
    """
    End-to-end version of the cross-mount-root test: generate a thumbnail
    for a photo discovered under mount session 1, then simulate a
    remount (fresh temp mount dir, same on-device file) and run
    _generate_thumbnail again for the session-2 stub. It must reuse the
    existing cache file rather than regenerating — proven by pre-marking
    the cached file with a stub byte string that only survives if no
    regeneration happens on the second call.
    """
    relative = os.path.join("DCIM", "100APPLE", "IMG_0001.JPG")
    mount_session_1 = str(tmp_path / "motunes_media_session1")
    mount_session_2 = str(tmp_path / "motunes_media_session2")
    fpath_1 = os.path.join(mount_session_1, relative)
    fpath_2 = os.path.join(mount_session_2, relative)
    _make_source_image(fpath_1)
    os.makedirs(os.path.dirname(fpath_2), exist_ok=True)
    shutil.copy2(fpath_1, fpath_2)

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo_session_1 = scanner._make_stub(fpath_1, mount_session_1)
    scanner._generate_thumbnail(photo_session_1)
    cached_path = photo_session_1.thumbnail_path
    assert os.path.exists(cached_path)

    # Overwrite with a marker — a regeneration on the "remount" pass would
    # replace this with a freshly-rendered JPEG and the assertion below
    # would fail.
    with open(cached_path, "wb") as f:
        f.write(b"MARKER-DO-NOT-REGENERATE")

    photo_session_2 = scanner._make_stub(fpath_2, mount_session_2)
    photo_session_2.width, photo_session_2.height = 40, 40  # skip the "fetch dims" branch too
    scanner._generate_thumbnail(photo_session_2)

    assert photo_session_2.thumbnail_path == cached_path
    with open(cached_path, "rb") as f:
        assert f.read() == b"MARKER-DO-NOT-REGENERATE", (
            "thumbnail was regenerated on a simulated remount instead of reusing the cache"
        )


# ── End-to-end: PhotoScanner._generate_thumbnail cache reuse/creation ──────

def test_generate_thumbnail_reuses_existing_cache_file_without_regenerating(tmp_path):
    """
    A valid cached thumbnail for the current source identity must be
    reused, not regenerated. We prove "not regenerated" by pre-seeding
    the cache file with content PIL did not write (a 1-byte stub) and by
    pre-populating photo.width/height so the reuse path takes zero PIL
    calls — if the code regenerated, save() would overwrite the stub with
    a real JPEG and the size assertion below would fail.
    """
    mount_point = str(tmp_path / "motunes_media_x")
    fpath = os.path.join(mount_point, "DCIM", "100APPLE", "IMG_0001.JPG")
    _make_source_image(fpath)

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo = scanner._make_stub(fpath, mount_point)
    photo.width, photo.height = 40, 40  # already known — skip the "fetch dims" branch too

    expected_name = _expected_cache_name(photo)
    cached_path = tmp_path / "thumbs" / expected_name
    os.makedirs(cached_path.parent, exist_ok=True)
    cached_path.write_bytes(b"X")  # stub — a real regeneration would replace this

    scanner._generate_thumbnail(photo)

    assert photo.thumbnail_path == str(cached_path)
    assert cached_path.read_bytes() == b"X", "cached thumbnail was regenerated instead of reused"


def test_generate_thumbnail_creates_cache_file_on_first_run(tmp_path):
    mount_point = str(tmp_path / "motunes_media_x")
    fpath = os.path.join(mount_point, "DCIM", "100APPLE", "IMG_0002.JPG")
    _make_source_image(fpath)

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo = scanner._make_stub(fpath, mount_point)

    scanner._generate_thumbnail(photo)

    expected_name = _expected_cache_name(photo)
    expected_path = os.path.join(str(tmp_path / "thumbs"), expected_name)
    assert photo.thumbnail_path == expected_path
    assert os.path.exists(expected_path)
    assert photo.width == 40 and photo.height == 40


def test_generate_thumbnail_for_edited_source_gets_a_fresh_cache_entry(tmp_path):
    """
    Same device-relative path, different content (simulated by a later
    mtime/size) must land in a different cache file rather than silently
    reusing the stale thumbnail left behind by the original content.
    """
    mount_point = str(tmp_path / "motunes_media_x")
    fpath = os.path.join(mount_point, "DCIM", "100APPLE", "IMG_0003.JPG")
    _make_source_image(fpath, color=(10, 10, 10))

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo_v1 = scanner._make_stub(fpath, mount_point)
    scanner._generate_thumbnail(photo_v1)
    v1_path = photo_v1.thumbnail_path
    assert os.path.exists(v1_path)

    # Simulate the source file being replaced in place with new content.
    _make_source_image(fpath, size=(80, 80), color=(250, 250, 250))
    photo_v2 = scanner._make_stub(fpath, mount_point)
    scanner._generate_thumbnail(photo_v2)
    v2_path = photo_v2.thumbnail_path

    assert v1_path != v2_path, "edited source reused the old thumbnail's cache identity"
    assert os.path.exists(v1_path), "old cache entry should still exist untouched"
    assert os.path.exists(v2_path)


# ── Fallback for Photo objects built outside discovery ─────────────────────

def test_generate_thumbnail_falls_back_to_path_when_device_relative_path_is_absent(tmp_path):
    """Hand-built Photo objects (e.g. other unit tests) have no
    device_relative_path. _generate_thumbnail must still work, falling
    back to photo.path so this remains a purely additive change."""
    src = tmp_path / "IMG_0004.JPG"
    _make_source_image(str(src))
    stat = os.stat(src)

    scanner = PhotoScanner(thumb_dir=str(tmp_path / "thumbs"))
    photo = _photo(str(src), size_bytes=stat.st_size, mtime=datetime.fromtimestamp(stat.st_mtime))
    assert photo.device_relative_path is None

    scanner._generate_thumbnail(photo)

    assert photo.thumbnail_path is not None
    assert os.path.exists(photo.thumbnail_path)

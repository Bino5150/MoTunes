"""
MoTunes - Photo Scanner
Phase 1: Fast file discovery (stat only, no PIL) — fires on_complete immediately
Phase 2: Background thumbnail generation — fires on_thumbnails_ready in batches
"""

import hashlib
import os
import threading
from dataclasses import dataclass
from typing import List, Optional, Callable
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".png", ".gif", ".bmp", ".tiff", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

# Apple sidecar / metadata files — skip entirely
SKIP_EXTENSIONS = {".aae", ".thm"}

# Thumbnail batch size before firing a UI refresh signal
THUMB_BATCH_SIZE = 20


@dataclass
class Photo:
    path: str
    filename: str
    file_size_bytes: int = 0
    width: int = 0
    height: int = 0
    is_video: bool = False
    is_live_photo: bool = False    # True = Live Photo .MOV paired with a still
    date_taken: Optional[datetime] = None
    thumbnail_path: Optional[str] = None
    thumb_loaded: bool = False     # True once thumbnail has been generated
    device_relative_path: Optional[str] = None  # path relative to the mount root
    # at discovery time — e.g. "DCIM/100APPLE/IMG_0001.JPG". `path` itself
    # is rooted at a fresh tempfile.mkdtemp(prefix="motunes_media_")
    # directory that DeviceManager.mount_media() creates on every remount,
    # so `path` alone changes across sessions even for the same on-device
    # file. This field is the part of identity that stays constant.
    device_id: str = ""  # stable per-device identifier (e.g. the iPhone's
    # UDID), established at discovery time. Namespaces the cache identity
    # alongside device_relative_path so two different physical devices
    # whose internal DCIM layout happens to collide (e.g. both have
    # DCIM/100APPLE/IMG_0001.JPG) don't share a thumbnail cache entry.
    # Defaults to "" when unknown — a single shared namespace, same as
    # before this field existed.

    @property
    def size_str(self) -> str:
        mb = self.file_size_bytes / (1024 * 1024)
        if mb < 1:
            return f"{self.file_size_bytes // 1024} KB"
        return f"{mb:.1f} MB"

    @property
    def dimensions_str(self) -> str:
        if self.width and self.height:
            return f"{self.width} × {self.height}"
        return ""

    @property
    def date_str(self) -> str:
        if self.date_taken:
            return self.date_taken.strftime("%b %d, %Y")
        return ""

    @property
    def ext(self) -> str:
        return Path(self.filename).suffix.upper().lstrip(".")


def find_live_photo_companion(still: Photo, all_media: List[Photo]) -> Optional[Photo]:
    """
    Return the paired Live Photo .MOV component for `still`, or None if
    `still` isn't a photo with a companion in `all_media`.

    Mirrors PhotoScanner's own pairing rule exactly (same directory, same
    filename stem, case-insensitive) — the .MOV component itself is
    flagged is_live_photo=True and deliberately excluded from the visible
    video grid, so it's only ever reachable through this lookup, not
    through direct user selection.
    """
    if still.is_video:
        return None
    still_dir = os.path.dirname(still.path)
    still_stem = Path(still.filename).stem.lower()
    for media in all_media:
        if (media.is_video and media.is_live_photo
                and os.path.dirname(media.path) == still_dir
                and Path(media.filename).stem.lower() == still_stem):
            return media
    return None


def thumbnail_cache_name(identity_path: str, size_bytes: int, mtime: Optional[datetime]) -> str:
    """
    Deterministic, filesystem-safe cache filename for a photo's thumbnail.

    `identity_path` must be a stable identity, not a raw filesystem path —
    callers are responsible for passing something that stays constant for
    the "same" source media across sessions (see Photo.device_relative_path).
    This helper only turns that identity, plus size + mtime for
    invalidation, into a deterministic digest via hashlib.sha256 — never
    the built-in hash(), which is randomized per-process by PYTHONHASHSEED
    and previously made every thumbnail's cache identity change across app
    restarts.
    """
    mtime_key = mtime.isoformat() if mtime else ""
    identity = f"{identity_path}|{size_bytes}|{mtime_key}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{digest}.jpg"


class PhotoScanner:
    def __init__(self, thumb_dir: str = "/tmp/motunes_thumbs"):
        self._photos: List[Photo] = []
        self._thumb_dir = thumb_dir
        # Per-run identity, not a shared stop flag. The old design used one
        # shared _stop_thumbs bool that _phase1_discover reset to False at
        # its own start — a scan superseding an in-flight one could have
        # its "stop" request silently erased by the very run it was meant
        # to stop, since both scans shared the same flag. Every worker
        # thread instead carries the generation number it was spawned
        # with, fixed for its whole lifetime; scan_async() bumps the
        # counter, and workers compare their own number against the
        # current one before ever publishing anything. A generation that's
        # been superseded can never win that comparison again, no matter
        # how its timing lines up with the new scan starting.
        self._generation = 0
        self._generation_lock = threading.Lock()

        # Phase 1 callbacks
        self._on_progress: Optional[Callable] = None       # (current, total, photo)
        self._on_complete: Optional[Callable] = None       # (photos) — stubs, fires immediately

        # Phase 2 callbacks
        self._on_thumbnails_ready: Optional[Callable] = None  # (indices: List[int])
        self._on_thumb_complete: Optional[Callable] = None    # ()

        os.makedirs(thumb_dir, exist_ok=True)

    def set_callbacks(
        self,
        on_progress: Callable,
        on_complete: Callable,
        on_thumbnails_ready: Optional[Callable] = None,
        on_thumb_complete: Optional[Callable] = None,
    ):
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_thumbnails_ready = on_thumbnails_ready
        self._on_thumb_complete = on_thumb_complete

    def _is_current(self, generation: int) -> bool:
        with self._generation_lock:
            return generation == self._generation

    def scan_async(self, mount_point: str, device_id: str = ""):
        """Start Phase 1 (discovery) in a background thread.

        `device_id` should be a stable per-device identifier (e.g. the
        connected iPhone's UDID) when the caller has one — see
        Photo.device_id. Optional and defaults to "" for callers (and
        existing tests) with no device identity to hand — falls back to a
        single shared cache namespace, same as before this parameter
        existed.
        """
        with self._generation_lock:
            self._generation += 1
            generation = self._generation
        self._photos = []
        thread = threading.Thread(
            target=self._phase1_discover, args=(mount_point, generation, device_id), daemon=True
        )
        thread.start()

    # ── Phase 1: Discovery ────────────────────────────────────────────────────

    def _phase1_discover(self, mount_point: str, generation: int, device_id: str = ""):
        """
        Stat-only scan: build stubs and fire progress IN the walk loop,
        one directory at a time. The UI gets photos as each DCIM/###APPLE
        folder is read — no waiting for the full walk to finish.

        Builds into a run-local list (`run_photos`), never the shared
        self._photos, until this generation is confirmed to still be
        current — so a superseded run can never leave a partially-built
        list sitting in self._photos for anyone else to read.
        """
        search_root = self._find_dcim(mount_point)
        run_photos: List[Photo] = []

        # Fire an early on_complete once we have enough to fill the screen
        EARLY_FIRE_THRESHOLD = 50
        _fired_initial = False

        try:
            for dirpath, dirnames, filenames in os.walk(search_root):
                if not self._is_current(generation):
                    return
                # Skip hidden dirs to avoid AFC hangs
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

                # Build set of photo stems in this directory so we can
                # identify Live Photo .MOV components (same stem, same dir)
                photo_stems = {
                    Path(f).stem.lower()
                    for f in filenames
                    if Path(f).suffix.lower() in PHOTO_EXTENSIONS
                }

                # Build stubs for every media file in this directory immediately
                for fname in filenames:
                    if not self._is_current(generation):
                        return
                    ext = Path(fname).suffix.lower()
                    if ext in SKIP_EXTENSIONS:
                        continue
                    if ext not in PHOTO_EXTENSIONS and ext not in VIDEO_EXTENSIONS:
                        continue
                    fpath = os.path.join(dirpath, fname)

                    # Flag .MOV as Live Photo if a photo with same stem exists here
                    is_live = (
                        ext == ".mov"
                        and Path(fname).stem.lower() in photo_stems
                    )

                    photo = self._make_stub(fpath, mount_point, device_id, is_live_photo=is_live)
                    if photo:
                        run_photos.append(photo)
                        if self._on_progress:
                            self._on_progress(
                                len(run_photos), len(run_photos), photo
                            )

                # After each directory, fire on_complete early once we have
                # enough photos to show something useful
                if (not _fired_initial
                        and len(run_photos) >= EARLY_FIRE_THRESHOLD
                        and self._is_current(generation)):
                    self._photos = list(run_photos)
                    if self._on_complete:
                        self._on_complete(list(run_photos))
                    _fired_initial = True

        except Exception as e:
            print(f"[PhotoScanner] Walk error: {e}")

        if not self._is_current(generation):
            return

        # Final on_complete with full list (always fires)
        self._photos = list(run_photos)
        if self._on_complete:
            self._on_complete(list(run_photos))

        # Kick off Phase 2 thumbnail generation, against this run's own
        # list — never self._photos, which a newer generation is free to
        # reassign at any moment.
        if run_photos and HAS_PIL:
            thumb_thread = threading.Thread(
                target=self._phase2_thumbnails, args=(generation, run_photos), daemon=True
            )
            thumb_thread.start()

    def _find_dcim(self, mount_point: str) -> str:
        """Return the best DCIM root, never falling back to bare mount root."""
        candidates = [
            os.path.join(mount_point, "DCIM"),
            os.path.join(mount_point, "Media", "DCIM"),
        ]
        for c in candidates:
            if os.path.isdir(c):
                return c

        # Safe fallback: Media/ subdir only
        media = os.path.join(mount_point, "Media")
        if os.path.isdir(media):
            print(f"[PhotoScanner] No DCIM found, falling back to Media/")
            return media

        print(f"[PhotoScanner] WARNING: No DCIM directory found at {mount_point}")
        return mount_point

    def _make_stub(
        self, fpath: str, mount_point: str, device_id: str = "", is_live_photo: bool = False
    ) -> Optional[Photo]:
        """Create a Photo with just stat info — no PIL, no file reading.

        `mount_point` and `device_id` are this run's own arguments (never
        read from self._something), so the identity they produce is fixed
        to the run that discovered the photo — safe even if a newer scan
        reassigns the scanner's state around it later.
        """
        try:
            stat = os.stat(fpath)
            fname = os.path.basename(fpath)
            ext = Path(fname).suffix.lower()
            return Photo(
                path=fpath,
                filename=fname,
                file_size_bytes=stat.st_size,
                is_video=(ext in VIDEO_EXTENSIONS),
                is_live_photo=is_live_photo,
                date_taken=datetime.fromtimestamp(stat.st_mtime),
                thumb_loaded=False,
                device_relative_path=os.path.relpath(fpath, mount_point),
                device_id=device_id,
            )
        except Exception as e:
            print(f"[PhotoScanner] Stub error {fpath}: {e}")
            return None

    # ── Phase 2: Thumbnail Generation ────────────────────────────────────────

    def _phase2_thumbnails(self, generation: int, photos: List[Photo]):
        """
        Generate thumbnails for non-video, non-HEIC photos in the background.
        Fires on_thumbnails_ready in batches so the grid refreshes incrementally.

        `photos` is this run's own list, passed explicitly by
        _phase1_discover rather than read from self._photos — a newer
        generation reassigning self._photos partway through can never
        change what this run iterates. Every publish point re-checks
        `generation` against the current one; once superseded, this run
        stops publishing (progress callbacks, completion) but keeps
        running to completion quietly rather than trying to tear down a
        background thread from outside it.
        """
        if not self._is_current(generation):
            return

        batch_indices = []

        for i, photo in enumerate(photos):
            if not self._is_current(generation):
                return
            if photo.is_video or photo.thumb_loaded:
                continue

            ext = Path(photo.filename).suffix.lower()
            if ext == ".heic":
                # HEIC requires pillow-heif or similar; skip for now, show placeholder
                photo.thumb_loaded = True
                continue

            self._generate_thumbnail(photo)
            photo.thumb_loaded = True
            batch_indices.append(i)

            if len(batch_indices) >= THUMB_BATCH_SIZE:
                if not self._is_current(generation):
                    return
                if self._on_thumbnails_ready:
                    self._on_thumbnails_ready(list(batch_indices))
                batch_indices = []

        if not self._is_current(generation):
            return

        # Fire remaining batch
        if batch_indices and self._on_thumbnails_ready:
            self._on_thumbnails_ready(list(batch_indices))

        if self._is_current(generation) and self._on_thumb_complete:
            self._on_thumb_complete()

    def _generate_thumbnail(self, photo: Photo):
        """Generate a 200×200 JPEG thumbnail, cached by a stable content-identity key.

        Keys on device_id + device_relative_path, not photo.path —
        photo.path is rooted at this session's own tempfile.mkdtemp(
        prefix="motunes_media_") mount directory and is different every
        time the device is remounted, even for the exact same on-device
        file. device_relative_path alone isn't enough either: two
        different physical devices can have the same internal layout
        (e.g. both have DCIM/100APPLE/IMG_0001.JPG), so device_id
        namespaces the identity per-device. Falls back to photo.path only
        for Photo objects built outside discovery (e.g. direct unit
        construction), which have no mount root to strip and no device
        identity to namespace with.
        """
        try:
            if photo.device_relative_path is not None:
                identity_path = f"{photo.device_id}:{photo.device_relative_path}"
            else:
                identity_path = photo.path
            thumb_name = thumbnail_cache_name(identity_path, photo.file_size_bytes, photo.date_taken)
            thumb_path = os.path.join(self._thumb_dir, thumb_name)

            if not os.path.exists(thumb_path):
                with Image.open(photo.path) as img:
                    photo.width, photo.height = img.size
                    img.thumbnail((200, 200), Image.LANCZOS)
                    img.convert("RGB").save(thumb_path, "JPEG", quality=72)
            else:
                # Thumbnail already cached — still update dimensions if missing
                if not photo.width:
                    with Image.open(photo.path) as img:
                        photo.width, photo.height = img.size

            photo.thumbnail_path = thumb_path
        except Exception as e:
            print(f"[PhotoScanner] Thumbnail error {photo.filename}: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def photos(self) -> List[Photo]:
        return [p for p in self._photos if not p.is_video]

    @property
    def videos(self) -> List[Photo]:
        """Real videos only — excludes Live Photo .MOV components."""
        return [p for p in self._photos if p.is_video and not p.is_live_photo]

    @property
    def live_photos(self) -> List[Photo]:
        """Live Photo .MOV components — paired with a still image."""
        return [p for p in self._photos if p.is_live_photo]

    @property
    def all_media(self) -> List[Photo]:
        return self._photos


# ── Device-file deletion ──────────────────────────────────────────────────────

@dataclass
class DeleteUnit:
    """
    One user-visible asset to delete — a standalone photo/video, or a Live
    Photo still paired with its motion component. UI selection counts are
    in terms of these units; a single unit with a companion still deletes
    two files underneath.
    """
    still: Photo
    companion: Optional[Photo] = None   # paired Live Photo .MOV, if any


@dataclass
class DeleteResult:
    """
    Truthful outcome of one DeleteUnit. still_deleted/companion_deleted
    are independent facts, not a single pass/fail bit — a companion that
    was removed while the still failed (or vice versa) is a real,
    reportable partial outcome, not something to paper over.
    """
    still: Photo
    companion: Optional[Photo]
    still_deleted: bool = False
    companion_deleted: bool = False
    error: str = ""

    @property
    def fully_deleted(self) -> bool:
        return self.still_deleted and (self.companion is None or self.companion_deleted)


class PhotoDeleteWorker:
    """
    Background-thread deletion of selected photos/videos from the device.

    Live Photo pairs are treated as one logical asset: the motion
    component is removed first, and the still is only removed if that
    succeeds — so a failed companion delete never leaves a pair
    half-gone-but-reported-clean. Filesystem deletes that already
    succeeded are never rolled back or hidden; DeleteResult reports
    exactly what happened.

    Unlike a chunked file copy, a single os.remove() can't be safely
    preempted mid-operation, so this deliberately has no cancel() — a
    caller that needs to know the batch has actually finished (e.g.
    before unmounting) uses is_running / join().
    """

    def __init__(self, can_write: Optional[Callable[[], bool]] = None):
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_result: Optional[Callable] = None        # (DeleteResult) -> None, per unit
        self._on_all_complete: Optional[Callable] = None  # () -> None
        # Consulted before spawning the worker — a caller invoking
        # start() directly must still be refused if device writes are
        # currently prohibited, not just a UI button that queued it.
        # Defaults to always-allowed so existing/other callers that
        # don't care about write policy see no behavior change.
        self._can_write: Callable[[], bool] = can_write or (lambda: True)

    def set_callbacks(self, on_result: Optional[Callable] = None,
                       on_all_complete: Optional[Callable] = None):
        self._on_result = on_result
        self._on_all_complete = on_all_complete

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, units: List[DeleteUnit]) -> bool:
        """Begin deleting `units` in a background thread. Returns False
        (no-op) if a batch is already running — never runs two concurrent
        delete workers — or if device writes are currently prohibited by
        capability policy, in which case no thread is spawned and zero
        os.remove() calls happen."""
        if not self._can_write():
            return False
        with self._lock:
            if self._running:
                return False
            self._running = True
            thread = threading.Thread(target=self._run, args=(list(units),), daemon=True)
            self._thread = thread
        thread.start()
        return True

    def join(self, timeout: Optional[float] = None) -> bool:
        """Wait for the worker to actually finish. Returns True if it has
        (or none was running), False if still alive when `timeout` elapses."""
        thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _run(self, units: List[DeleteUnit]):
        for unit in units:
            result = DeleteResult(still=unit.still, companion=unit.companion)
            if unit.companion is not None:
                try:
                    os.remove(unit.companion.path)
                    result.companion_deleted = True
                except Exception as e:
                    result.error = f"companion: {e}"
                    print(f"[PhotoDeleteWorker] Companion delete failed: {unit.companion.path} — {e}")
                    if self._on_result:
                        self._on_result(result)
                    continue  # companion delete failed — do not touch the still

            try:
                os.remove(unit.still.path)
                result.still_deleted = True
            except Exception as e:
                result.error = (result.error + "; " if result.error else "") + f"still: {e}"
                print(f"[PhotoDeleteWorker] Delete failed: {unit.still.path} — {e}")

            if self._on_result:
                self._on_result(result)

        with self._lock:
            self._running = False
        if self._on_all_complete:
            self._on_all_complete()

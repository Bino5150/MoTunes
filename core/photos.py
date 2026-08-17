"""
MoTunes - Photo Scanner
Phase 1: Fast file discovery (stat only, no PIL) — fires on_complete immediately
Phase 2: Background thumbnail generation — fires on_thumbnails_ready in batches
"""

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


class PhotoScanner:
    def __init__(self, thumb_dir: str = "/tmp/motunes_thumbs"):
        self._photos: List[Photo] = []
        self._thumb_dir = thumb_dir
        self._stop_thumbs = False

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

    def scan_async(self, mount_point: str):
        """Start Phase 1 (discovery) in a background thread."""
        self._stop_thumbs = True   # Cancel any in-flight thumbnail generation
        self._photos = []
        thread = threading.Thread(
            target=self._phase1_discover, args=(mount_point,), daemon=True
        )
        thread.start()

    # ── Phase 1: Discovery ────────────────────────────────────────────────────

    def _phase1_discover(self, mount_point: str):
        """
        Stat-only scan: build stubs and fire progress IN the walk loop,
        one directory at a time. The UI gets photos as each DCIM/###APPLE
        folder is read — no waiting for the full walk to finish.
        """
        self._stop_thumbs = False
        search_root = self._find_dcim(mount_point)

        # Fire an early on_complete once we have enough to fill the screen
        EARLY_FIRE_THRESHOLD = 50
        _fired_initial = False

        try:
            for dirpath, dirnames, filenames in os.walk(search_root):
                if self._stop_thumbs:
                    break
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
                    if self._stop_thumbs:
                        break
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

                    photo = self._make_stub(fpath, is_live_photo=is_live)
                    if photo:
                        self._photos.append(photo)
                        if self._on_progress:
                            self._on_progress(
                                len(self._photos), len(self._photos), photo
                            )

                # After each directory, fire on_complete early once we have
                # enough photos to show something useful
                if (not _fired_initial
                        and len(self._photos) >= EARLY_FIRE_THRESHOLD):
                    if self._on_complete:
                        self._on_complete(list(self._photos))
                    _fired_initial = True

        except Exception as e:
            print(f"[PhotoScanner] Walk error: {e}")

        # Final on_complete with full list (always fires)
        if self._on_complete:
            self._on_complete(list(self._photos))

        # Kick off Phase 2 thumbnail generation
        if self._photos and not self._stop_thumbs and HAS_PIL:
            thumb_thread = threading.Thread(
                target=self._phase2_thumbnails, daemon=True
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

    def _make_stub(self, fpath: str, is_live_photo: bool = False) -> Optional[Photo]:
        """Create a Photo with just stat info — no PIL, no file reading."""
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
            )
        except Exception as e:
            print(f"[PhotoScanner] Stub error {fpath}: {e}")
            return None

    # ── Phase 2: Thumbnail Generation ────────────────────────────────────────

    def _phase2_thumbnails(self):
        """
        Generate thumbnails for non-video, non-HEIC photos in the background.
        Fires on_thumbnails_ready in batches so the grid refreshes incrementally.
        """
        batch_indices = []

        for i, photo in enumerate(self._photos):
            if self._stop_thumbs:
                break
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
                if self._on_thumbnails_ready:
                    self._on_thumbnails_ready(list(batch_indices))
                batch_indices = []

        # Fire remaining batch
        if batch_indices and self._on_thumbnails_ready:
            self._on_thumbnails_ready(list(batch_indices))

        if not self._stop_thumbs and self._on_thumb_complete:
            self._on_thumb_complete()

    def _generate_thumbnail(self, photo: Photo):
        """Generate a 200×200 JPEG thumbnail, cached by path hash."""
        try:
            thumb_name = f"{abs(hash(photo.path))}.jpg"
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

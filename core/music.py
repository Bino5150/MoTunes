"""
MoTunes - Music Scanner
Phase 1: Fast file discovery (filenames + size only) — fires on_complete immediately
Phase 2: Background tag hydration — fires on_track_updated per track as tags arrive
"""

import os
import threading
from dataclasses import dataclass
from typing import List, Optional, Callable
from pathlib import Path

try:
    import eyed3
    eyed3.log.setLevel("ERROR")
    HAS_EYED3 = True
except ImportError:
    HAS_EYED3 = False

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3NoHeaderError
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".aiff"}
EARLY_FIRE_THRESHOLD = 20
HYDRATION_BATCH_SIZE = 25


@dataclass
class Track:
    path: str
    filename: str
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    genre: str = ""
    year: str = ""
    track_num: int = 0
    duration_secs: float = 0.0
    file_size_bytes: int = 0
    has_artwork: bool = False
    artwork_data: Optional[bytes] = None
    tags_loaded: bool = False

    @property
    def duration_str(self) -> str:
        if self.duration_secs <= 0:
            return "--:--"
        mins = int(self.duration_secs // 60)
        secs = int(self.duration_secs % 60)
        return f"{mins}:{secs:02d}"

    @property
    def size_str(self) -> str:
        mb = self.file_size_bytes / (1024 * 1024)
        return f"{mb:.1f} MB"

    @property
    def display_title(self) -> str:
        return self.title or Path(self.filename).stem

    @property
    def display_artist(self) -> str:
        return self.artist or ("..." if not self.tags_loaded else "Unknown Artist")

    @property
    def display_album(self) -> str:
        return self.album or ("..." if not self.tags_loaded else "Unknown Album")


class MusicScanner:
    def __init__(self):
        self._tracks: List[Track] = []
        self._scanning = False
        self._hydrating = False
        self._stop_hydration = False
        self._on_progress: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None
        self._on_track_updated: Optional[Callable] = None
        self._on_hydration_complete: Optional[Callable] = None

    def set_callbacks(
        self,
        on_progress: Callable,
        on_complete: Callable,
        on_track_updated: Optional[Callable] = None,
        on_hydration_complete: Optional[Callable] = None,
    ):
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_track_updated = on_track_updated
        self._on_hydration_complete = on_hydration_complete

    def scan_async(self, mount_point: str):
        """Start Phase 1 (discovery) in a background thread."""
        self._stop_hydration = True
        self._tracks = []
        thread = threading.Thread(
            target=self._phase1_discover, args=(mount_point,), daemon=True
        )
        thread.start()

    # ── Phase 1: Discovery ────────────────────────────────────────────────────

    def _phase1_discover(self, mount_point: str):
        """
        Find all audio files, build stub Track objects.
        Fires on_complete early once EARLY_FIRE_THRESHOLD tracks found,
        then again at the end with the full list.
        """
        self._scanning = True
        self._stop_hydration = False
        _fired_initial = False

        search_roots = self._build_search_roots(mount_point)

        for root in search_roots:
            if self._stop_hydration:
                break
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    if self._stop_hydration:
                        break
                    dirnames[:] = [
                        d for d in dirnames
                        if not d.startswith(".")
                        and d not in ("Artwork", "tmp", "Temp", "Logs", "Crash")
                    ]
                    for fname in filenames:
                        if self._stop_hydration:
                            break
                        ext = Path(fname).suffix.lower()
                        if ext not in AUDIO_EXTENSIONS:
                            continue
                        fpath = os.path.join(dirpath, fname)
                        try:
                            size = os.path.getsize(fpath)
                        except Exception:
                            size = 0
                        # Skip cloud stubs — real audio files are always > 250KB
                        if size < 250 * 1024:
                            continue

                        track = Track(
                            path=fpath,
                            filename=fname,
                            file_size_bytes=size,
                            tags_loaded=False,
                        )
                        self._tracks.append(track)
                        if self._on_progress:
                            self._on_progress(
                                len(self._tracks), len(self._tracks), track
                            )

                    # Early fire once we have enough to populate the UI
                    if not _fired_initial and len(self._tracks) >= EARLY_FIRE_THRESHOLD:
                        if self._on_complete:
                            self._on_complete(list(self._tracks))
                        _fired_initial = True

            except Exception as e:
                print(f"[MusicScanner] Walk error in {root}: {e}")

        self._scanning = False

        # Always fire final on_complete with full list
        if self._on_complete:
            self._on_complete(list(self._tracks))

        # Kick off Phase 2
        if self._tracks and not self._stop_hydration:
            hydration_thread = threading.Thread(
                target=self._phase2_hydrate, daemon=True
            )
            hydration_thread.start()

    def _build_search_roots(self, mount_point: str) -> List[str]:
        """
        Return targeted search directories in priority order.
        Never falls back to walking the entire mount root.
        """
        candidates = [
            os.path.join(mount_point, "Purchases"),
            os.path.join(mount_point, "Music"),
            os.path.join(mount_point, "iTunes_Control", "Music"),
            os.path.join(mount_point, "Media", "iTunes_Control", "Music"),
            os.path.join(mount_point, "Media", "Music"),
            os.path.join(mount_point, "Media", "Purchases"),
        ]
        found = []
        for path in candidates:
            try:
                if os.path.isdir(path):
                    if "iTunes_Control" in path:
                        try:
                            subdirs = [
                                os.path.join(path, d)
                                for d in os.listdir(path)
                                if os.path.isdir(os.path.join(path, d))
                            ]
                            found.extend(subdirs if subdirs else [path])
                        except Exception:
                            found.append(path)
                    else:
                        found.append(path)
            except Exception:
                pass

        if not found:
            for fb in [os.path.join(mount_point, "Media"),
                       os.path.join(mount_point, "Documents")]:
                if os.path.isdir(fb):
                    found.append(fb)
                    print(f"[MusicScanner] Using safe fallback: {fb}")

        if not found:
            print("[MusicScanner] WARNING: No known music directories found.")

        return found

    # ── Phase 2: Tag Hydration ────────────────────────────────────────────────

    def _phase2_hydrate(self):
        """
        Read ID3/metadata tags for each stub track in the background.
        Fires on_track_updated in batches so the UI refreshes smoothly.
        """
        self._hydrating = True
        batch_indices = []

        for i, track in enumerate(self._tracks):
            if self._stop_hydration:
                break
            if track.tags_loaded:
                continue
            self._read_tags_into(track)
            track.tags_loaded = True
            batch_indices.append(i)

            if len(batch_indices) >= HYDRATION_BATCH_SIZE:
                if self._on_track_updated:
                    self._on_track_updated(list(batch_indices))
                batch_indices = []

        if batch_indices and self._on_track_updated:
            self._on_track_updated(list(batch_indices))

        self._hydrating = False
        if not self._stop_hydration and self._on_hydration_complete:
            self._on_hydration_complete()

    def _read_tags_into(self, track: Track):
        """Read tags directly into an existing Track object. Never raises."""
        try:
            fpath = track.path
            ext = fpath.lower()

            if HAS_EYED3 and ext.endswith(".mp3"):
                af = eyed3.load(fpath)
                if af and af.tag:
                    tag = af.tag
                    track.title = tag.title or ""
                    track.artist = tag.artist or ""
                    track.album = tag.album or ""
                    track.album_artist = tag.album_artist or ""
                    track.genre = str(tag.genre) if tag.genre else ""
                    track.year = str(tag.best_release_date) if tag.best_release_date else ""
                    track.track_num = tag.track_num[0] if tag.track_num else 0
                    images = list(tag.images) if tag.images else []
                    if images:
                        track.has_artwork = True
                        track.artwork_data = images[0].image_data
                if af and af.info:
                    track.duration_secs = af.info.time_secs

            elif HAS_MUTAGEN:
                mf = MutagenFile(fpath, easy=True)
                if mf:
                    track.title = (mf.get("title", [""])[0]) or ""
                    track.artist = (mf.get("artist", [""])[0]) or ""
                    track.album = (mf.get("album", [""])[0]) or ""
                    track.album_artist = (mf.get("albumartist", [""])[0]) or ""
                    track.genre = (mf.get("genre", [""])[0]) or ""
                    track.year = (mf.get("date", [""])[0]) or ""
                    tn = mf.get("tracknumber", ["0"])[0]
                    track.track_num = int(str(tn).split("/")[0]) if tn else 0
                    if hasattr(mf, "info") and hasattr(mf.info, "length"):
                        track.duration_secs = mf.info.length

        except Exception as e:
            print(f"[MusicScanner] Tag read error {track.filename}: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def tracks(self) -> List[Track]:
        return self._tracks

    def get_artists(self) -> List[str]:
        return sorted(set(t.display_artist for t in self._tracks))

    def get_albums(self) -> List[str]:
        return sorted(set(t.display_album for t in self._tracks))

    def filter_tracks(self, query: str) -> List[Track]:
        q = query.lower()
        return [
            t for t in self._tracks
            if q in t.display_title.lower()
            or q in t.display_artist.lower()
            or q in t.display_album.lower()
        ]

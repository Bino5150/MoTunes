"""
MoTunes - Main Application Window
Commercial-grade iPhone manager for Linux
"""

import sys
import os
import subprocess
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QFileDialog, QLineEdit, QSplitter,
    QScrollArea, QGridLayout, QFrame, QSizePolicy, QStatusBar,
    QMessageBox, QAbstractItemView, QToolBar, QStyle,
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QMenu
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QObject, QTimer, QSize, QMimeData, QUrl
)
from PySide6.QtGui import (
    QPixmap, QColor, QPalette, QFont, QIcon, QDragEnterEvent,
    QDropEvent, QPainter, QLinearGradient, QBrush, QPen, QAction
)

try:
    import vlc as _vlc
    HAS_VLC = True
except ImportError:
    HAS_VLC = False

# Add parent dir to path so we can import core modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.device import DeviceManager, DeviceInfo
from core.music import MusicScanner, Track
from core.photos import PhotoScanner, Photo
from core.transfer import TransferEngine, TransferDirection, TransferStatus


# ── Color Palette ─────────────────────────────────────────────────────────────
DARK_BG       = "#0f0f13"
PANEL_BG      = "#16161e"
CARD_BG       = "#1e1e2a"
ACCENT        = "#c8a96e"       # Mo Thugs gold
ACCENT_DIM    = "#8a7048"
TEXT_PRIMARY  = "#e8e6e0"
TEXT_SECONDARY= "#8a8894"
TEXT_DIM      = "#4a4858"
BORDER        = "#2a2838"
SUCCESS       = "#4caf78"
WARNING       = "#e8a84a"
DANGER        = "#e05a5a"
HIGHLIGHT     = "#252535"


STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {DARK_BG};
    color: {TEXT_PRIMARY};
    font-family: 'Ubuntu', 'Segoe UI', sans-serif;
    font-size: 13px;
}}

/* Sidebar */
#sidebar {{
    background-color: {PANEL_BG};
    border-right: 1px solid {BORDER};
    min-width: 220px;
    max-width: 260px;
}}

#deviceCard {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 12px;
    margin: 8px;
}}

#appTitle {{
    font-size: 22px;
    font-weight: 700;
    color: {ACCENT};
    letter-spacing: 2px;
    padding: 16px 16px 4px 16px;
}}

#appSubtitle {{
    font-size: 10px;
    color: {TEXT_DIM};
    letter-spacing: 3px;
    padding: 0px 16px 12px 16px;
}}

/* Tabs */
QTabWidget::pane {{
    border: none;
    background-color: {DARK_BG};
}}

QTabBar::tab {{
    background-color: {PANEL_BG};
    color: {TEXT_SECONDARY};
    padding: 10px 24px;
    border: none;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

QTabBar::tab:selected {{
    background-color: {DARK_BG};
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}

QTabBar::tab:hover:!selected {{
    color: {TEXT_PRIMARY};
    background-color: {HIGHLIGHT};
}}

/* Table */
QTableWidget {{
    background-color: {DARK_BG};
    border: none;
    gridline-color: {BORDER};
    selection-background-color: {HIGHLIGHT};
    selection-color: {TEXT_PRIMARY};
    alternate-background-color: {PANEL_BG};
}}

QTableWidget::item {{
    padding: 6px 10px;
    border: none;
}}

QTableWidget::item:selected {{
    background-color: {HIGHLIGHT};
    color: {ACCENT};
}}

QHeaderView::section {{
    background-color: {PANEL_BG};
    color: {TEXT_SECONDARY};
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

/* Buttons */
QPushButton {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: {HIGHLIGHT};
    border-color: {ACCENT_DIM};
    color: {ACCENT};
}}

QPushButton:pressed {{
    background-color: {ACCENT_DIM};
    color: {DARK_BG};
}}

QPushButton:disabled {{
    background-color: {CARD_BG};
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

QPushButton#primaryBtn {{
    background-color: {ACCENT};
    color: {DARK_BG};
    border: none;
    font-weight: 700;
}}

QPushButton#primaryBtn:hover {{
    background-color: #d9ba80;
    color: {DARK_BG};
}}

QPushButton#primaryBtn:disabled {{
    background-color: {ACCENT_DIM};
    color: {TEXT_DIM};
    border: none;
}}

QPushButton#dangerBtn {{
    background-color: transparent;
    color: {DANGER};
    border: 1px solid {DANGER};
}}

/* Search bar */
QLineEdit {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 13px;
}}

QLineEdit:focus {{
    border-color: {ACCENT_DIM};
}}

QLineEdit::placeholder {{
    color: {TEXT_DIM};
}}

/* Progress bar */
QProgressBar {{
    background-color: {CARD_BG};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    font-size: 10px;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {PANEL_BG};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT_DIM};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {PANEL_BG};
    height: 8px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
}}

/* Status bar */
QStatusBar {{
    background-color: {PANEL_BG};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
    font-size: 11px;
    padding: 2px 8px;
}}

/* Splitter */
QSplitter::handle {{
    background-color: {BORDER};
    width: 1px;
}}

/* Toolbar */
QToolBar {{
    background-color: {PANEL_BG};
    border-bottom: 1px solid {BORDER};
    padding: 4px 8px;
    spacing: 4px;
}}

QLabel#sectionLabel {{
    color: {TEXT_DIM};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 12px 16px 4px 16px;
}}

QFrame#divider {{
    background-color: {BORDER};
    max-height: 1px;
    margin: 4px 16px;
}}
"""


class StorageBar(QWidget):
    """Custom storage usage bar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._used_pct = 0.0

    def set_usage(self, pct: float):
        self._used_pct = max(0.0, min(pct, 100.0))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2

        # Background
        painter.setBrush(QBrush(QColor(CARD_BG)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, w, h, r, r)

        # Fill
        fill_w = int(w * self._used_pct / 100)
        if fill_w > 0:
            color = QColor(ACCENT) if self._used_pct < 80 else QColor(WARNING) if self._used_pct < 95 else QColor(DANGER)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(0, 0, fill_w, h, r, r)

        painter.end()


class DeviceWorker(QObject):
    """Runs device polling in a QThread."""
    device_connected = Signal(object)
    device_disconnected = Signal()

    def __init__(self, manager: DeviceManager):
        super().__init__()
        self._manager = manager

    def start(self):
        self._manager.set_callbacks(
            on_connected=self.device_connected.emit,
            on_disconnected=self.device_disconnected.emit,
        )
        self._manager.start_polling()


class _MusicBridge(QObject):
    """Qt signal bridge — safely delivers scanner callbacks to the main thread."""
    progress    = Signal(int, int)        # current, total
    complete    = Signal(list)            # tracks (stubs)
    hydrated    = Signal(list)            # indices updated
    hyd_done    = Signal()


class _PhotoBridge(QObject):
    """Qt signal bridge for photo scanner callbacks."""
    progress    = Signal(int, int)        # current, total
    complete    = Signal(list)            # photos (stubs)
    thumbs      = Signal(list)            # indices with new thumbnails
    thumb_done  = Signal()


class _TransferBridge(QObject):
    """
    Qt signal bridge — safely delivers TransferEngine worker-thread callbacks
    to the main thread. TransferEngine invokes its callbacks directly from a
    plain threading.Thread; emitting a Signal from that thread and connecting
    it to a slot here is what actually marshals the call onto the Qt main
    thread (Qt auto-queues cross-thread signal delivery). QTimer.singleShot
    does NOT do this — it only fires if the thread it was created on is
    pumping an event loop, which a bare threading.Thread never does.
    """
    job_progress  = Signal(object)   # TransferJob
    all_complete  = Signal()


# ── VLC iPhone path helper ────────────────────────────────────────────────────

VLC_DOCUMENTS_PATH = "AppDomain-org.videolan.vlc-ios/Documents"

def find_vlc_iphone_path(mount_point: str) -> Optional[str]:
    """
    Return the VLC documents folder on the mounted iPhone if VLC is installed,
    otherwise return None.
    """
    candidate = os.path.join(mount_point, VLC_DOCUMENTS_PATH)
    return candidate if os.path.isdir(candidate) else None


def _make_placeholder_icon(size: int = 40) -> QIcon:
    """Return a music-note QIcon for tracks with no artwork."""
    px = QPixmap(size, size)
    px.fill(QColor(CARD_BG))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor(TEXT_DIM))
    font = painter.font()
    font.setPixelSize(size // 2)
    painter.setFont(font)
    painter.drawText(px.rect(), Qt.AlignCenter, "♪")
    painter.end()
    return QIcon(px)


def _artwork_icon(data: bytes, size: int = 40) -> Optional[QIcon]:
    """Convert raw artwork bytes to a square QIcon, or None on failure."""
    if not data:
        return None
    px = QPixmap()
    if not px.loadFromData(data):
        return None
    return QIcon(px.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class TagEditorDialog(QDialog):
    """
    Modal ID3 / metadata tag editor.
    Supports MP3 (via eyeD3) and M4A/AAC/FLAC/etc (via mutagen).
    Writes directly to the file on the mounted iPhone.
    """

    def __init__(self, track: "Track", parent=None):
        super().__init__(parent)
        self._track = track
        self._new_artwork_data: Optional[bytes] = None
        self._new_artwork_path: Optional[str] = None
        self._saved = False

        self.setWindowTitle("Edit Tags")
        self.setMinimumWidth(620)
        self.setMinimumHeight(340)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog {{
                background: {DARK_BG};
                color: {TEXT_PRIMARY};
                font-family: 'Ubuntu', 'Segoe UI', sans-serif;
            }}
            QLabel {{
                background: transparent;
                color: {TEXT_PRIMARY};
                font-size: 12px;
            }}
            QLineEdit, QSpinBox {{
                background: {CARD_BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus, QSpinBox:focus {{
                border-color: {ACCENT_DIM};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: {PANEL_BG};
                border: none;
                width: 18px;
            }}
            QFormLayout QLabel {{
                color: {TEXT_SECONDARY};
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.5px;
            }}
            QDialogButtonBox QPushButton {{
                background: {CARD_BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 5px;
                padding: 7px 20px;
                font-size: 12px;
                font-weight: 600;
                min-width: 80px;
            }}
            QDialogButtonBox QPushButton:hover {{
                border-color: {ACCENT_DIM};
                color: {ACCENT};
            }}
            QDialogButtonBox QPushButton[text="Save"] {{
                background: {ACCENT};
                color: {DARK_BG};
                border: none;
                font-weight: 700;
            }}
            QDialogButtonBox QPushButton[text="Save"]:hover {{
                background: #d9ba80;
            }}
        """)
        self._build_ui()
        self._load_fields()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(20)

        # ── Left: artwork panel ───────────────────────────────────────────────
        art_col = QVBoxLayout()
        art_col.setSpacing(8)

        self.art_label = QLabel()
        self.art_label.setFixedSize(160, 160)
        self.art_label.setAlignment(Qt.AlignCenter)
        self.art_label.setStyleSheet(
            f"background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 8px;"
        )
        art_col.addWidget(self.art_label)

        self.change_art_btn = QPushButton("🖼  Change Artwork")
        self.change_art_btn.setStyleSheet(
            f"QPushButton {{ background: {CARD_BG}; color: {TEXT_SECONDARY}; "
            f"border: 1px solid {BORDER}; border-radius: 5px; padding: 6px 10px; "
            f"font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ border-color: {ACCENT_DIM}; color: {ACCENT}; }}"
        )
        self.change_art_btn.clicked.connect(self._pick_artwork)
        art_col.addWidget(self.change_art_btn)

        self.remove_art_btn = QPushButton("✕  Remove Artwork")
        self.remove_art_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {DANGER}; "
            f"border: 1px solid {DANGER}; border-radius: 5px; padding: 6px 10px; "
            f"font-size: 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {DANGER}; color: {DARK_BG}; }}"
        )
        self.remove_art_btn.clicked.connect(self._remove_artwork)
        art_col.addWidget(self.remove_art_btn)
        art_col.addStretch()
        root.addLayout(art_col)

        # ── Right: fields + buttons ───────────────────────────────────────────
        right_col = QVBoxLayout()
        right_col.setSpacing(0)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        def _field(placeholder=""):
            f = QLineEdit()
            f.setPlaceholderText(placeholder)
            f.setFixedHeight(34)
            return f

        self.f_title        = _field("Track title")
        self.f_artist       = _field("Artist name")
        self.f_album        = _field("Album name")
        self.f_album_artist = _field("Album artist")
        self.f_genre        = _field("Genre")

        year_row = QHBoxLayout()
        year_row.setSpacing(12)
        self.f_year = _field("YYYY")
        self.f_year.setMaximumWidth(90)
        year_row.addWidget(self.f_year)
        year_lbl2 = QLabel("Track #")
        year_lbl2.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 600;"
        )
        year_row.addWidget(year_lbl2)
        self.f_track_num = QSpinBox()
        self.f_track_num.setRange(0, 999)
        self.f_track_num.setFixedHeight(34)
        self.f_track_num.setMaximumWidth(80)
        year_row.addWidget(self.f_track_num)
        year_row.addStretch()

        form.addRow("Title",        self.f_title)
        form.addRow("Artist",       self.f_artist)
        form.addRow("Album",        self.f_album)
        form.addRow("Album Artist", self.f_album_artist)
        form.addRow("Genre",        self.f_genre)
        form.addRow("Year",         year_row)

        right_col.addLayout(form)
        right_col.addSpacing(16)

        path_lbl = QLabel(self._track.path)
        path_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 10px; background: transparent;"
        )
        path_lbl.setWordWrap(True)
        right_col.addWidget(path_lbl)
        right_col.addStretch()

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)
        right_col.addWidget(btn_box)

        root.addLayout(right_col, 1)

    def _load_fields(self):
        self.f_title.setText(self._track.title or "")
        self.f_artist.setText(self._track.artist or "")
        self.f_album.setText(self._track.album or "")
        self.f_album_artist.setText(self._track.album_artist or "")
        self.f_genre.setText(self._track.genre or "")
        self.f_year.setText(self._track.year or "")
        self.f_track_num.setValue(self._track.track_num or 0)
        self._display_artwork(self._track.artwork_data)

    def _display_artwork(self, data: Optional[bytes]):
        if data:
            px = QPixmap()
            px.loadFromData(data)
            if not px.isNull():
                self.art_label.setPixmap(
                    px.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self.art_label.setText("")
                return
        self.art_label.setPixmap(QPixmap())
        self.art_label.setText("No Artwork")
        self.art_label.setStyleSheet(
            f"background: {CARD_BG}; border: 1px solid {BORDER}; "
            f"border-radius: 8px; color: {TEXT_DIM}; font-size: 12px;"
        )

    def _pick_artwork(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Artwork", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.webp)"
        )
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read()
        self._new_artwork_data = data
        self._new_artwork_path = path
        self._display_artwork(data)

    def _remove_artwork(self):
        self._new_artwork_data = b""   # empty bytes = sentinel for "remove"
        self._new_artwork_path = None
        self._display_artwork(None)

    def _save(self):
        fpath = self._track.path
        ext = Path(fpath).suffix.lower()
        try:
            if ext == ".mp3":
                self._save_mp3(fpath)
            else:
                self._save_mutagen(fpath)
        except Exception as e:
            QMessageBox.critical(
                self, "Save Failed",
                f"Could not write tags to:\n{fpath}\n\n{e}"
            )
            return

        self._track.title        = self.f_title.text().strip()
        self._track.artist       = self.f_artist.text().strip()
        self._track.album        = self.f_album.text().strip()
        self._track.album_artist = self.f_album_artist.text().strip()
        self._track.genre        = self.f_genre.text().strip()
        self._track.year         = self.f_year.text().strip()
        self._track.track_num    = self.f_track_num.value()
        if self._new_artwork_data is not None:
            self._track.artwork_data = (
                self._new_artwork_data if self._new_artwork_data else None
            )
            self._track.has_artwork = bool(self._track.artwork_data)

        self._saved = True
        self.accept()

    def _save_mp3(self, fpath: str):
        try:
            import eyed3
            eyed3.log.setLevel("ERROR")
        except ImportError:
            raise RuntimeError("eyeD3 is not installed. Run: pip install eyeD3")
        af = eyed3.load(fpath)
        if af is None:
            raise RuntimeError("eyeD3 could not load this file.")
        if af.tag is None:
            af.initTag()
        tag = af.tag
        tag.title        = self.f_title.text().strip() or None
        tag.artist       = self.f_artist.text().strip() or None
        tag.album        = self.f_album.text().strip() or None
        tag.album_artist = self.f_album_artist.text().strip() or None
        tag.genre        = self.f_genre.text().strip() or None
        year_str = self.f_year.text().strip()
        if year_str.isdigit():
            tag.recording_date = eyed3.core.Date(int(year_str))
        else:
            tag.recording_date = None
        track_n = self.f_track_num.value()
        tag.track_num = (track_n, None) if track_n > 0 else None
        if self._new_artwork_data is not None:
            from eyed3.id3.frames import ImageFrame
            tag.images.remove("")
            if self._new_artwork_data:
                art_ext = Path(self._new_artwork_path or "").suffix.lower()
                mime = "image/jpeg" if art_ext in (".jpg", ".jpeg") else "image/png"
                tag.images.set(ImageFrame.FRONT_COVER, self._new_artwork_data, mime)
        tag.save(version=eyed3.id3.ID3_DEFAULT_VERSION)

    def _save_mutagen(self, fpath: str):
        try:
            from mutagen import File as MutagenFile
            from mutagen.mp4 import MP4, MP4Cover
        except ImportError:
            raise RuntimeError("mutagen is not installed. Run: pip install mutagen")
        ext = Path(fpath).suffix.lower()
        if ext in (".m4a", ".aac", ".mp4", ".m4v"):
            audio = MP4(fpath)
            audio["\xa9nam"] = [self.f_title.text().strip()]
            audio["\xa9ART"] = [self.f_artist.text().strip()]
            audio["\xa9alb"] = [self.f_album.text().strip()]
            audio["aART"]    = [self.f_album_artist.text().strip()]
            audio["\xa9gen"] = [self.f_genre.text().strip()]
            year_str = self.f_year.text().strip()
            if year_str:
                audio["\xa9day"] = [year_str]
            track_n = self.f_track_num.value()
            if track_n > 0:
                audio["trkn"] = [(track_n, 0)]
            if self._new_artwork_data is not None:
                if self._new_artwork_data:
                    art_ext = Path(self._new_artwork_path or "").suffix.lower()
                    fmt = MP4Cover.FORMAT_JPEG if art_ext in (".jpg", ".jpeg") else MP4Cover.FORMAT_PNG
                    audio["covr"] = [MP4Cover(self._new_artwork_data, imageformat=fmt)]
                else:
                    audio.pop("covr", None)
            audio.save()
        else:
            mf = MutagenFile(fpath, easy=True)
            if mf is None:
                raise RuntimeError(f"mutagen could not open: {fpath}")
            mf["title"]       = [self.f_title.text().strip()]
            mf["artist"]      = [self.f_artist.text().strip()]
            mf["album"]       = [self.f_album.text().strip()]
            mf["albumartist"] = [self.f_album_artist.text().strip()]
            mf["genre"]       = [self.f_genre.text().strip()]
            year_str = self.f_year.text().strip()
            if year_str:
                mf["date"] = [year_str]
            track_n = self.f_track_num.value()
            if track_n > 0:
                mf["tracknumber"] = [str(track_n)]
            mf.save()

    @property
    def saved(self) -> bool:
        return self._saved


# ─────────────────────────────────────────────────────────────────────────────

class MusicTab(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanner = MusicScanner()
        self._transfer = TransferEngine()
        self._mount_point: Optional[str] = None

        # _all_tracks is the full master list, indexed the same way the
        # scanner's own hydration-progress indices are (scan order).
        # _displayed_tracks is whatever is currently in the table — the
        # full list, or a filtered subset — and _path_to_row maps a track's
        # stable path identity to its current row. Every row-based action
        # must resolve through _displayed_tracks/_path_to_row, never index
        # into _all_tracks with a table row number: filtering changes which
        # rows are visible without reordering _all_tracks.
        self._all_tracks: List[Track] = []
        self._displayed_tracks: List[Track] = []
        self._path_to_row: dict = {}

        # Bridge: scanner background thread → main thread via Qt signals
        self._bridge = _MusicBridge()
        self._bridge.progress.connect(self._update_scan_progress)
        self._bridge.complete.connect(self._populate_table)
        self._bridge.hydrated.connect(self._refresh_rows)
        self._bridge.hyd_done.connect(self._on_hydration_done)

        # Bridge: TransferEngine worker thread → main thread via Qt signals
        # (see _TransferBridge docstring — QTimer.singleShot from that
        # thread would silently never fire).
        self._transfer_bridge = _TransferBridge()
        self._transfer_bridge.job_progress.connect(self._on_transfer_progress)
        self._transfer_bridge.all_complete.connect(self._on_transfer_complete)

        self._setup_ui()
        self._setup_scanner()
        self._setup_transfer()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(52)
        toolbar.setStyleSheet(f"background-color: {PANEL_BG}; border-bottom: 1px solid {BORDER};")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(8)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  Search tracks, artists, albums...")
        self.search_box.setFixedHeight(34)
        self.search_box.textChanged.connect(self._filter_tracks)
        tl.addWidget(self.search_box)

        tl.addStretch()

        self.export_btn = QPushButton("⬇  Export Selected")
        self.export_btn.setFixedHeight(34)
        self.export_btn.setEnabled(False)   # enabled only when rows are selected
        self.export_btn.clicked.connect(self._export_selected)
        tl.addWidget(self.export_btn)

        self.add_btn = QPushButton("⬆  Add to iPhone")
        self.add_btn.setFixedHeight(34)
        self.add_btn.clicked.connect(self._add_tracks)
        tl.addWidget(self.add_btn)

        layout.addWidget(toolbar)

        # Progress bar (hidden by default)
        self.scan_progress = QProgressBar()
        self.scan_progress.setFixedHeight(3)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.hide()
        layout.addWidget(self.scan_progress)

        # Track table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["", "Title", "Artist", "Album", "Duration", "Size", "Year"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 46)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setIconSize(QSize(40, 40))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAcceptDrops(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table)

        # Empty state label
        self.empty_label = QLabel("Connect your iPhone to browse music")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 14px; padding: 40px;")
        layout.addWidget(self.empty_label)
        self.table.hide()

        # Transfer progress
        self.transfer_bar = QProgressBar()
        self.transfer_bar.setFixedHeight(20)
        self.transfer_bar.setTextVisible(True)
        self.transfer_bar.hide()
        layout.addWidget(self.transfer_bar)

    def set_player(self, player):
        self._player = player

    def _track_at_row(self, row: int) -> Optional[Track]:
        """
        Resolve the track for a table row against what's actually displayed
        (self._displayed_tracks), not the unfiltered master list — filtering
        changes which rows are visible without reordering _all_tracks, so a
        raw row index into _all_tracks would silently name the wrong track.
        """
        if 0 <= row < len(self._displayed_tracks):
            return self._displayed_tracks[row]
        return None

    def _on_double_click(self, index):
        """Double-click a track to load it into the player and start playing."""
        if not hasattr(self, '_player') or not self._player:
            return
        row = index.row()
        if self._track_at_row(row) is not None:
            self._player.set_playlist(self._displayed_tracks, row)

    def _show_context_menu(self, pos):
        """Right-click context menu on the track table."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        if self._track_at_row(row) is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {CARD_BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 4px;
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 7px 20px 7px 12px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {HIGHLIGHT};
                color: {ACCENT};
            }}
            QMenu::separator {{
                height: 1px;
                background: {BORDER};
                margin: 4px 8px;
            }}
        """)
        edit_action   = menu.addAction("✏️  Edit Tags...")
        menu.addSeparator()
        play_action   = menu.addAction("▶  Play")
        menu.addSeparator()
        export_action = menu.addAction("⬇  Export Selected")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == edit_action:
            self._edit_tags(row)
        elif action == play_action:
            if hasattr(self, '_player') and self._player:
                self._player.set_playlist(self._displayed_tracks, row)
        elif action == export_action:
            self._export_selected()

    def _edit_tags(self, row: int):
        """Open the tag editor for the track visibly at the given table row."""
        track = self._track_at_row(row)
        if track is None:
            return
        if not track.tags_loaded:
            QMessageBox.information(
                self, "Loading Metadata",
                "Track metadata is still loading. Please wait a moment and try again."
            )
            return
        dlg = TagEditorDialog(track, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.saved:
            # Refresh this row's text and artwork
            updates = {1: track.display_title, 2: track.display_artist,
                       3: track.display_album, 4: track.duration_str, 6: track.year or "—"}
            for col, text in updates.items():
                item = self.table.item(row, col)
                if item:
                    item.setText(text)
            # Update artwork icon in col 0
            art_item = self.table.item(row, 0)
            if art_item:
                _ph = _make_placeholder_icon(40)
                icon = _artwork_icon(track.artwork_data) if track.artwork_data else None
                art_item.setIcon(icon if icon else _ph)
            self.status_message.emit(
                f"Tags saved — {track.display_artist} · {track.display_title}"
            )

    def _setup_scanner(self):
        self._scanner.set_callbacks(
            on_progress=lambda c, t, tr: self._bridge.progress.emit(c, t),
            on_complete=lambda tracks: self._bridge.complete.emit(tracks),
            on_track_updated=lambda idx: self._bridge.hydrated.emit(idx),
            on_hydration_complete=lambda: self._bridge.hyd_done.emit(),
        )

    def _setup_transfer(self):
        # These callbacks run on TransferEngine's background worker thread.
        # Emitting a signal here (rather than touching widgets directly, or
        # using QTimer.singleShot) is what safely marshals the update onto
        # the Qt main thread — see _TransferBridge.
        self._transfer.set_callbacks(
            on_job_progress=self._transfer_bridge.job_progress.emit,
            on_all_complete=self._transfer_bridge.all_complete.emit,
        )

    def load_from_mount(self, mount_point: str):
        self._mount_point = mount_point
        self.empty_label.setText("Scanning music library...")
        self.empty_label.show()
        self.table.hide()
        self.scan_progress.setRange(0, 0)   # Indeterminate spinner during discovery
        self.scan_progress.show()
        self._scanner.scan_async(mount_point)

    def refresh(self):
        """Re-scan without remounting."""
        if self._mount_point:
            self.load_from_mount(self._mount_point)
        else:
            self.status_message.emit("No device mounted — nothing to refresh")

    # ── Phase 1 callbacks — delivered via _MusicBridge signals ─────────────

    def _update_scan_progress(self, current, total):
        """Slot: connected to _bridge.progress signal — always on main thread."""
        if total > 0:
            self.scan_progress.setRange(0, total)
            self.scan_progress.setValue(current)
        self.status_message.emit(f"Finding tracks... {current}/{total}")

    def _populate_table(self, tracks):
        self._all_tracks = tracks
        self.scan_progress.hide()

        if not tracks:
            self.empty_label.setText("No music found on this device.")
            return

        self.empty_label.hide()
        self.table.show()
        self._fill_table(tracks)
        self.status_message.emit(
            f"{len(tracks)} tracks found — loading metadata…"
        )

    def _fill_table(self, tracks):
        """
        Batch-populate the table with updates disabled to prevent
        a repaint on every row insertion.
        Col 0: artwork icon (placeholder until tags hydrate)
        Col 1-6: Title, Artist, Album, Duration, Size, Year

        Whatever list is passed here becomes the displayed set — every
        row-based action resolves against it (see _track_at_row), so this
        is the single place that _displayed_tracks/_path_to_row are updated.
        """
        self._displayed_tracks = tracks
        self._path_to_row = {track.path: row for row, track in enumerate(tracks)}

        _placeholder = _make_placeholder_icon(40)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(tracks))

        for row, track in enumerate(tracks):
            # Col 0 — artwork
            art_item = QTableWidgetItem()
            art_item.setData(Qt.UserRole, track.path)
            icon = _artwork_icon(track.artwork_data) if track.artwork_data else None
            art_item.setIcon(icon if icon else _placeholder)
            art_item.setFlags(art_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, art_item)

            # Cols 1-6 — text fields
            texts = [
                track.display_title,
                track.display_artist,
                track.display_album,
                track.duration_str,
                track.size_str,
                track.year or "—",
            ]
            for col, text in enumerate(texts, start=1):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, track.path)
                if col > 1:
                    item.setForeground(QColor(TEXT_SECONDARY))
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 46)

        self.table.setUpdatesEnabled(True)

    # ── Phase 2 callbacks — delivered via _MusicBridge signals ─────────────

    def _refresh_rows(self, indices: list):
        """
        Update only the rows whose tags have just been loaded.
        `indices` are positions into _all_tracks (the scanner's own master
        list order) — NOT table rows. Resolve each to a track, then to its
        current on-screen row via _path_to_row, since a filter may be active
        and hydration can complete for tracks that aren't currently visible.
        """
        _placeholder = _make_placeholder_icon(40)
        self.table.setUpdatesEnabled(False)

        for master_idx in indices:
            if master_idx >= len(self._all_tracks):
                continue
            track = self._all_tracks[master_idx]
            row = self._path_to_row.get(track.path)
            if row is None:
                continue   # filtered out — nothing on screen to update

            # Col 0 — update artwork icon now that tags are loaded
            art_item = self.table.item(row, 0)
            if art_item:
                icon = _artwork_icon(track.artwork_data) if track.artwork_data else None
                art_item.setIcon(icon if icon else _placeholder)

            # Cols 1-6 — text fields
            updates = {
                1: track.display_title,
                2: track.display_artist,
                3: track.display_album,
                4: track.duration_str,
                6: track.year or "—",
            }
            for col, text in updates.items():
                item = self.table.item(row, col)
                if item:
                    item.setText(text)
                else:
                    new_item = QTableWidgetItem(text)
                    new_item.setData(Qt.UserRole, track.path)
                    if col > 1:
                        new_item.setForeground(QColor(TEXT_SECONDARY))
                    self.table.setItem(row, col, new_item)

        self.table.setUpdatesEnabled(True)

    def _on_hydration_done(self):
        """Slot: connected to _bridge.hyd_done signal."""
        self.status_message.emit(f"{len(self._all_tracks)} tracks — metadata loaded")

    def _filter_tracks(self, query: str):
        if not query:
            self._fill_table(self._all_tracks)
        else:
            filtered = self._scanner.filter_tracks(query)
            self._fill_table(filtered)

    def _on_selection_changed(self):
        """Enable Export button only when at least one row is selected."""
        has_selection = len(self.table.selectedItems()) > 0
        self.export_btn.setEnabled(has_selection)

    def _export_selected(self):
        rows = list(set(
            item.row() for item in self.table.selectedItems()
        ))
        if not rows:
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "Export To...")
        if not dest_dir:
            return

        self._transfer.clear()

        for r in rows:
            src_item = self.table.item(r, 1)   # col 1 = Title (holds path in UserRole)
            if not src_item:
                continue
            src_path = src_item.data(Qt.UserRole)

            track = self._track_at_row(r)
            ext = Path(src_path).suffix.lower()

            if track and track.title:
                safe_title = "".join(
                    c for c in track.title if c not in r'\/:*?"<>|'
                ).strip()
                if track.artist:
                    safe_artist = "".join(
                        c for c in track.display_artist if c not in r'\/:*?"<>|'
                    ).strip()
                    filename = f"{safe_artist} - {safe_title}{ext}"
                else:
                    filename = f"{safe_title}{ext}"
            else:
                filename = os.path.basename(src_path)

            dest_path = os.path.join(dest_dir, filename)
            counter = 1
            while os.path.exists(dest_path):
                stem = Path(filename).stem
                dest_path = os.path.join(dest_dir, f"{stem} ({counter}){ext}")
                counter += 1

            self._transfer.add_job(src_path, dest_path, TransferDirection.FROM_DEVICE)

        count = len(rows)
        self.transfer_bar.setRange(0, count)
        self.transfer_bar.setValue(0)
        self.transfer_bar.show()
        self.status_message.emit(f"Exporting {count} track(s)...")
        self._transfer.start()

    def _add_tracks(self):
        if not self._mount_point:
            QMessageBox.warning(self, "Not Connected", "Connect an iPhone first.")
            return

        vlc_path = find_vlc_iphone_path(self._mount_point)
        if not vlc_path:
            reply = QMessageBox.warning(
                self,
                "VLC Not Found on iPhone",
                "MoTunes transfers music via the VLC app for instant playback "
                "on your iPhone — no iTunes sync required.\n\n"
                "VLC was not found on this device.\n\n"
                "Install VLC for iPhone from the App Store, then try again.\n\n"
                "Note: Direct transfer to the Apple Music library is in development "
                "for a future release.",
                QMessageBox.Ok | QMessageBox.Help,
            )
            if reply == QMessageBox.Help:
                import webbrowser
                webbrowser.open("https://apps.apple.com/app/vlc-for-mobile/id650377962")
            return

        files, _ = QFileDialog.getOpenFileNames(
            self, "Add Tracks to iPhone (via VLC)", "",
            "Audio Files (*.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus *.aiff)"
        )
        if not files:
            return

        self._transfer.add_jobs(files, vlc_path, TransferDirection.TO_DEVICE)
        self.transfer_bar.setRange(0, len(files))
        self.transfer_bar.setValue(0)
        self.transfer_bar.show()
        self.status_message.emit(f"Sending {len(files)} file(s) to VLC on iPhone...")
        self._transfer.start()

    def is_transfer_active(self) -> bool:
        """Public state MainWindow can check before unmounting/closing."""
        return self._transfer.is_running

    def _on_transfer_progress(self, job):
        """Slot: connected to _transfer_bridge.job_progress — always on main thread."""
        completed = sum(1 for j in self._transfer.queue if j.status == TransferStatus.COMPLETE)
        self.transfer_bar.setValue(completed)

    def _on_transfer_complete(self):
        """Slot: connected to _transfer_bridge.all_complete — always on main thread."""
        self.transfer_bar.hide()
        self.status_message.emit("Transfer complete!")


class PhotoGrid(QWidget):
    """
    Reusable scrollable photo grid with:
    - Date-grouped sections (newest first)
    - Click to select / deselect (gold border highlight)
    - Ctrl+click multi-select
    - Two-phase thumbnail hydration
    """
    selection_changed = Signal(int)   # emits selected count
    export_requested = Signal()
    delete_requested = Signal()

    COLS = 5
    CELL_W = 130
    CELL_H = 155   # taller to fit size label on video cells

    def __init__(self, show_size: bool = False, parent=None):
        super().__init__(parent)
        self._photos: List[Photo] = []
        self._selected: set = set()          # indices into self._photos
        self._thumb_cells: dict = {}         # global_index → img_label
        self._cell_frames: dict = {}         # global_index → QFrame
        self._show_size = show_size          # show file size on cells (videos)
        self._last_clicked: Optional[int] = None   # anchor for shift+click range select
        self._display_order: List[int] = []        # global indices in on-screen order
        self._pos_by_idx: dict = {}                 # global_index → position in _display_order
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {DARK_BG}; }}"
        )

        self.container = QWidget()
        self.container.setStyleSheet(f"background: {DARK_BG};")
        self.v_layout = QVBoxLayout(self.container)
        self.v_layout.setContentsMargins(12, 12, 12, 24)
        self.v_layout.setSpacing(0)
        self.v_layout.addStretch()

        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)

    def load(self, photos: List[Photo]):
        self._photos = photos
        self._selected.clear()
        self._thumb_cells.clear()
        self._cell_frames.clear()
        self._last_clicked = None
        self._rebuild()
        self.selection_changed.emit(0)

    def _rebuild(self):
        # Clear existing layout items (except trailing stretch)
        while self.v_layout.count() > 1:
            item = self.v_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._photos:
            return

        # Group by "Month YYYY" — newest first
        from collections import OrderedDict
        groups: OrderedDict = OrderedDict()
        sorted_photos = sorted(
            enumerate(self._photos),
            key=lambda t: t[1].date_taken or __import__("datetime").datetime.min,
            reverse=True,
        )
        for global_idx, photo in sorted_photos:
            if photo.date_taken:
                key = photo.date_taken.strftime("%B %Y")
            else:
                key = "Unknown Date"
            groups.setdefault(key, []).append((global_idx, photo))

        # Flattened on-screen order, used for shift+click range selection
        self._display_order = [gi for items in groups.values() for gi, _ in items]
        self._pos_by_idx = {gi: pos for pos, gi in enumerate(self._display_order)}

        for month_label, items in groups.items():
            # Section header
            hdr = QLabel(month_label)
            hdr.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 700; "
                f"letter-spacing: 1px; padding: 14px 4px 6px 4px; "
                f"background: transparent; border: none;"
            )
            self.v_layout.insertWidget(self.v_layout.count() - 1, hdr)

            # Grid for this month
            month_widget = QWidget()
            month_widget.setStyleSheet(f"background: {DARK_BG};")
            grid = QGridLayout(month_widget)
            grid.setSpacing(6)
            grid.setContentsMargins(0, 0, 0, 0)

            for pos, (global_idx, photo) in enumerate(items):
                cell, img_label = self._make_cell(photo, global_idx)
                self._thumb_cells[global_idx] = img_label
                self._cell_frames[global_idx] = cell
                grid.addWidget(cell, pos // self.COLS, pos % self.COLS)

            # Fill remaining columns in last row so grid aligns left
            last_row_items = len(items) % self.COLS
            if last_row_items:
                for pad in range(self.COLS - last_row_items):
                    spacer = QWidget()
                    spacer.setFixedSize(self.CELL_W, self.CELL_H)
                    spacer.setStyleSheet("background: transparent;")
                    grid.addWidget(
                        spacer,
                        len(items) // self.COLS,
                        last_row_items + pad,
                    )

            self.v_layout.insertWidget(self.v_layout.count() - 1, month_widget)

    def _make_cell(self, photo: Photo, global_idx: int):
        cell = QFrame()
        cell.setFixedSize(self.CELL_W, self.CELL_H)
        cell.setStyleSheet(self._cell_style(False))
        cell.setCursor(Qt.PointingHandCursor)

        cl = QVBoxLayout(cell)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(2)

        img_label = QLabel()
        img_label.setFixedSize(120, 100)
        img_label.setAlignment(Qt.AlignCenter)

        if photo.is_video:
            img_label.setText("▶")
            img_label.setStyleSheet(
                f"background: {DARK_BG}; color: {ACCENT}; font-size: 28px; "
                f"border-radius: 4px; border: none;"
            )
        else:
            img_label.setText("🖼")
            img_label.setStyleSheet(
                f"background: {DARK_BG}; color: {TEXT_DIM}; font-size: 24px; "
                f"border-radius: 4px; border: none;"
            )
        cl.addWidget(img_label)

        name_label = QLabel(
            photo.filename[:16] + ("…" if len(photo.filename) > 16 else "")
        )
        name_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 9px; border: none; background: transparent;"
        )
        name_label.setAlignment(Qt.AlignCenter)
        cl.addWidget(name_label)

        if self._show_size:
            size_label = QLabel(photo.size_str)
            size_label.setStyleSheet(
                f"color: {TEXT_DIM}; font-size: 9px; border: none; background: transparent;"
            )
            size_label.setAlignment(Qt.AlignCenter)
            cl.addWidget(size_label)

        # Single-click → select (ctrl = toggle, shift = range), double-click → preview,
        # right-click → context menu
        def make_click(idx):
            def handler(event):
                if event.button() == Qt.RightButton:
                    if idx not in self._selected:
                        self._single_select(idx)
                        self._last_clicked = idx
                    self._show_context_menu(event.globalPosition().toPoint())
                    return
                modifiers = QApplication.keyboardModifiers()
                if modifiers & Qt.ShiftModifier and self._last_clicked is not None:
                    self._range_select(self._last_clicked, idx)
                elif modifiers & Qt.ControlModifier:
                    self._toggle_select(idx)
                    self._last_clicked = idx
                else:
                    self._single_select(idx)
                    self._last_clicked = idx
            return handler

        def make_dbl_click(photo_obj):
            def handler(event):
                try:
                    subprocess.Popen(["xdg-open", photo_obj.path])
                except Exception as e:
                    print(f"[Preview] xdg-open failed: {e}")
            return handler

        click_fn = make_click(global_idx)
        dbl_fn = make_dbl_click(photo)
        cell.mousePressEvent = click_fn
        cell.mouseDoubleClickEvent = dbl_fn
        img_label.mousePressEvent = click_fn
        img_label.mouseDoubleClickEvent = dbl_fn
        name_label.mousePressEvent = click_fn
        name_label.mouseDoubleClickEvent = dbl_fn

        cell.setProperty("photo_idx", global_idx)
        return cell, img_label

    def _cell_style(self, selected: bool) -> str:
        if selected:
            return (
                f"QFrame {{ background: {CARD_BG}; border-radius: 6px; "
                f"border: 2px solid {ACCENT}; }}"
            )
        return (
            f"QFrame {{ background: {CARD_BG}; border-radius: 6px; "
            f"border: 1px solid {BORDER}; }}"
            f"QFrame:hover {{ border: 1px solid {ACCENT_DIM}; }}"
        )

    def _toggle_select(self, idx: int):
        if idx in self._selected:
            self._selected.discard(idx)
        else:
            self._selected.add(idx)
        self._update_cell_style(idx)
        self.selection_changed.emit(len(self._selected))

    def _single_select(self, idx: int):
        # If clicking an already-selected cell solo, deselect it
        if self._selected == {idx}:
            self._selected.clear()
            self._update_cell_style(idx)
            self.selection_changed.emit(0)
            return
        prev = set(self._selected)
        self._selected = {idx}
        for i in prev:
            self._update_cell_style(i)
        self._update_cell_style(idx)
        self.selection_changed.emit(1)

    def _range_select(self, from_idx: int, to_idx: int):
        """Shift+click — select every cell between the anchor and the clicked cell,
        in on-screen (display) order rather than raw list order."""
        if from_idx not in self._pos_by_idx or to_idx not in self._pos_by_idx:
            self._single_select(to_idx)
            return
        p1 = self._pos_by_idx[from_idx]
        p2 = self._pos_by_idx[to_idx]
        lo, hi = min(p1, p2), max(p1, p2)
        range_ids = set(self._display_order[lo:hi + 1])
        prev = set(self._selected)
        self._selected = prev | range_ids
        for idx in prev.symmetric_difference(self._selected):
            self._update_cell_style(idx)
        self.selection_changed.emit(len(self._selected))

    def _update_cell_style(self, idx: int):
        frame = self._cell_frames.get(idx)
        if frame:
            frame.setStyleSheet(self._cell_style(idx in self._selected))

    def _show_context_menu(self, global_pos):
        count = len(self._selected)
        if not count:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {CARD_BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 4px;
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 7px 20px 7px 12px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {HIGHLIGHT};
                color: {ACCENT};
            }}
            QMenu::separator {{
                height: 1px;
                background: {BORDER};
                margin: 4px 8px;
            }}
        """)
        export_act = menu.addAction(f"⬇  Export {count} item(s)...")
        menu.addSeparator()
        delete_act = menu.addAction(f"🗑  Delete {count} item(s) from iPhone")

        action = menu.exec(global_pos)
        if action == export_act:
            self.export_requested.emit()
        elif action == delete_act:
            self.delete_requested.emit()

    def delete_selected(self):
        """Delete the selected items from the iPhone via the ifuse mount.
        Returns (deleted_paths: set, failed_filenames: list)."""
        to_delete = self.selected_photos
        failed = []
        deleted_paths = set()
        for photo in to_delete:
            try:
                os.remove(photo.path)
                deleted_paths.add(photo.path)
            except Exception as e:
                failed.append(photo.filename)
                print(f"[PhotoGrid] Delete failed: {photo.path} — {e}")

        if deleted_paths:
            remaining = [p for p in self._photos if p.path not in deleted_paths]
            self.load(remaining)
            if remaining:
                # Thumbnails were already generated earlier; re-apply the cached
                # ones against the new (post-delete) indices rather than rescanning.
                self.apply_thumbnails(list(range(len(remaining))))

        return deleted_paths, failed

    def apply_thumbnails(self, indices: list):
        """Called from PhotosTab when thumbnails are ready."""
        for i in indices:
            if i >= len(self._photos):
                continue
            photo = self._photos[i]
            img_label = self._thumb_cells.get(i)
            if not img_label:
                continue
            if photo.thumbnail_path and os.path.exists(photo.thumbnail_path):
                px = QPixmap(photo.thumbnail_path).scaled(
                    120, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                img_label.setText("")
                img_label.setStyleSheet(
                    f"background: {DARK_BG}; border-radius: 4px; border: none;"
                )
                img_label.setPixmap(px)

    def select_all(self):
        self._selected = set(range(len(self._photos)))
        for idx in self._cell_frames:
            self._update_cell_style(idx)
        self.selection_changed.emit(len(self._selected))

    def clear_selection(self):
        prev = set(self._selected)
        self._selected.clear()
        for idx in prev:
            self._update_cell_style(idx)
        self.selection_changed.emit(0)

    @property
    def selected_photos(self) -> List[Photo]:
        return [self._photos[i] for i in sorted(self._selected) if i < len(self._photos)]

    @property
    def all_photos(self) -> List[Photo]:
        return self._photos


class PhotosTab(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanner = PhotoScanner()
        self._all_media: List[Photo] = []
        self._mount_point: Optional[str] = None

        # Bridge: scanner background thread → main thread via Qt signals
        self._bridge = _PhotoBridge()
        self._bridge.progress.connect(self._update_progress)
        self._bridge.complete.connect(self._on_scan_complete)
        self._bridge.thumbs.connect(self._apply_thumbnails)
        self._bridge.thumb_done.connect(self._on_thumb_done)

        self._setup_ui()
        self._scanner.set_callbacks(
            on_progress=lambda c, t, p: self._bridge.progress.emit(c, t),
            on_complete=lambda photos: self._bridge.complete.emit(photos),
            on_thumbnails_ready=lambda idx: self._bridge.thumbs.emit(idx),
            on_thumb_complete=lambda: self._bridge.thumb_done.emit(),
        )

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(52)
        toolbar.setStyleSheet(
            f"background-color: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(8)

        self.count_label = QLabel("Photos")
        self.count_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 600;")
        tl.addWidget(self.count_label)

        self.sel_label = QLabel("")
        self.sel_label.setStyleSheet(f"color: {ACCENT}; font-size: 11px;")
        tl.addWidget(self.sel_label)

        tl.addStretch()

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedHeight(34)
        self.select_all_btn.clicked.connect(self._select_all)
        tl.addWidget(self.select_all_btn)

        self.export_all_btn = QPushButton("⬇  Export All")
        self.export_all_btn.setFixedHeight(34)
        self.export_all_btn.clicked.connect(self._export_all)
        tl.addWidget(self.export_all_btn)

        self.export_sel_btn = QPushButton("⬇  Export Selected")
        self.export_sel_btn.setFixedHeight(34)
        self.export_sel_btn.setEnabled(False)
        self.export_sel_btn.clicked.connect(self._export_selected)
        tl.addWidget(self.export_sel_btn)

        self.delete_btn = QPushButton("🗑  Delete Selected")
        self.delete_btn.setObjectName("dangerBtn")
        self.delete_btn.setFixedHeight(34)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_selected)
        tl.addWidget(self.delete_btn)

        layout.addWidget(toolbar)

        # ── Scan progress ─────────────────────────────────────────────────────
        self.scan_progress = QProgressBar()
        self.scan_progress.setFixedHeight(3)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.hide()
        layout.addWidget(self.scan_progress)

        # ── Sub-tabs: Photos | Videos | Albums ────────────────────────────────
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setDocumentMode(True)
        self.sub_tabs.setStyleSheet(f"""
            QTabBar::tab {{
                background-color: {DARK_BG};
                color: {TEXT_DIM};
                padding: 6px 18px;
                border: none;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 1px;
            }}
            QTabBar::tab:selected {{
                color: {ACCENT};
                border-bottom: 2px solid {ACCENT};
            }}
            QTabBar::tab:hover:!selected {{
                color: {TEXT_SECONDARY};
            }}
            QTabWidget::pane {{
                border: none;
                background: {DARK_BG};
            }}
        """)

        self.photo_grid = PhotoGrid(show_size=False)
        self.photo_grid.selection_changed.connect(self._on_selection_changed)
        self.photo_grid.export_requested.connect(self._export_selected)
        self.photo_grid.delete_requested.connect(self._delete_selected)
        self.sub_tabs.addTab(self.photo_grid, "📷  Photos")

        self.video_grid = PhotoGrid(show_size=True)
        self.video_grid.selection_changed.connect(self._on_selection_changed)
        self.video_grid.export_requested.connect(self._export_selected)
        self.video_grid.delete_requested.connect(self._delete_selected)
        self.sub_tabs.addTab(self.video_grid, "🎬  Videos")

        # Albums — coming soon placeholder styled as a card
        albums_placeholder = QWidget()
        albums_placeholder.setStyleSheet(f"background: {DARK_BG};")
        ap_layout = QVBoxLayout(albums_placeholder)
        ap_layout.setAlignment(Qt.AlignCenter)
        ap_card = QFrame()
        ap_card.setMinimumWidth(360)
        ap_card.setMaximumWidth(500)
        ap_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        ap_card.setStyleSheet(
            f"QFrame {{ background: {CARD_BG}; border: 1px solid {BORDER}; "
            f"border-radius: 10px; }}"
        )
        ap_cl = QVBoxLayout(ap_card)
        ap_cl.setContentsMargins(28, 24, 28, 24)
        ap_cl.setSpacing(10)
        ap_icon = QLabel("📚")
        ap_icon.setStyleSheet("font-size: 32px; background: transparent; border: none;")
        ap_icon.setAlignment(Qt.AlignCenter)
        ap_title = QLabel("Albums")
        ap_title.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {TEXT_PRIMARY}; "
            f"background: transparent; border: none;"
        )
        ap_title.setAlignment(Qt.AlignCenter)
        ap_desc = QLabel(
            "Album recognition reads the iPhone's PhotoData/Photos.sqlite "
            "database to show your Favorites, Selfies, Recents, and custom "
            "albums — so you can back up entire albums in one click.\n\n"
            "Coming in Phase 2."
        )
        ap_desc.setStyleSheet(
            f"font-size: 12px; color: {TEXT_SECONDARY}; "
            f"background: transparent; border: none;"
        )
        ap_desc.setWordWrap(True)
        ap_desc.setAlignment(Qt.AlignCenter)
        ap_cl.addWidget(ap_icon)
        ap_cl.addWidget(ap_title)
        ap_cl.addWidget(ap_desc)
        ap_layout.addWidget(ap_card)
        self.sub_tabs.addTab(albums_placeholder, "📚  Albums")

        # Empty state (shown over sub-tabs until scan completes)
        self.empty_label = QLabel("Connect your iPhone to browse photos")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 14px; padding: 40px;"
        )

        layout.addWidget(self.sub_tabs)
        layout.addWidget(self.empty_label)
        self.sub_tabs.hide()

        # Switch selection tracking when sub-tab changes
        self.sub_tabs.currentChanged.connect(self._on_subtab_changed)

    def _current_grid(self) -> PhotoGrid:
        idx = self.sub_tabs.currentIndex()
        return self.photo_grid if idx == 0 else self.video_grid

    def _on_subtab_changed(self, _):
        # Reflect selection count of newly visible grid
        grid = self._current_grid()
        self._on_selection_changed(len(grid.selected_photos))

    def _on_selection_changed(self, count: int):
        if count:
            self.sel_label.setText(f"{count} selected")
            self.export_sel_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
        else:
            self.sel_label.setText("")
            self.export_sel_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)

    def _select_all(self):
        self._current_grid().select_all()

    # ── Scan lifecycle ────────────────────────────────────────────────────────

    def load_from_mount(self, mount_point: str):
        self._mount_point = mount_point
        self.empty_label.setText("Scanning photos...")
        self.empty_label.show()
        self.sub_tabs.hide()
        self.scan_progress.setRange(0, 0)
        self.scan_progress.show()
        self._scanner.scan_async(mount_point)

    def refresh(self):
        if self._mount_point:
            self.load_from_mount(self._mount_point)
        else:
            self.status_message.emit("No device mounted — nothing to refresh")

    def _update_progress(self, current, total):
        if total > 0:
            self.scan_progress.setRange(0, total)
            self.scan_progress.setValue(current)

    def _on_scan_complete(self, all_media: list):
        self._all_media = all_media
        self.scan_progress.hide()

        photos = [p for p in all_media if not p.is_video]
        videos = [p for p in all_media if p.is_video and not p.is_live_photo]

        if not all_media:
            self.empty_label.setText("No photos found on this device.")
            return

        self.empty_label.hide()
        self.sub_tabs.show()

        # Update sub-tab labels with counts
        self.sub_tabs.setTabText(0, f"📷  Photos ({len(photos)})")
        self.sub_tabs.setTabText(1, f"🎬  Videos ({len(videos)})")

        self.count_label.setText(f"{len(all_media)} items")

        # Load grids — photos use global indices offset by 0, videos offset after
        # We keep a single master list in _all_media; grids get their own slice
        # with their own internal indices, so thumb hydration maps to _all_media
        self.photo_grid.load(photos)
        self.video_grid.load(videos)

        # Store separate lists for thumb hydration routing
        self._photos_list = photos
        self._videos_list = videos

        self.status_message.emit(
            f"{len(photos)} photos, {len(videos)} videos — generating thumbnails…"
        )

    def _apply_thumbnails(self, indices: list):
        """
        indices come from PhotoScanner referencing self._all_media positions.
        Route each to the correct grid.
        """
        photo_indices = []
        video_indices = []

        # Build reverse maps on demand (cheap, done once per batch)
        if not hasattr(self, '_photo_idx_map'):
            self._photo_idx_map = {}
            self._video_idx_map = {}
            pi = vi = 0
            for global_i, media in enumerate(self._all_media):
                if media.is_video:
                    self._video_idx_map[global_i] = vi
                    vi += 1
                else:
                    self._photo_idx_map[global_i] = pi
                    pi += 1

        for global_i in indices:
            if global_i in self._photo_idx_map:
                photo_indices.append(self._photo_idx_map[global_i])
            elif global_i in self._video_idx_map:
                video_indices.append(self._video_idx_map[global_i])

        if photo_indices:
            self.photo_grid.apply_thumbnails(photo_indices)
        if video_indices:
            self.video_grid.apply_thumbnails(video_indices)

    def _on_thumb_done(self):
        photos = len(self._photos_list) if hasattr(self, '_photos_list') else 0
        videos = len(self._videos_list) if hasattr(self, '_videos_list') else 0
        self.status_message.emit(f"{photos} photos, {videos} videos — ready")

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_all(self):
        grid = self._current_grid()
        items = grid.all_photos
        if not items:
            QMessageBox.information(self, "Nothing to Export", "No items to export.")
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "Export All To...")
        if not dest_dir:
            return
        engine = TransferEngine()
        engine.add_jobs([p.path for p in items], dest_dir, TransferDirection.FROM_DEVICE)
        engine.start()
        self.status_message.emit(f"Exporting {len(items)} items to {dest_dir}…")

    def _export_selected(self):
        grid = self._current_grid()
        items = grid.selected_photos
        if not items:
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "Export Selected To...")
        if not dest_dir:
            return
        engine = TransferEngine()
        engine.add_jobs([p.path for p in items], dest_dir, TransferDirection.FROM_DEVICE)
        engine.start()
        grid.clear_selection()
        self.status_message.emit(f"Exporting {len(items)} item(s) to {dest_dir}…")

    # ── Delete ────────────────────────────────────────────────────────────────

    def _delete_selected(self):
        grid = self._current_grid()
        items = grid.selected_photos
        if not items:
            return

        count = len(items)
        reply = QMessageBox.question(
            self, "Delete from iPhone",
            f"Permanently delete {count} item(s) from your iPhone?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        deleted_paths, failed = grid.delete_selected()

        if deleted_paths:
            self._all_media = [m for m in self._all_media if m.path not in deleted_paths]
            self._photos_list = [p for p in getattr(self, "_photos_list", []) if p.path not in deleted_paths]
            self._videos_list = [v for v in getattr(self, "_videos_list", []) if v.path not in deleted_paths]
            # Index maps are position-based and now stale — drop them so the next
            # thumbnail batch rebuilds them against the post-delete lists.
            if hasattr(self, "_photo_idx_map"):
                del self._photo_idx_map
                del self._video_idx_map
            self.count_label.setText(f"{len(self._all_media)} items")
            self.sub_tabs.setTabText(0, f"📷  Photos ({len(self._photos_list)})")
            self.sub_tabs.setTabText(1, f"🎬  Videos ({len(self._videos_list)})")

        if failed:
            QMessageBox.warning(
                self, "Some Deletes Failed",
                f"Could not delete {len(failed)} item(s):\n" + "\n".join(failed[:10])
            )
            self.status_message.emit(f"Deleted {len(deleted_paths)} item(s) ({len(failed)} failed)")
        elif deleted_paths:
            self.status_message.emit(f"Deleted {len(deleted_paths)} item(s) from iPhone")



class MyComputerTab(QWidget):
    """
    Local file browser — navigate Linux filesystem, select audio files,
    transfer them to the mounted iPhone.
    """
    status_message = Signal(str)
    transfer_to_phone = Signal(list)   # list of local file paths

    AUDIO_FILTER = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".aiff"}

    # Quick-access bookmarks
    BOOKMARKS = [
        ("🏠  Home",        os.path.expanduser("~")),
        ("🎵  Music",       os.path.expanduser("~/Music")),
        ("⬇  Downloads",   os.path.expanduser("~/Downloads")),
        ("🖥  Desktop",     os.path.expanduser("~/Desktop")),
        ("💾  Media",       "/media"),
        ("🔌  Mnt",         "/mnt"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path = os.path.expanduser("~/Music")
        self._mount_point: Optional[str] = None

        # Bridge: TransferEngine worker thread → main thread via Qt signals
        # (see _TransferBridge docstring — QTimer.singleShot from that
        # thread would silently never fire).
        self._transfer_bridge = _TransferBridge()
        self._transfer_bridge.job_progress.connect(self._on_transfer_progress)
        self._transfer_bridge.all_complete.connect(self._on_transfer_complete)

        self._setup_ui()
        self._navigate(self._current_path)

    def is_transfer_active(self) -> bool:
        """Public state MainWindow can check before unmounting/closing."""
        return self._transfer.is_running

    def set_player(self, player):
        self._player = player

    def set_mount_point(self, mount_point: Optional[str]):
        self._mount_point = mount_point
        # Re-evaluate button state based on current selection + mount
        self._on_selection_changed()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(52)
        toolbar.setStyleSheet(
            f"background-color: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(6)

        # Back button
        self.back_btn = QPushButton("◀")
        self.back_btn.setFixedSize(30, 34)
        self.back_btn.setToolTip("Go up one level")
        self.back_btn.clicked.connect(self._go_up)
        tl.addWidget(self.back_btn)

        # Path bar
        self.path_bar = QLineEdit()
        self.path_bar.setFixedHeight(34)
        self.path_bar.setPlaceholderText("Path...")
        self.path_bar.returnPressed.connect(
            lambda: self._navigate(self.path_bar.text().strip())
        )
        tl.addWidget(self.path_bar)

        tl.addStretch()

        # Select all / deselect
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedHeight(34)
        self.select_all_btn.clicked.connect(self.file_table.selectAll
            if hasattr(self, "file_table") else lambda: None)
        tl.addWidget(self.select_all_btn)

        # Transfer button
        self.transfer_btn = QPushButton("⬆  Send to iPhone")
        self.transfer_btn.setFixedHeight(34)
        self.transfer_btn.setEnabled(False)
        self.transfer_btn.clicked.connect(self._transfer_selected)
        tl.addWidget(self.transfer_btn)

        layout.addWidget(toolbar)

        # ── Main splitter: bookmarks | file list ──────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {BORDER}; }}")

        # Bookmarks panel
        bookmark_widget = QWidget()
        bookmark_widget.setFixedWidth(160)
        bookmark_widget.setStyleSheet(
            f"background: {PANEL_BG}; border-right: 1px solid {BORDER};"
        )
        bl = QVBoxLayout(bookmark_widget)
        bl.setContentsMargins(0, 8, 0, 8)
        bl.setSpacing(2)

        bm_label = QLabel("FAVORITES")
        bm_label.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 2px; padding: 4px 12px 8px 12px; background: transparent;"
        )
        bl.addWidget(bm_label)

        for label, path in self.BOOKMARKS:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_SECONDARY};
                    border: none;
                    text-align: left;
                    padding: 7px 12px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background: {HIGHLIGHT};
                    color: {TEXT_PRIMARY};
                }}
            """)
            btn.clicked.connect(lambda checked, p=path: self._navigate(p))
            bl.addWidget(btn)

        bl.addStretch()
        splitter.addWidget(bookmark_widget)

        # File list
        file_panel = QWidget()
        fl = QVBoxLayout(file_panel)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        self.file_table = QTableWidget()
        self.file_table.setColumnCount(4)
        self.file_table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Modified"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.verticalHeader().hide()
        self.file_table.setShowGrid(False)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.doubleClicked.connect(self._on_double_click)
        self.file_table.itemSelectionChanged.connect(self._on_selection_changed)
        self._player = None
        fl.addWidget(self.file_table)
        splitter.addWidget(file_panel)
        splitter.setSizes([160, 900])
        layout.addWidget(splitter)

        # Now wire select_all properly
        self.select_all_btn.clicked.disconnect()
        self.select_all_btn.clicked.connect(self.file_table.selectAll)

        # Transfer progress bar
        self.transfer_bar = QProgressBar()
        self.transfer_bar.setFixedHeight(20)
        self.transfer_bar.setTextVisible(True)
        self.transfer_bar.hide()
        layout.addWidget(self.transfer_bar)

        # Transfer engine — callbacks run on its background worker thread,
        # so they're wired to bridge signal emitters, not the slots directly.
        self._transfer = TransferEngine()
        self._transfer.set_callbacks(
            on_job_progress=self._transfer_bridge.job_progress.emit,
            on_all_complete=self._transfer_bridge.all_complete.emit,
        )

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate(self, path: str):
        """Load a directory into the file table."""
        if not os.path.exists(path):
            self.status_message.emit(f"Path not found: {path}")
            return

        # If it's a file, go to its parent
        if os.path.isfile(path):
            path = os.path.dirname(path)

        self._current_path = path
        self.path_bar.setText(path)
        self._load_directory(path)

    def _go_up(self):
        parent = os.path.dirname(self._current_path)
        if parent != self._current_path:
            self._navigate(parent)

    def _load_directory(self, path: str):
        """Populate the file table with contents of path."""
        self.file_table.setUpdatesEnabled(False)
        self.file_table.setRowCount(0)

        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            self.status_message.emit(f"Permission denied: {path}")
            self.file_table.setUpdatesEnabled(True)
            return

        audio_count = 0
        for entry in entries:
            # Skip hidden files
            if entry.name.startswith("."):
                continue

            is_dir = entry.is_dir()
            ext = Path(entry.name).suffix.lower()
            is_audio = ext in self.AUDIO_FILTER

            # Show directories and audio files only
            if not is_dir and not is_audio:
                continue

            row = self.file_table.rowCount()
            self.file_table.insertRow(row)

            # Name with icon
            icon = "📁" if is_dir else self._audio_icon(ext)
            name_item = QTableWidgetItem(f"{icon}  {entry.name}")
            name_item.setData(Qt.UserRole, entry.path)
            name_item.setData(Qt.UserRole + 1, is_dir)
            if not is_dir:
                name_item.setForeground(QColor(TEXT_PRIMARY))
            else:
                name_item.setForeground(QColor(TEXT_SECONDARY))
            self.file_table.setItem(row, 0, name_item)

            # Type
            type_text = "Folder" if is_dir else ext.upper().lstrip(".")
            type_item = QTableWidgetItem(type_text)
            type_item.setForeground(QColor(TEXT_DIM))
            self.file_table.setItem(row, 1, type_item)

            # Size
            try:
                stat = entry.stat()
                if is_dir:
                    size_text = "—"
                else:
                    mb = stat.st_size / (1024 * 1024)
                    size_text = f"{mb:.1f} MB" if mb >= 1 else f"{stat.st_size // 1024} KB"
                    audio_count += 1
                mod_text = __import__("datetime").datetime.fromtimestamp(
                    stat.st_mtime).strftime("%b %d, %Y")
            except Exception:
                size_text = "—"
                mod_text = "—"

            size_item = QTableWidgetItem(size_text)
            size_item.setForeground(QColor(TEXT_DIM))
            self.file_table.setItem(row, 2, size_item)

            mod_item = QTableWidgetItem(mod_text)
            mod_item.setForeground(QColor(TEXT_DIM))
            self.file_table.setItem(row, 3, mod_item)

            self.file_table.setRowHeight(row, 34)

        self.file_table.setUpdatesEnabled(True)
        self.status_message.emit(
            f"{path}  —  {audio_count} audio file(s)"
        )

    def _audio_icon(self, ext: str) -> str:
        icons = {
            ".mp3": "🎵", ".m4a": "🎵", ".aac": "🎵",
            ".flac": "🎶", ".wav": "🎼", ".ogg": "🎵",
            ".opus": "🎵", ".aiff": "🎼",
        }
        return icons.get(ext, "🎵")

    def _on_double_click(self, index):
        """Navigate into directory on double-click, or play audio file."""
        row = index.row()
        item = self.file_table.item(row, 0)
        if not item:
            return
        if item.data(Qt.UserRole + 1):  # is_dir
            self._navigate(item.data(Qt.UserRole))
        else:
            # Play the audio file — build a mini playlist from all audio in current dir
            if hasattr(self, '_player') and self._player:
                from core.music import Track as _Track
                audio_rows = [
                    r for r in range(self.file_table.rowCount())
                    if self.file_table.item(r, 0)
                    and not self.file_table.item(r, 0).data(Qt.UserRole + 1)
                ]
                tracks = []
                clicked_idx = 0
                for i, r in enumerate(audio_rows):
                    it = self.file_table.item(r, 0)
                    path = it.data(Qt.UserRole)
                    fname = os.path.basename(path)
                    t = _Track(path=path, filename=fname)
                    tracks.append(t)
                    if r == row:
                        clicked_idx = i
                self._player.set_playlist(tracks, clicked_idx)

    def _on_selection_changed(self):
        """Enable Send to iPhone only when audio files are selected and phone is mounted."""
        selected_rows = list(set(
            item.row() for item in self.file_table.selectedItems()
        ))
        has_audio = any(
            not self.file_table.item(r, 0).data(Qt.UserRole + 1)
            for r in selected_rows
            if self.file_table.item(r, 0)
        )
        self.transfer_btn.setEnabled(
            has_audio and self._mount_point is not None
        )

    # ── Transfer ──────────────────────────────────────────────────────────────

    def _transfer_selected(self):
        if not self._mount_point:
            QMessageBox.warning(self, "Not Mounted",
                                "Mount your iPhone first.")
            return

        rows = list(set(
            item.row() for item in self.file_table.selectedItems()
        ))
        paths = [
            self.file_table.item(r, 0).data(Qt.UserRole)
            for r in rows
            if self.file_table.item(r, 0)
            and not self.file_table.item(r, 0).data(Qt.UserRole + 1)  # not a dir
        ]
        if not paths:
            return

        # Route to VLC folder for instant playback — no sync required
        vlc_path = find_vlc_iphone_path(self._mount_point)
        if not vlc_path:
            reply = QMessageBox.warning(
                self,
                "VLC Not Found on iPhone",
                "MoTunes transfers music via the VLC app for instant playback "
                "on your iPhone — no iTunes sync required.\n\n"
                "VLC was not found on this device.\n\n"
                "Install VLC for iPhone from the App Store, then try again.\n\n"
                "Note: Direct transfer to the Apple Music library is in development "
                "for a future release.",
                QMessageBox.Ok | QMessageBox.Help,
            )
            if reply == QMessageBox.Help:
                import webbrowser
                webbrowser.open("https://apps.apple.com/app/vlc-for-mobile/id650377962")
            return

        self._transfer.clear()
        self._transfer.add_jobs(paths, vlc_path, TransferDirection.TO_DEVICE)
        self.transfer_bar.setRange(0, len(paths))
        self.transfer_bar.setValue(0)
        self.transfer_bar.show()
        self.status_message.emit(f"Sending {len(paths)} file(s) to VLC on iPhone...")
        self._transfer.start()

    def _on_transfer_progress(self, job):
        """Slot: connected to _transfer_bridge.job_progress — always on main thread."""
        completed = sum(
            1 for j in self._transfer.queue
            if j.status == TransferStatus.COMPLETE
        )
        self.transfer_bar.setValue(completed)

    def _on_transfer_complete(self):
        """Slot: connected to _transfer_bridge.all_complete — always on main thread."""
        self.transfer_bar.hide()
        self.status_message.emit("Transfer complete! Files sent to iPhone.")


class PlayerBar(QWidget):
    """
    Persistent player bar docked at the bottom of the content area.
    Uses python-vlc for playback across all audio formats.
    Double-click any track in Music or My Computer to load it.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = _vlc.MediaPlayer() if HAS_VLC else None
        self._playlist: List[Track] = []
        self._current_index = -1
        self._duration_ms = 0

        self.setFixedHeight(74)
        self.setStyleSheet(f"""
            PlayerBar {{
                background-color: {PANEL_BG};
                border-top: 2px solid {BORDER};
            }}
        """)
        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 0, 16, 0)
        root.setSpacing(16)

        # ── Album art ─────────────────────────────────────────────────────────
        self.art_label = QLabel()
        self.art_label.setFixedSize(54, 54)
        self.art_label.setAlignment(Qt.AlignCenter)
        self.art_label.setStyleSheet(
            f"background: {CARD_BG}; border: 1px solid {BORDER}; "
            f"border-radius: 6px; color: {TEXT_DIM}; font-size: 20px;"
        )
        self.art_label.setText("♪")
        root.addWidget(self.art_label)

        # ── Track info ────────────────────────────────────────────────────────
        info = QWidget()
        info.setFixedWidth(240)
        info.setStyleSheet("background: transparent;")
        il = QVBoxLayout(info)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(1)

        self.title_lbl = QLabel("No track loaded")
        self.title_lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600; background: transparent;"
        )
        self.title_lbl.setMaximumWidth(235)

        self.artist_lbl = QLabel("")
        self.artist_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        self.artist_lbl.setMaximumWidth(235)

        il.addWidget(self.title_lbl)
        il.addWidget(self.artist_lbl)
        root.addWidget(info)

        # ── Centre: transport + seek ──────────────────────────────────────────
        centre = QWidget()
        centre.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(0, 6, 0, 4)
        cl.setSpacing(4)

        # Transport row
        btn_row = QWidget()
        btn_row.setStyleSheet("background: transparent;")
        bl = QHBoxLayout(btn_row)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        bl.addStretch()

        ghost = f"""
            QPushButton {{
                background: transparent; color: {TEXT_SECONDARY};
                border: none; font-size: 17px; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {ACCENT}; }}
            QPushButton:disabled {{ color: {TEXT_DIM}; }}
        """

        self.prev_btn = QPushButton("⏮")
        self.prev_btn.setStyleSheet(ghost)
        self.prev_btn.setFixedSize(34, 30)
        self.prev_btn.clicked.connect(self.play_prev)
        bl.addWidget(self.prev_btn)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(34, 34)
        self.play_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; color: {DARK_BG};
                border: none; border-radius: 17px;
                font-size: 13px; font-weight: 700;
            }}
            QPushButton:hover {{ background: #d9ba80; }}
            QPushButton:disabled {{ background: {ACCENT_DIM}; color: {TEXT_DIM}; }}
        """)
        self.play_btn.clicked.connect(self.toggle_play)
        bl.addWidget(self.play_btn)

        self.next_btn = QPushButton("⏭")
        self.next_btn.setStyleSheet(ghost)
        self.next_btn.setFixedSize(34, 30)
        self.next_btn.clicked.connect(self.play_next)
        bl.addWidget(self.next_btn)

        bl.addStretch()
        cl.addWidget(btn_row)

        # Seek row
        seek_row = QWidget()
        seek_row.setStyleSheet("background: transparent;")
        sl = QHBoxLayout(seek_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)

        self.time_cur = QLabel("0:00")
        self.time_cur.setFixedWidth(34)
        self.time_cur.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; background: transparent;")
        sl.addWidget(self.time_cur)

        self.seek_bar = QProgressBar()
        self.seek_bar.setRange(0, 1000)
        self.seek_bar.setValue(0)
        self.seek_bar.setFixedHeight(4)
        self.seek_bar.setTextVisible(False)
        self.seek_bar.setStyleSheet(f"""
            QProgressBar {{ background: {BORDER}; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
        """)
        self.seek_bar.mousePressEvent = self._seek_click
        sl.addWidget(self.seek_bar)

        self.time_tot = QLabel("0:00")
        self.time_tot.setFixedWidth(34)
        self.time_tot.setAlignment(Qt.AlignRight)
        self.time_tot.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; background: transparent;")
        sl.addWidget(self.time_tot)

        cl.addWidget(seek_row)
        root.addWidget(centre, stretch=1)

        # ── Volume ────────────────────────────────────────────────────────────
        vol_w = QWidget()
        vol_w.setFixedWidth(120)
        vol_w.setStyleSheet("background: transparent;")
        vl = QHBoxLayout(vol_w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)

        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("background: transparent; font-size: 12px;")
        vl.addWidget(vol_icon)

        self.vol_bar = QProgressBar()
        self.vol_bar.setRange(0, 100)
        self.vol_bar.setValue(80)
        self.vol_bar.setFixedHeight(4)
        self.vol_bar.setTextVisible(False)
        self.vol_bar.setStyleSheet(f"""
            QProgressBar {{ background: {BORDER}; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {TEXT_SECONDARY}; border-radius: 2px; }}
        """)
        self.vol_bar.mousePressEvent = self._vol_click
        vl.addWidget(self.vol_bar)
        root.addWidget(vol_w)

        if self._player:
            self._player.audio_set_volume(80)

        self._set_controls_enabled(False)

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_playlist(self, tracks: List[Track], start_index: int = 0):
        """Load a full playlist and start playing from start_index."""
        self._playlist = tracks
        self.play_index(start_index)

    def play_index(self, index: int):
        if not self._playlist or not (0 <= index < len(self._playlist)):
            return
        self._current_index = index
        self._load(self._playlist[index])

    def play_next(self):
        self.play_index(self._current_index + 1)

    def play_prev(self):
        if self._player and self._player.get_time() > 3000:
            self._player.set_time(0)
        else:
            self.play_index(self._current_index - 1)

    def toggle_play(self):
        if not self._player:
            return
        if self._player.is_playing():
            self._player.pause()
            self.play_btn.setText("▶")
        else:
            self._player.play()
            self.play_btn.setText("⏸")

    def cleanup(self):
        if self._player:
            self._player.stop()
            self._player.release()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self, track: Track):
        if not self._player:
            return
        self._player.set_media(_vlc.Media(track.path))
        self._player.play()
        self.play_btn.setText("⏸")
        self._duration_ms = 0
        self.seek_bar.setValue(0)
        self.time_cur.setText("0:00")
        self.time_tot.setText("0:00")
        self.title_lbl.setText(track.display_title)
        self.artist_lbl.setText(track.display_artist)
        self._set_controls_enabled(True)

        # Album artwork in player bar
        if track.artwork_data:
            px = QPixmap()
            px.loadFromData(track.artwork_data)
            if not px.isNull():
                self.art_label.setText("")
                self.art_label.setPixmap(
                    px.scaled(54, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self.art_label.setStyleSheet(
                    f"background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 6px;"
                )
                return
        # No artwork — musical note placeholder
        self.art_label.setPixmap(QPixmap())
        self.art_label.setText("♪")
        self.art_label.setStyleSheet(
            f"background: {CARD_BG}; border: 1px solid {BORDER}; "
            f"border-radius: 6px; color: {TEXT_DIM}; font-size: 20px;"
        )

    def _tick(self):
        if not self._player:
            return
        state = self._player.get_state()
        if state == _vlc.State.Ended:
            self.play_next()
            return
        if not self._player.is_playing():
            return
        if self._duration_ms <= 0:
            self._duration_ms = self._player.get_length()
            if self._duration_ms > 0:
                self.time_tot.setText(self._fmt(self._duration_ms))
        pos = self._player.get_time()
        if pos >= 0 and self._duration_ms > 0:
            self.seek_bar.setValue(int(pos / self._duration_ms * 1000))
            self.time_cur.setText(self._fmt(pos))

    def _seek_click(self, event):
        if self._player and self._duration_ms > 0:
            pct = event.x() / max(self.seek_bar.width(), 1)
            self._player.set_time(int(pct * self._duration_ms))

    def _vol_click(self, event):
        if self._player:
            vol = int(event.x() / max(self.vol_bar.width(), 1) * 100)
            vol = max(0, min(100, vol))
            self._player.audio_set_volume(vol)
            self.vol_bar.setValue(vol)

    def _set_controls_enabled(self, on: bool):
        self.play_btn.setEnabled(on)
        self.prev_btn.setEnabled(on)
        self.next_btn.setEnabled(on)

    @staticmethod
    def _fmt(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60}:{s % 60:02d}"

# ── Device Tools Tab ──────────────────────────────────────────────────────────

class DeviceToolsTab(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mount_point: Optional[str] = None
        self._setup_ui()

    def set_mount_point(self, mount_point: Optional[str]):
        self._mount_point = mount_point
        # cleanup_btn stays permanently disabled — see the note above
        # _make_cleanup_card / where the old handlers used to be.

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {DARK_BG}; }}")

        container = QWidget()
        container.setStyleSheet(f"background: {DARK_BG};")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        header = QLabel("Device Tools")
        header.setStyleSheet(
            f"color: {ACCENT}; font-size: 18px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        sub = QLabel("Maintenance and management utilities for your iPhone.")
        sub.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(sub)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"background: {BORDER}; border: none; max-height: 1px; margin: 4px 0px;")
        layout.addWidget(div)

        layout.addWidget(self._make_cleanup_card())
        layout.addWidget(self._make_vlc_card())
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _make_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {CARD_BG};
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
        """)
        return card

    def _make_cleanup_card(self) -> QWidget:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        icon = QLabel("🧹")
        icon.setStyleSheet("font-size: 22px; background: transparent; border: none;")
        title = QLabel("Clean Music Library")
        title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {TEXT_PRIMARY}; "
            f"background: transparent; border: none;"
        )
        title_row.addWidget(icon)
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        desc = QLabel(
            "Safe orphan cleanup — removing only the audio files the iPhone's "
            "own library no longer references — is not implemented in this "
            "build.\n\n"
            "An earlier version of this feature deleted the entire "
            "iTunes_Control/Music/ folder tree and the iTunes sync database "
            "outright, with no orphan check at all. That destructive "
            "implementation has been removed. This card is a placeholder "
            "until real orphan-detection logic exists."
        )
        desc.setStyleSheet(
            f"font-size: 12px; color: {TEXT_SECONDARY}; "
            f"background: transparent; border: none;"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        warning = QLabel(
            "⚠  Not available yet — no cleanup action is performed by this card."
        )
        warning.setStyleSheet(
            f"font-size: 11px; color: {WARNING}; background: transparent; border: none;"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cleanup_btn = QPushButton("🧹  Not Available Yet")
        self.cleanup_btn.setObjectName("dangerBtn")
        self.cleanup_btn.setFixedHeight(36)
        self.cleanup_btn.setEnabled(False)
        self.cleanup_btn.setToolTip(
            "Safe orphan cleanup is not implemented in this build. "
            "No destructive action is available here."
        )
        btn_row.addWidget(self.cleanup_btn)
        layout.addLayout(btn_row)

        return card

    def _make_vlc_card(self) -> QWidget:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        icon = QLabel("📱")
        icon.setStyleSheet("font-size: 22px; background: transparent; border: none;")
        title = QLabel("VLC Transfer — How It Works")
        title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {TEXT_PRIMARY}; "
            f"background: transparent; border: none;"
        )
        title_row.addWidget(icon)
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        desc = QLabel(
            "MoTunes transfers music to your iPhone via VLC for Mobile. "
            "Files appear instantly in VLC with no iTunes sync required.\n\n"
            "Direct transfer to the Apple Music library is in development "
            "for a future release.\n\n"
            "VLC for iPhone is free on the App Store."
        )
        desc.setStyleSheet(
            f"font-size: 12px; color: {TEXT_SECONDARY}; "
            f"background: transparent; border: none;"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        vlc_btn = QPushButton("Open App Store — VLC")
        vlc_btn.setFixedHeight(36)
        vlc_btn.clicked.connect(lambda: __import__("webbrowser").open(
            "https://apps.apple.com/app/vlc-for-mobile/id650377962"
        ))
        btn_row.addWidget(vlc_btn)
        layout.addLayout(btn_row)

        return card

    # NOTE: The previous "Clean Music Library" implementation has been
    # removed. It recursively deleted every iTunes_Control/Music/F##
    # folder and the iTunes sync database files (iTunesDB, iTunesCDB,
    # iTunesControl, ...) with no orphan check at all — i.e. it was a full
    # wipe mislabeled as safe cleanup. There is intentionally no button
    # handler here: the card above is a disabled placeholder until real
    # orphan-detection logic (comparing on-disk files against what the
    # device's own metadata references) is implemented.


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MoTunes")
        self.setMinimumSize(1100, 680)
        self.resize(1280, 760)
        self.setStyleSheet(STYLESHEET)

        self._dev_manager = DeviceManager()
        self._current_mount: Optional[str] = None

        self._cleanup_stale_mounts()
        self._setup_ui()
        self._start_device_polling()

    def _cleanup_stale_mounts(self):
        """Unmount any leftover motunes mount points from previous sessions."""
        import glob
        for path in glob.glob("/tmp/motunes_media_*"):
            try:
                subprocess.run(["fusermount", "-u", path],
                               capture_output=True, timeout=5)
                os.rmdir(path)
                print(f"[MoTunes] Cleaned stale mount: {path}")
            except Exception:
                pass

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(230)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Logo / Title
        title = QLabel("MoTunes")
        title.setObjectName("appTitle")
        sub = QLabel("IPHONE MANAGER")
        sub.setObjectName("appSubtitle")
        credit = QLabel("by BINO of Mo Thugs")
        credit.setStyleSheet(f"color: {ACCENT_DIM}; font-size: 10px; font-style: italic; padding: 0px 16px 12px 16px;")
        sidebar_layout.addWidget(title)
        sidebar_layout.addWidget(sub)
        sidebar_layout.addWidget(credit)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        sidebar_layout.addWidget(divider)

        # Device card
        self.device_card = QWidget()
        self.device_card.setObjectName("deviceCard")
        dc_layout = QVBoxLayout(self.device_card)
        dc_layout.setSpacing(6)
        dc_layout.setContentsMargins(10, 10, 10, 10)

        self.device_icon = QLabel("📱")
        self.device_icon.setStyleSheet(f"font-size: 28px; background: transparent; border: none;")
        self.device_name = QLabel("No Device")
        self.device_name.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: 700; font-size: 13px; background: transparent; border: none;")
        self.device_ios = QLabel("Connect your iPhone")
        self.device_ios.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent; border: none;")
        self.device_ios.setWordWrap(True)

        self.storage_bar = StorageBar()
        self.storage_info = QLabel("")
        self.storage_info.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; background: transparent; border: none;")

        self.connect_btn = QPushButton("Mount Device")
        self.connect_btn.setObjectName("primaryBtn")
        self.connect_btn.setFixedHeight(32)
        self.connect_btn.clicked.connect(self._mount_device)
        self.connect_btn.setEnabled(False)

        dc_layout.addWidget(self.device_icon)
        dc_layout.addWidget(self.device_name)
        dc_layout.addWidget(self.device_ios)
        dc_layout.addWidget(self.storage_bar)
        dc_layout.addWidget(self.storage_info)
        dc_layout.addWidget(self.connect_btn)

        sidebar_layout.addWidget(self.device_card)

        # Nav section label
        nav_label = QLabel("LIBRARY")
        nav_label.setObjectName("sectionLabel")
        sidebar_layout.addWidget(nav_label)

        # Nav items — wired to tabs by index
        nav_items = [
            ("🎵", "Music",       0),
            ("📷", "Photos",      1),
            ("🖥",  "My Computer", 2),
            ("📋", "Playlists",   3),
        ]
        for icon, label, tab_idx in nav_items:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_SECONDARY};
                    border: none;
                    text-align: left;
                    padding: 10px 16px;
                    font-size: 13px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background: {HIGHLIGHT};
                    color: {TEXT_PRIMARY};
                    border-radius: 0px;
                }}
            """)
            btn.clicked.connect(lambda checked, i=tab_idx: self.tabs.setCurrentIndex(i))
            sidebar_layout.addWidget(btn)

        sidebar_layout.addStretch()

        # Copyright
        copyright_label = QLabel("© Mo Thugs South 2026  •  All Rights Reserved")
        copyright_label.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 9px; padding: 0px 16px 6px 16px; "
            f"background: transparent; letter-spacing: 1px;"
        )
        copyright_label.setWordWrap(True)
        copyright_label.setAlignment(Qt.AlignLeft)
        sidebar_layout.addWidget(copyright_label)

        # Connection status dot
        self.status_dot = QLabel("● Not Connected")
        self.status_dot.setStyleSheet(f"color: {DANGER}; font-size: 10px; padding: 8px 16px; background: transparent;")
        sidebar_layout.addWidget(self.status_dot)

        main_layout.addWidget(self.sidebar)

        # ── Content Area ─────────────────────────────────────────────────────
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # ── Global toolbar (Refresh) above tabs ──────────────────────────────
        global_toolbar = QWidget()
        global_toolbar.setFixedHeight(44)
        global_toolbar.setStyleSheet(
            f"background-color: {PANEL_BG}; border-bottom: 1px solid {BORDER};"
        )
        gt_layout = QHBoxLayout(global_toolbar)
        gt_layout.setContentsMargins(12, 6, 12, 6)
        gt_layout.setSpacing(8)
        gt_layout.addStretch()

        self.refresh_btn = QPushButton("↺  Refresh Library")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setToolTip("Re-scan the mounted iPhone without remounting")
        self.refresh_btn.clicked.connect(self._refresh_library)
        gt_layout.addWidget(self.refresh_btn)

        content_layout.addWidget(global_toolbar)

        self.music_tab = MusicTab()
        self.music_tab.status_message.connect(self._set_status)
        self.tabs.addTab(self.music_tab, "Music")

        self.photos_tab = PhotosTab()
        self.photos_tab.status_message.connect(self._set_status)
        self.tabs.addTab(self.photos_tab, "Photos")

        self.my_computer_tab = MyComputerTab()
        self.my_computer_tab.status_message.connect(self._set_status)
        self.tabs.addTab(self.my_computer_tab, "My Computer")

        # Playlists — styled coming soon card
        self.tabs.addTab(self._make_coming_soon_tab(
            "📋", "Playlist Manager",
            "Create, edit, and sync playlists between your iPhone and Linux.\n\n"
            "Reads M3U and iPhone native playlists. Drag and drop to reorder. "
            "Export playlists as M3U files.\n\nComing in Phase 2.",
        ), "Playlists")

        # Device Tools
        self.device_tools_tab = DeviceToolsTab()
        self.device_tools_tab.status_message.connect(self._set_status)
        self.tabs.addTab(self.device_tools_tab, "Device Tools")

        # Backup & Restore — styled coming soon card
        self.tabs.addTab(self._make_coming_soon_tab(
            "💾", "Backup & Restore",
            "Full device backup and restore via idevicebackup2.\n\n"
            "Encrypted backup support, backup browser, diff viewer, "
            "and scheduled automatic backups.\n\nComing in Phase 3.",
        ), "Backup & Restore")
        content_layout.addWidget(self.tabs)

        # Player bar — sits between tab content and status bar
        self.player_bar = PlayerBar()
        content_layout.addWidget(self.player_bar)

        main_layout.addWidget(content)

        # Give tabs a reference to the player
        self.music_tab.set_player(self.player_bar)
        self.my_computer_tab.set_player(self.player_bar)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready — connect your iPhone to begin")

    def _start_device_polling(self):
        # Use a QObject with signals to safely bridge background thread → main thread
        class _Bridge(QObject):
            connected = Signal(object)
            disconnected = Signal()

        self._bridge = _Bridge()
        self._bridge.connected.connect(self._on_device_connected)
        self._bridge.disconnected.connect(self._on_device_disconnected)

        self._dev_manager.set_callbacks(
            on_connected=self._bridge.connected.emit,
            on_disconnected=self._bridge.disconnected.emit,
        )
        self._dev_manager.start_polling(interval=3.0)

    def _on_device_connected(self, device: DeviceInfo):
        self._update_device_ui(device)

    def _update_device_ui(self, device: DeviceInfo):
        self.device_name.setText(device.name)
        self.device_ios.setText(f"iOS {device.ios_version}  •  {device.model_name}")
        self.storage_bar.set_usage(device.used_percent)
        self.storage_info.setText(f"{device.used_gb} GB used of {device.capacity_gb} GB")
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Mount Device")
        self.status_dot.setText("● Connected")
        self.status_dot.setStyleSheet(f"color: {SUCCESS}; font-size: 10px; padding: 8px 16px; background: transparent;")
        self._set_status(f"{device.name} detected — click 'Mount Device' to browse")

    def _on_device_disconnected(self):
        self._clear_device_ui()

    def _clear_device_ui(self):
        # DeviceManager owns the real mount state (self._dev_manager.mount_dir);
        # _current_mount here is just a transitional mirror of it for the UI,
        # kept in sync at every mount/unmount site. unmount_current() is
        # idempotent, so this is safe even if nothing is actually mounted.
        self._dev_manager.unmount_current()
        self._current_mount = None
        self.my_computer_tab.set_mount_point(None) if hasattr(self, "my_computer_tab") else None
        self.device_tools_tab.set_mount_point(None) if hasattr(self, "device_tools_tab") else None
        self.device_name.setText("No Device")
        self.device_ios.setText("Connect your iPhone")
        self.storage_bar.set_usage(0)
        self.storage_info.setText("")
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Mount Device")
        self.status_dot.setText("● Not Connected")
        self.status_dot.setStyleSheet(f"color: {DANGER}; font-size: 10px; padding: 8px 16px; background: transparent;")
        self._set_status("Device disconnected")

    def _mount_device(self):
        device = self._dev_manager.device
        if not device:
            return
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Mounting...")
        self._set_status("Mounting iPhone filesystem...")

        mount = self._dev_manager.mount_media()
        if mount:
            self._current_mount = mount
            device.mount_point = mount
            self.connect_btn.setText("Mounted ✓")
            self._set_status(f"Mounted at {mount} — scanning library...")

            # Read storage from mount — ideviceinfo storage keys unavailable on iOS 26+
            capacity, used = self._dev_manager.storage_from_mount(mount)
            if capacity > 0:
                device.capacity_bytes = capacity
                device.used_bytes = used
                self.storage_bar.set_usage(device.used_percent)
                self.storage_info.setText(
                    f"{device.used_gb} GB used of {device.capacity_gb} GB"
                )

            self.my_computer_tab.set_mount_point(mount)
            self.device_tools_tab.set_mount_point(mount)
            self.music_tab.load_from_mount(mount)
            self.photos_tab.load_from_mount(mount)
        else:
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Mount Device")
            QMessageBox.warning(
                self, "Mount Failed",
                "Could not mount the iPhone.\n\n"
                "Make sure you have tapped 'Trust' on your iPhone when prompted, "
                "and that ifuse is installed.\n\n"
                "Try: sudo apt install ifuse"
            )

    def _make_coming_soon_tab(self, icon: str, title: str, desc: str) -> QWidget:
        """Build a polished 'coming soon' tab card."""
        outer = QWidget()
        outer.setStyleSheet(f"background: {DARK_BG};")
        ol = QVBoxLayout(outer)
        ol.setAlignment(Qt.AlignCenter)
        ol.setContentsMargins(40, 40, 40, 40)

        card = QFrame()
        card.setMinimumWidth(360)
        card.setMaximumWidth(500)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        card.setStyleSheet(
            f"QFrame {{ background: {CARD_BG}; border: 1px solid {BORDER}; "
            f"border-radius: 12px; }}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 28, 32, 28)
        cl.setSpacing(12)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(
            "font-size: 36px; background: transparent; border: none;"
        )
        icon_lbl.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {TEXT_PRIMARY}; "
            f"background: transparent; border: none;"
        )
        title_lbl.setAlignment(Qt.AlignCenter)

        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(
            f"font-size: 12px; color: {TEXT_SECONDARY}; "
            f"background: transparent; border: none;"
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setAlignment(Qt.AlignCenter)

        cl.addWidget(icon_lbl)
        cl.addWidget(title_lbl)
        cl.addWidget(desc_lbl)
        ol.addWidget(card)
        return outer

    def _set_status(self, msg: str):
        self.status_bar.showMessage(msg)

    def _refresh_library(self):
        """Re-scan current tab content without remounting."""
        current = self.tabs.currentIndex()
        if current == 0:
            self.music_tab.refresh()
            self._set_status("Refreshing music library...")
        elif current == 1:
            self.photos_tab.refresh()
            self._set_status("Refreshing photo library...")
        else:
            self._set_status("Refresh available on Music and Photos tabs")

    # Bound on how long "Quit anyway" waits for an in-flight transfer to
    # actually stop after being cancelled, before refusing to close rather
    # than risk unmounting mid-write. Not a substitute for the cancellation
    # mechanism itself — see TransferEngine.cancel()/join() — just a ceiling
    # on how long the user waits for a well-behaved cancel to land.
    _CLOSE_CANCEL_JOIN_TIMEOUT = 10.0

    def _active_transfer_tab_names(self) -> List[str]:
        """
        Tabs with a TransferEngine still mid-copy, via each tab's public
        is_transfer_active() state. Used to decide whether it's safe to
        unmount and exit.
        """
        active = []
        if self.music_tab.is_transfer_active():
            active.append("Music")
        if self.my_computer_tab.is_transfer_active():
            active.append("My Computer")
        return active

    def _cancel_and_wait_for_active_transfers(self) -> bool:
        """
        Request cancellation on every tab's TransferEngine and wait for
        each worker to actually stop. Returns True only if every engine
        genuinely reached a stopped state — the caller must not proceed to
        unmount unless this is True, since cancel() alone only requests
        the stop and does not confirm a write already in flight has
        actually ended.
        """
        engines = [self.music_tab._transfer, self.my_computer_tab._transfer]
        for engine in engines:
            if engine.is_running:
                engine.cancel()
        return all(
            engine.join(timeout=self._CLOSE_CANCEL_JOIN_TIMEOUT)
            for engine in engines
        )

    def closeEvent(self, event):
        active = self._active_transfer_tab_names()
        if active:
            reply = QMessageBox.warning(
                self,
                "Transfer In Progress",
                "A file transfer is still in progress ({}).\n\n"
                "Closing now would tear down the iPhone mount while a file "
                "is still being written, which can leave a truncated file "
                "on the device.\n\n"
                "Quit anyway? MoTunes will cancel the transfer safely "
                "first — the file being written when you confirm will not "
                "be completed.".format(", ".join(active)),
                QMessageBox.Cancel | QMessageBox.Yes,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

            # The user confirmed, but that is not itself permission to tear
            # the mount out from under a write in progress — only a
            # confirmed-stopped worker earns that. If cancellation can't be
            # confirmed within the timeout, stay open rather than guess.
            if not self._cancel_and_wait_for_active_transfers():
                QMessageBox.warning(
                    self, "Still Finishing",
                    "MoTunes could not confirm the in-progress transfer "
                    "stopped safely in time, so it's staying open rather "
                    "than risk corrupting a file on your iPhone. Please "
                    "wait a moment and try closing again.",
                )
                event.ignore()
                return

        self._dev_manager.stop_polling()
        # DeviceManager owns the real mount state; unmount_current() is
        # idempotent, so this is safe even if nothing is actually mounted.
        self._dev_manager.unmount_current()
        self._current_mount = None
        self.player_bar.cleanup()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("MoTunes")
    app.setOrganizationName("Mo Thugs South")

    # Enable HiDPI
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

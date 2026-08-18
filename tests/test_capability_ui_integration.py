"""
Regression coverage for Phase 0B Slice 2, spec items 11, 12, and 16,
exercised through the real UI entry points (PhotosTab, MusicTab,
MyComputerTab, TagEditorDialog) rather than the engines directly —
proving the wiring from set_capability_provider() through to each
concrete write surface, not just that the engines/worker can be gated
in isolation (see test_capability_write_gating.py for that).
"""
import os
import threading
import unittest.mock

import pytest
from PySide6.QtWidgets import QMessageBox

from core.capability import CapabilityDecision, RuntimeCapability, WritePolicy
from core.music import Track
from core.photos import Photo
from core.transfer import TransferDirection
from ui.main_window import MusicTab, PhotosTab, MyComputerTab, TagEditorDialog


def _decision(write_policy: WritePolicy, reason="test") -> CapabilityDecision:
    return CapabilityDecision(
        capability=RuntimeCapability(
            ifuse_present=True, ifuse_version=(1, 1, 3), ifuse_version_raw="ifuse 1.1.3",
            idevice_id_present=True, ideviceinfo_present=True, unmount_binary="fusermount3",
        ),
        write_policy=write_policy,
        reason=reason,
    )


READ_ONLY = _decision(WritePolicy.READ_ONLY_LEGACY, reason="Legacy ifuse — writes disabled precaution")
WRITE_ENABLED = _decision(WritePolicy.WRITE_ENABLED, reason="Compatible ifuse version detected.")


def _confirm_yes(*a, **kw):
    return QMessageBox.Yes


def _photo(path, is_video=False) -> Photo:
    return Photo(path=str(path), filename=os.path.basename(str(path)), is_video=is_video)


# ── 11. Read-only mode still permits an iPhone → local export ───────────────

def test_photos_export_selected_works_under_read_only_policy(qapp, monkeypatch, tmp_path):
    f = tmp_path / "IMG_0001.HEIC"
    f.write_bytes(b"x" * 4096)
    tab = PhotosTab()
    tab.set_capability_provider(lambda: READ_ONLY)
    tab._on_scan_complete([_photo(f)])
    tab.photo_grid.select_all()
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(tmp_path / "out"),
    )

    tab._export_selected()
    assert tab._transfer.join(timeout=5)

    exported = tmp_path / "out" / "IMG_0001.HEIC"
    assert exported.exists(), "export (a read from the device) must work under read-only policy"


def test_music_export_selected_works_under_read_only_policy(qapp, monkeypatch, tmp_path):
    f = tmp_path / "song.mp3"
    f.write_bytes(b"x" * 2048)
    tab = MusicTab()
    tab.set_capability_provider(lambda: READ_ONLY)
    track = Track(path=str(f), filename="song.mp3", title="T", artist="A", tags_loaded=True)
    tab._all_tracks = [track]
    tab._populate_table([track])
    tab.table.selectRow(0)
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(tmp_path / "out"),
    )

    tab._export_selected()
    assert tab._transfer.join(timeout=5)
    assert any((tmp_path / "out").glob("*.mp3")), "music export must work under read-only policy"


# ── 12. Read-only mode refuses every discovered device-write surface ────────

def test_photos_delete_refused_under_read_only_policy(qapp, monkeypatch, tmp_path):
    f = tmp_path / "IMG_0002.HEIC"
    f.write_bytes(b"x")
    tab = PhotosTab()
    tab.set_capability_provider(lambda: READ_ONLY)
    tab._on_scan_complete([_photo(f)])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    questions_asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: questions_asked.append(1) or QMessageBox.Yes)

    remove_calls = []
    with unittest.mock.patch("core.photos.os.remove", side_effect=lambda p: remove_calls.append(p)):
        tab._delete_selected()

    assert tab._delete_worker.is_running is False
    assert remove_calls == []
    assert questions_asked == [], "must refuse before even asking the user to confirm deletion"
    assert f.exists()


def test_music_add_tracks_refused_under_read_only_policy(qapp, monkeypatch, tmp_path):
    tab = MusicTab()
    tab.set_capability_provider(lambda: READ_ONLY)
    tab._mount_point = str(tmp_path)

    dialog_opened = {"count": 0}

    def track_dialog(*a, **kw):
        dialog_opened["count"] += 1
        return ([], "")

    monkeypatch.setattr("ui.main_window.QFileDialog.getOpenFileNames", track_dialog)
    messages = []
    tab.status_message.connect(messages.append)

    tab._add_tracks()

    assert dialog_opened["count"] == 0, "must refuse before even opening the file picker"
    assert any("cannot send" in m.lower() or "read" in m.lower() or "legacy" in m.lower() for m in messages)


def test_my_computer_transfer_selected_refused_under_read_only_policy(qapp, tmp_path):
    f = tmp_path / "local.mp3"
    f.write_bytes(b"x")
    tab = MyComputerTab()
    tab.set_capability_provider(lambda: READ_ONLY)
    tab._mount_point = str(tmp_path)  # "mounted" so the mount-check doesn't short-circuit first
    tab._navigate(str(tmp_path))
    tab.file_table.selectAll()

    messages = []
    tab.status_message.connect(messages.append)
    queue_before = list(tab._transfer.queue)

    tab._transfer_selected()

    assert list(tab._transfer.queue) == queue_before == []
    assert messages, "a refusal reason must be reported"


def test_tag_editor_save_refused_under_read_only_policy(qapp, monkeypatch, tmp_path):
    f = tmp_path / "song.mp3"
    f.write_bytes(b"not really an mp3")
    track = Track(path=str(f), filename="song.mp3", title="Old Title", tags_loaded=True)
    # The refusal path shows a real QMessageBox.warning() — under offscreen
    # Qt with no user to click it, an unmocked call here hangs the test.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Ok)

    dlg = TagEditorDialog(track, can_write=lambda: False)
    with unittest.mock.patch.object(dlg, "_save_mp3") as mock_save_mp3, \
         unittest.mock.patch.object(dlg, "_save_mutagen") as mock_save_mutagen:
        dlg._save()
        mock_save_mp3.assert_not_called()
        mock_save_mutagen.assert_not_called()

    assert dlg.saved is False
    assert f.read_bytes() == b"not really an mp3", "the file on the mounted device must not be touched"


def test_tag_editor_save_proceeds_when_writes_allowed(qapp, tmp_path):
    """Sanity check for the gate itself — a permissive predicate must not
    block the save path (the real save is exercised by pre-existing
    tag-editing behavior; here we only prove the gate isn't inverted)."""
    f = tmp_path / "song.mp3"
    f.write_bytes(b"x")
    track = Track(path=str(f), filename="song.mp3", title="T", tags_loaded=True)

    dlg = TagEditorDialog(track, can_write=lambda: True)
    with unittest.mock.patch.object(dlg, "_save_mp3") as mock_save_mp3:
        dlg._save()
        mock_save_mp3.assert_called_once()


# ── Known-bad 1.2.0: every write surface refused, same as read-only, plus no mount

def test_photos_delete_refused_under_known_corrupting_policy(qapp, tmp_path):
    f = tmp_path / "IMG_0003.HEIC"
    f.write_bytes(b"x")
    tab = PhotosTab()
    tab.set_capability_provider(lambda: _decision(WritePolicy.BLOCKED_KNOWN_CORRUPTING))
    tab._on_scan_complete([_photo(f)])
    tab.photo_grid.select_all()

    remove_calls = []
    with unittest.mock.patch("core.photos.os.remove", side_effect=lambda p: remove_calls.append(p)):
        tab._delete_selected()

    assert remove_calls == []
    assert f.exists()


# ── 16. Compatible/write-enabled mode preserves existing successful behavior

def test_photos_delete_succeeds_under_write_enabled_policy(qapp, monkeypatch, tmp_path):
    f = tmp_path / "IMG_0004.HEIC"
    f.write_bytes(b"x")
    tab = PhotosTab()
    tab.set_capability_provider(lambda: WRITE_ENABLED)
    tab._on_scan_complete([_photo(f)])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)

    tab._delete_selected()
    assert tab._delete_worker.join(timeout=5)

    from PySide6.QtCore import QCoreApplication
    for _ in range(200):
        QCoreApplication.processEvents()

    assert not f.exists(), "write-enabled policy must preserve the pre-existing delete behavior"


def test_music_add_tracks_reaches_file_picker_under_write_enabled_policy(qapp, monkeypatch, tmp_path):
    tab = MusicTab()
    tab.set_capability_provider(lambda: WRITE_ENABLED)
    tab._mount_point = str(tmp_path)

    dialog_opened = {"count": 0}

    def track_dialog(*a, **kw):
        dialog_opened["count"] += 1
        return ([], "")

    monkeypatch.setattr("ui.main_window.find_vlc_iphone_path", lambda mount: str(tmp_path))
    monkeypatch.setattr("ui.main_window.QFileDialog.getOpenFileNames", track_dialog)

    tab._add_tracks()

    assert dialog_opened["count"] == 1, "write-enabled policy must reach the same code path as before this slice"

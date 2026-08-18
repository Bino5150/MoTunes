"""
Regression coverage for Finding C (Phase 0B slice 1) through the real
PhotosTab export/delete flow: a Live Photo still and its paired .MOV
motion component must behave as one logical asset, even though the
companion is deliberately excluded from both visible grids (it's only
ever reachable via find_live_photo_companion()).

Fixtures covered: still+paired MOV export, still+paired MOV delete,
companion-delete failure, an ordinary standalone still, and an ordinary
standalone video — proving the pairing logic only ever engages for actual
Live Photo pairs and leaves everything else exactly as before.
"""
import unittest.mock

from PySide6.QtWidgets import QMessageBox

from core.photos import Photo
from ui.main_window import PhotosTab


def _confirm_yes(*a, **kw):
    return QMessageBox.Yes


def _make_pair(tmp_path, stem="IMG_0001"):
    still_f = tmp_path / f"{stem}.HEIC"
    mov_f = tmp_path / f"{stem}.MOV"
    still_f.write_bytes(b"still-bytes")
    mov_f.write_bytes(b"motion-bytes")
    still = Photo(path=str(still_f), filename=f"{stem}.HEIC")
    companion = Photo(path=str(mov_f), filename=f"{stem}.MOV", is_video=True, is_live_photo=True)
    return still_f, mov_f, still, companion


# ── Fixture: still + paired MOV export ───────────────────────────────────────

def test_live_photo_export_includes_still_and_companion(qapp, monkeypatch, tmp_path):
    still_f, mov_f, still, companion = _make_pair(tmp_path)

    tab = PhotosTab()
    tab._on_scan_complete([still, companion])

    # The companion must never appear as a directly selectable grid item.
    assert [p.path for p in tab.photo_grid.all_photos] == [still.path]
    assert companion.path not in [p.path for p in tab.video_grid.all_photos]

    tab.photo_grid.select_all()
    dest_dir = tmp_path / "out"
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(dest_dir),
    )

    status_messages = []
    tab.status_message.connect(status_messages.append)

    tab._export_selected()
    assert tab._transfer.join(timeout=5)

    exported_sources = {j.source for j in tab._transfer.queue}
    assert str(still_f) in exported_sources, "the selected still must be exported"
    assert str(mov_f) in exported_sources, "the paired motion component must travel with it"
    # Selection is counted in user-visible terms: 1 item selected, even
    # though 2 files were queued underneath.
    assert any("Exporting 1 item" in m for m in status_messages)


# ── Fixture: still + paired MOV delete ───────────────────────────────────────

def test_live_photo_delete_removes_both_motion_component_first(qapp, monkeypatch, tmp_path):
    still_f, mov_f, still, companion = _make_pair(tmp_path)

    tab = PhotosTab()
    tab._on_scan_complete([still, companion])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)

    delete_order = []
    orig_remove = __import__("os").remove

    def tracking_remove(path):
        delete_order.append(path)
        orig_remove(path)

    with unittest.mock.patch("core.photos.os.remove", side_effect=tracking_remove):
        tab._delete_selected()
        assert tab._delete_worker.join(timeout=5)

    from PySide6.QtCore import QCoreApplication
    for _ in range(200):
        QCoreApplication.processEvents()

    assert delete_order == [str(mov_f), str(still_f)], "motion component must be deleted before the still"
    assert not still_f.exists()
    assert not mov_f.exists()
    remaining_paths = {p.path for p in tab._all_media}
    assert still.path not in remaining_paths
    assert companion.path not in remaining_paths


def test_live_photo_delete_confirmation_counts_one_user_visible_item(qapp, monkeypatch, tmp_path):
    """Count UI selections in terms users understand — selecting one Live
    Photo still must ask to delete "1 item", not 2."""
    still_f, mov_f, still, companion = _make_pair(tmp_path)

    tab = PhotosTab()
    tab._on_scan_complete([still, companion])
    tab.photo_grid.select_all()

    questions = []

    def capture_question(parent, title, text, *a, **kw):
        questions.append(text)
        return QMessageBox.Cancel  # decline — we only care what was asked

    monkeypatch.setattr(QMessageBox, "question", capture_question)
    tab._delete_selected()

    assert questions
    assert "1 item" in questions[0]


# ── Fixture: companion-delete failure ────────────────────────────────────────

def test_live_photo_companion_delete_failure_leaves_still_and_reports_it(qapp, monkeypatch, tmp_path):
    still_f = tmp_path / "IMG_0002.HEIC"
    still_f.write_bytes(b"x")
    still = Photo(path=str(still_f), filename="IMG_0002.HEIC")
    # Companion has no backing file on disk — its delete will fail.
    companion = Photo(path=str(tmp_path / "IMG_0002.MOV"), filename="IMG_0002.MOV",
                       is_video=True, is_live_photo=True)

    tab = PhotosTab()
    tab._on_scan_complete([still, companion])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: warnings.append(a) or QMessageBox.Ok)

    tab._delete_selected()
    assert tab._delete_worker.join(timeout=5)

    from PySide6.QtCore import QCoreApplication
    for _ in range(200):
        QCoreApplication.processEvents()

    assert still_f.exists(), "still must not be deleted when the companion delete failed"
    remaining_paths = {p.path for p in tab._all_media}
    assert still.path in remaining_paths, "the pair must remain visible — not reported as cleanly removed"
    assert warnings, "the failure must be surfaced to the user"


# ── Fixture: ordinary standalone still ───────────────────────────────────────

def test_ordinary_still_export_and_delete_are_single_file_operations(qapp, monkeypatch, tmp_path):
    f = tmp_path / "IMG_0099.HEIC"
    f.write_bytes(b"x")
    photo = Photo(path=str(f), filename="IMG_0099.HEIC")

    tab = PhotosTab()
    tab._on_scan_complete([photo])
    tab.photo_grid.select_all()

    dest_dir = tmp_path / "out"
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(dest_dir),
    )
    tab._export_selected()
    assert tab._transfer.join(timeout=5)
    assert [j.source for j in tab._transfer.queue] == [str(f)]

    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    tab.photo_grid.select_all()
    tab._delete_selected()
    assert tab._delete_worker.join(timeout=5)
    assert not f.exists()


# ── Fixture: ordinary standalone video ───────────────────────────────────────

def test_ordinary_video_export_and_delete_are_single_file_operations(qapp, monkeypatch, tmp_path):
    f = tmp_path / "IMG_0100.MOV"
    f.write_bytes(b"x")
    video = Photo(path=str(f), filename="IMG_0100.MOV", is_video=True, is_live_photo=False)

    tab = PhotosTab()
    tab._on_scan_complete([video])
    assert [p.path for p in tab.video_grid.all_photos] == [video.path]

    tab.sub_tabs.setCurrentIndex(1)  # Videos sub-tab — _current_grid() follows this, not which grid was touched
    tab.video_grid.select_all()
    dest_dir = tmp_path / "out"
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(dest_dir),
    )
    tab._export_selected()
    assert tab._transfer.join(timeout=5)
    assert [j.source for j in tab._transfer.queue] == [str(f)], (
        "an ordinary video must never trigger a companion lookup"
    )

    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    tab.video_grid.select_all()
    tab._delete_selected()
    assert tab._delete_worker.join(timeout=5)
    assert not f.exists()

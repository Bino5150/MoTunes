"""
Regression coverage for the media-operation exclusion policy added after
checkpoint review of Phase 0B slice 1: export and delete each guarded only
against a second instance of *themselves* — nothing stopped a delete from
starting while an export was mid-copy, or vice versa, even though both
operate on the same on-device files with zero coordination between the two
worker classes (TransferEngine, PhotoDeleteWorker).

is_media_operation_active() is now the single predicate every entry point
(_export_all, _export_selected, _delete_selected) checks before starting
anything, backed by a real worker thread in every test here — not just a
flag flip — so these prove an operation genuinely cannot begin while the
other's os.remove()/TransferEngine.start() is actually in flight.
"""
import threading
import unittest.mock

from PySide6.QtWidgets import QMessageBox

from core.photos import Photo
from core.transfer import TransferStatus
from ui.main_window import PhotosTab


def _photo(path, is_video=False, is_live_photo=False) -> Photo:
    import os
    return Photo(path=str(path), filename=os.path.basename(str(path)),
                 is_video=is_video, is_live_photo=is_live_photo)


def _confirm_yes(*a, **kw):
    return QMessageBox.Yes


def test_delete_cannot_begin_while_export_is_active(qapp, monkeypatch, tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"x" * 4096)
    tab = PhotosTab()
    tab._on_scan_complete([_photo(f)])
    tab.photo_grid.select_all()

    hold = threading.Event()
    entered = threading.Event()

    def on_job_progress(job):
        entered.set()
        hold.wait(timeout=5)

    tab._transfer._chunk_size = 1
    tab._transfer.set_callbacks(
        on_job_progress=on_job_progress,
        on_all_complete=tab._transfer_bridge.all_complete.emit,
    )
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(tmp_path / "out"),
    )

    tab._export_selected()
    assert entered.wait(timeout=5)
    assert tab._transfer.is_running is True

    # Now try to delete while that real export worker is mid-copy.
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    status_messages = []
    tab.status_message.connect(status_messages.append)

    remove_calls = []
    with unittest.mock.patch("core.photos.os.remove", side_effect=lambda p: remove_calls.append(p)):
        tab._delete_selected()

    assert tab._delete_worker.is_running is False, "delete must not have started while export is active"
    assert remove_calls == [], "refused delete path must perform no os.remove"
    assert any("export" in m.lower() and "progress" in m.lower() for m in status_messages), (
        "refusal message must truthfully name the export as the reason"
    )

    hold.set()
    assert tab._transfer.join(timeout=5)


def test_export_cannot_begin_while_delete_is_active(qapp, monkeypatch, tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"x")
    tab = PhotosTab()
    tab._on_scan_complete([_photo(f)])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)

    hold = threading.Event()
    entered = threading.Event()
    orig_remove = __import__("os").remove

    def blocking_remove(path):
        entered.set()
        hold.wait(timeout=5)
        orig_remove(path)

    with unittest.mock.patch("core.photos.os.remove", side_effect=blocking_remove):
        tab._delete_selected()
        assert entered.wait(timeout=5)
        assert tab._delete_worker.is_running is True

        # Now try to export while that real delete worker is mid-operation.
        monkeypatch.setattr(
            "ui.main_window.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(tmp_path / "out"),
        )
        status_messages = []
        tab.status_message.connect(status_messages.append)

        queue_before = list(tab._transfer.queue)
        tab._export_selected()

        assert tab._transfer.is_running is False, "export must not have started while delete is active"
        assert list(tab._transfer.queue) == queue_before == [], (
            "refused export path must add/start no transfer jobs"
        )
        assert any("delete" in m.lower() and "progress" in m.lower() for m in status_messages), (
            "refusal message must truthfully name the delete as the reason"
        )

        hold.set()
        assert tab._delete_worker.join(timeout=5)


def test_export_all_also_refused_while_delete_active(qapp, monkeypatch, tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"x")
    tab = PhotosTab()
    tab._on_scan_complete([_photo(f)])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)

    hold = threading.Event()
    entered = threading.Event()
    orig_remove = __import__("os").remove

    def blocking_remove(path):
        entered.set()
        hold.wait(timeout=5)
        orig_remove(path)

    with unittest.mock.patch("core.photos.os.remove", side_effect=blocking_remove):
        tab._delete_selected()
        assert entered.wait(timeout=5)

        dialog_opened = {"count": 0}

        def track_dialog(*a, **kw):
            dialog_opened["count"] += 1
            return str(tmp_path / "out")

        monkeypatch.setattr("ui.main_window.QFileDialog.getExistingDirectory", track_dialog)
        tab._export_all()

        assert dialog_opened["count"] == 0, "the guard must return before even opening the destination dialog"
        assert tab._transfer.is_running is False

        hold.set()
        assert tab._delete_worker.join(timeout=5)


def test_is_media_operation_active_reflects_either_worker(qapp, monkeypatch, tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"x" * 4096)
    tab = PhotosTab()
    tab._on_scan_complete([_photo(f)])

    assert tab.is_media_operation_active() is False

    hold = threading.Event()
    entered = threading.Event()

    def on_job_progress(job):
        entered.set()
        hold.wait(timeout=5)

    tab._transfer._chunk_size = 1
    tab._transfer.set_callbacks(
        on_job_progress=on_job_progress,
        on_all_complete=tab._transfer_bridge.all_complete.emit,
    )
    tab.photo_grid.select_all()
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(tmp_path / "out"),
    )
    tab._export_selected()
    assert entered.wait(timeout=5)
    assert tab.is_media_operation_active() is True

    hold.set()
    assert tab._transfer.join(timeout=5)
    assert tab.is_media_operation_active() is False


def test_export_completion_distinguishes_success_from_failure(qapp, monkeypatch, tmp_path):
    """
    "Complete" in the user-visible status must not mean "some jobs failed
    but the worker stopped" — a mixed batch (one success, one failure)
    must report the failure honestly, never the plain success message.
    """
    good_f = tmp_path / "good.jpg"
    good_f.write_bytes(b"x")
    good = _photo(good_f)
    missing = _photo(tmp_path / "missing.jpg")  # no backing file — job will FAIL

    tab = PhotosTab()
    tab._on_scan_complete([good, missing])
    tab.photo_grid.select_all()
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(tmp_path / "out"),
    )

    status_messages = []
    tab.status_message.connect(status_messages.append)

    tab._export_selected()
    assert tab._transfer.join(timeout=5)

    from PySide6.QtCore import QCoreApplication
    for _ in range(200):
        QCoreApplication.processEvents()

    statuses = {j.status for j in tab._transfer.queue}
    assert TransferStatus.FAILED in statuses
    assert TransferStatus.COMPLETE in statuses

    final_message = status_messages[-1]
    assert final_message != "Export complete!", (
        "a batch with a failed job must never be reported as unqualified success"
    )
    assert "fail" in final_message.lower()

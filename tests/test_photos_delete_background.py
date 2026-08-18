"""
Regression coverage for Finding B (Phase 0B slice 1): PhotoGrid.delete_selected()
used to call os.remove() directly on the Qt main thread, synchronously, as
part of a QPushButton click handler — freezing the UI for the duration and
giving PhotosTab no way to report partial failure accurately or participate
in shutdown/unmount protection.

Deletion is now a PhotoDeleteWorker background operation owned by
PhotosTab, wired through _PhotoDeleteBridge the same way TransferEngine
uses _TransferBridge. All file operations happen against real temp files.
"""
import threading
import time
import unittest.mock

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from core.photos import Photo
from ui.main_window import MainWindow, PhotosTab, _PhotoDeleteBridge


def _photo(path, is_video=False, is_live_photo=False) -> Photo:
    import os
    return Photo(path=str(path), filename=os.path.basename(str(path)),
                 is_video=is_video, is_live_photo=is_live_photo)


def _confirm_yes(*a, **kw):
    return QMessageBox.Yes


def _pump(iterations=200):
    for _ in range(iterations):
        QCoreApplication.processEvents()


def test_photos_tab_owns_a_persistent_delete_worker(qapp):
    tab = PhotosTab()
    assert hasattr(tab, "_delete_worker")
    assert hasattr(tab, "_delete_bridge")
    assert isinstance(tab._delete_bridge, _PhotoDeleteBridge)
    assert tab._delete_worker._on_result == tab._delete_bridge.result.emit
    assert tab._delete_worker._on_all_complete == tab._delete_bridge.all_complete.emit


def test_delete_does_not_call_os_remove_on_the_qt_main_thread(qapp, monkeypatch, tmp_path):
    f = tmp_path / "IMG_0001.JPG"
    f.write_bytes(b"x")
    photo = _photo(f)

    tab = PhotosTab()
    tab._on_scan_complete([photo])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)

    main_thread = threading.current_thread()
    remove_thread_holder = {}
    orig_remove = __import__("os").remove

    def tracking_remove(path):
        remove_thread_holder["thread"] = threading.current_thread()
        orig_remove(path)

    with unittest.mock.patch("core.photos.os.remove", side_effect=tracking_remove):
        tab._delete_selected()
        assert tab._delete_worker.join(timeout=5)

    assert remove_thread_holder["thread"] is not main_thread, (
        "os.remove() must run on a background thread, not the Qt main thread"
    )


def test_delete_completion_reaches_ui_through_qt_signals(qapp, monkeypatch, tmp_path):
    f = tmp_path / "IMG_0001.JPG"
    f.write_bytes(b"x")
    photo = _photo(f)

    tab = PhotosTab()
    tab._on_scan_complete([photo])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)

    tab._delete_selected()
    assert tab._delete_worker.join(timeout=5)
    _pump()  # let the queued signals actually reach the main-thread slots

    assert f.exists() is False
    assert len(tab._all_media) == 0, "confirmed-deleted item must be gone from _all_media once signals are processed"


def test_ui_not_updated_until_delete_results_are_known(qapp, monkeypatch, tmp_path):
    """No item is removed from the UI merely because deletion was
    attempted — it must still be visible while the worker is mid-flight."""
    f = tmp_path / "IMG_0001.JPG"
    f.write_bytes(b"x")
    photo = _photo(f)

    tab = PhotosTab()
    tab._on_scan_complete([photo])
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

        # Mid-flight: nothing confirmed yet, so the item must still be present.
        assert len(tab._all_media) == 1
        assert f.exists()

        hold.set()
        assert tab._delete_worker.join(timeout=5)

    _pump()
    assert len(tab._all_media) == 0
    assert not f.exists()


def test_partial_delete_failure_reported_accurately(qapp, monkeypatch, tmp_path):
    good_f = tmp_path / "good.jpg"
    good_f.write_bytes(b"x")
    good = _photo(good_f)
    # bad has no backing file, so os.remove() will fail for it
    bad = _photo(tmp_path / "missing.jpg")

    tab = PhotosTab()
    tab._on_scan_complete([good, bad])
    tab.photo_grid.select_all()
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: warnings.append(a) or QMessageBox.Ok)

    tab._delete_selected()
    assert tab._delete_worker.join(timeout=5)
    _pump()

    remaining_paths = {p.path for p in tab._all_media}
    assert str(good_f) not in remaining_paths, "successfully deleted item must be gone"
    assert bad.path in remaining_paths, "failed delete must remain visible, not silently dropped"
    assert not good_f.exists()
    assert warnings, "a partial failure must surface a warning to the user"


def test_starting_second_delete_while_active_is_refused_not_merged(qapp, monkeypatch, tmp_path):
    f1 = tmp_path / "a.jpg"
    f1.write_bytes(b"x")
    f2 = tmp_path / "b.jpg"
    f2.write_bytes(b"y")

    tab = PhotosTab()
    tab._on_scan_complete([_photo(f1), _photo(f2)])
    monkeypatch.setattr(QMessageBox, "question", _confirm_yes)

    hold = threading.Event()
    entered = threading.Event()
    orig_remove = __import__("os").remove

    def blocking_remove(path):
        entered.set()
        hold.wait(timeout=5)
        orig_remove(path)

    status_messages = []
    tab.status_message.connect(status_messages.append)

    with unittest.mock.patch("core.photos.os.remove", side_effect=blocking_remove):
        tab.photo_grid._single_select(0)
        tab._delete_selected()
        assert entered.wait(timeout=5)
        assert tab._delete_worker.is_running is True

        tab.photo_grid._single_select(1)
        tab._delete_selected()
        assert any("already in progress" in m for m in status_messages)

        hold.set()
        assert tab._delete_worker.join(timeout=5)


def test_delete_buttons_reflect_active_state(qapp, monkeypatch, tmp_path):
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

    assert tab.delete_btn.isEnabled() is True

    with unittest.mock.patch("core.photos.os.remove", side_effect=blocking_remove):
        tab._delete_selected()
        assert entered.wait(timeout=5)
        assert tab.delete_btn.isEnabled() is False, "delete button must reflect an active delete"
        hold.set()
        assert tab._delete_worker.join(timeout=5)

    _pump()
    assert tab.delete_btn.isEnabled() is False, "nothing selected after the deleted item disappears"


def test_delete_active_blocks_mainwindow_close_no_quit_anyway_bypass(qapp, monkeypatch, tmp_path):
    """
    Deletion has no cancel(), so there must be no "quit anyway" override —
    close must simply refuse while a delete is active, regardless of any
    button choice, and only proceed once the worker is confirmed finished.
    """
    window = MainWindow()
    try:
        f = tmp_path / "a.jpg"
        f.write_bytes(b"x")
        window.photos_tab._on_scan_complete([_photo(f)])
        window.photos_tab.photo_grid.select_all()
        monkeypatch.setattr(QMessageBox, "question", _confirm_yes)
        # The gate's "still active" message would otherwise be a real
        # blocking modal under offscreen Qt — nothing would ever click it.
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Ok)

        # Short join timeout so this test doesn't need to wait out the real
        # 10s production ceiling — hold.wait() below outlasts it by design,
        # so the gate is exercised for real rather than racing hold's own
        # timeout.
        monkeypatch.setattr(window, "_CLOSE_CANCEL_JOIN_TIMEOUT", 0.2)

        hold = threading.Event()
        entered = threading.Event()
        orig_remove = __import__("os").remove

        def blocking_remove(path):
            entered.set()
            hold.wait(timeout=30)
            orig_remove(path)

        with unittest.mock.patch("core.photos.os.remove", side_effect=blocking_remove):
            window.photos_tab._delete_selected()
            assert entered.wait(timeout=5)
            assert window.photos_tab.is_delete_active() is True

            unmount_calls = {"count": 0}
            with unittest.mock.patch.object(
                window._dev_manager, "unmount_current",
                side_effect=lambda: unmount_calls.__setitem__("count", unmount_calls["count"] + 1),
            ):
                event = QCloseEvent()
                window.closeEvent(event)

                assert event.isAccepted() is False
                assert unmount_calls["count"] == 0, "unmount must never be entered while delete is active"

            hold.set()
            assert window.photos_tab.wait_for_delete(timeout=5)
    finally:
        window.music_tab._transfer.cancel()
        window.my_computer_tab._transfer.cancel()
        window.photos_tab._transfer.cancel()

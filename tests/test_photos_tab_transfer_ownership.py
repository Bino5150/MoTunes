"""
Regression coverage for Finding A (Phase 0B slice 1): PhotosTab's
_export_all()/_export_selected() used to instantiate a local
TransferEngine() on every call and immediately lose all ownership of it —
no callbacks wired, no way for MainWindow to know an export was active, no
way to stop a second click from spawning an unrelated second worker.

PhotosTab now owns one persistent TransferEngine + _TransferBridge for its
whole lifetime, exactly mirroring the MusicTab/MyComputerTab pattern.
"""
import threading

from core.photos import Photo
from core.transfer import TransferDirection, TransferStatus
from ui.main_window import PhotosTab, MainWindow, _TransferBridge


def _make_photo(i: int, is_video=False) -> Photo:
    return Photo(path=f"/mnt/DCIM/100APPLE/IMG_{i:04d}.JPG", filename=f"IMG_{i:04d}.JPG",
                 is_video=is_video)


def test_photos_tab_owns_a_persistent_transfer_engine(qapp):
    tab = PhotosTab()
    assert hasattr(tab, "_transfer")
    assert hasattr(tab, "_transfer_bridge")
    assert isinstance(tab._transfer_bridge, _TransferBridge)
    assert tab._transfer._on_job_progress == tab._transfer_bridge.job_progress.emit
    assert tab._transfer._on_all_complete == tab._transfer_bridge.all_complete.emit


def test_export_selected_reuses_the_same_engine_across_calls(qapp, monkeypatch, tmp_path):
    """The engine object itself must not change between export calls —
    the old bug was a brand new TransferEngine() per click."""
    tab = PhotosTab()
    tab._on_scan_complete([_make_photo(1)])
    tab.photo_grid.select_all()

    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(tmp_path),
    )

    engine_before = tab._transfer
    tab._export_selected()
    assert tab._transfer is engine_before, "a new TransferEngine was created instead of reusing the owned one"

    # Let the (fast, tiny/nonexistent file) export finish before the next call.
    tab._transfer.join(timeout=5)
    tab.photo_grid.select_all()
    tab._export_selected()
    assert tab._transfer is engine_before


def test_starting_second_export_while_active_is_refused_not_merged(qapp, monkeypatch, tmp_path):
    """
    Requirement: starting another Photos export while one is already
    active must have deterministic behavior — no silently merging an
    accidental second UI batch into the running one.
    """
    tab = PhotosTab()
    src = tmp_path / "IMG_0001.JPG"
    src.write_bytes(b"x" * 4096)
    photo = Photo(path=str(src), filename="IMG_0001.JPG")
    tab._on_scan_complete([photo])

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

    dest_dir = tmp_path / "out"
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(dest_dir),
    )

    tab.photo_grid.select_all()
    tab._export_selected()
    assert entered.wait(timeout=5), "export never started"
    assert tab._transfer.is_running is True

    # A second click while the first is still running.
    status_messages = []
    tab.status_message.connect(status_messages.append)
    tab.photo_grid.select_all()
    tab._export_selected()

    assert any("already in progress" in m for m in status_messages), (
        "second export attempt must be refused with a clear message, not silently merged"
    )

    hold.set()
    assert tab._transfer.join(timeout=5)


def test_export_buttons_reflect_active_export_state(qapp, monkeypatch, tmp_path):
    tab = PhotosTab()
    src = tmp_path / "IMG_0001.JPG"
    src.write_bytes(b"x" * 4096)
    photo = Photo(path=str(src), filename="IMG_0001.JPG")
    tab._on_scan_complete([photo])

    hold = threading.Event()
    entered = threading.Event()
    tab._transfer._chunk_size = 1
    tab._transfer.set_callbacks(
        on_job_progress=lambda job: (entered.set(), hold.wait(timeout=5)),
        on_all_complete=tab._transfer_bridge.all_complete.emit,
    )
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getExistingDirectory",
        lambda *a, **kw: str(tmp_path / "out"),
    )

    tab.photo_grid.select_all()
    assert tab.export_all_btn.isEnabled() is True

    tab._export_selected()
    assert entered.wait(timeout=5)
    assert tab.export_all_btn.isEnabled() is False, "export buttons must reflect an active export"

    hold.set()
    assert tab._transfer.join(timeout=5)
    # Let the queued Qt signal (all_complete) actually reach the slot.
    from PySide6.QtCore import QCoreApplication
    for _ in range(200):
        QCoreApplication.processEvents()
        if tab.export_all_btn.isEnabled():
            break
    assert tab.export_all_btn.isEnabled() is True


def test_failed_export_job_remains_observable(qapp, monkeypatch, tmp_path):
    tab = PhotosTab()
    missing = Photo(path=str(tmp_path / "does_not_exist.jpg"), filename="does_not_exist.jpg")
    tab._on_scan_complete([missing])
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

    failed = [j for j in tab._transfer.queue if j.status == TransferStatus.FAILED]
    assert len(failed) == 1
    assert any("failed" in m.lower() for m in status_messages)


def test_photos_export_is_visible_to_mainwindow_close_guard(qapp, tmp_path):
    """
    A real Photos export worker must be visible to the close guard and
    the window must not be able to unmount out from under it.
    """
    window = MainWindow()
    try:
        engine = window.photos_tab._transfer
        hold = threading.Event()
        entered = threading.Event()

        def on_job_progress(job):
            entered.set()
            hold.wait(timeout=5)

        engine._chunk_size = 1
        engine.set_callbacks(
            on_job_progress=on_job_progress,
            on_all_complete=window.photos_tab._transfer_bridge.all_complete.emit,
        )

        src = tmp_path / "IMG_0001.JPG"
        src.write_bytes(b"x" * 4096)
        engine.add_job(str(src), str(tmp_path / "out" / "IMG_0001.JPG"), TransferDirection.FROM_DEVICE)
        engine.start()

        assert entered.wait(timeout=5)
        assert window._active_transfer_tab_names() == ["Photos"]

        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtGui import QCloseEvent
        import unittest.mock

        unmount_calls = {"count": 0}
        with unittest.mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes):
            with unittest.mock.patch.object(
                window._dev_manager, "unmount_current",
                side_effect=lambda: unmount_calls.__setitem__("count", unmount_calls["count"] + 1),
            ):
                def release_shortly():
                    import time
                    time.sleep(0.1)
                    hold.set()
                threading.Thread(target=release_shortly, daemon=True).start()

                event = QCloseEvent()
                window.closeEvent(event)

        assert engine.is_running is False, "engine must be confirmed stopped before unmount was allowed"
        assert unmount_calls["count"] == 1, "close should proceed once the export was confirmed cancelled/stopped"
    finally:
        window.music_tab._transfer.cancel()
        window.my_computer_tab._transfer.cancel()
        window.photos_tab._transfer.cancel()

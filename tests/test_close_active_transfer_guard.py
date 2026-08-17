"""
Regression coverage for Finding 9 / Slice E: closeEvent must not tear down
the mount while a transfer is active.

Exercises the real MainWindow.closeEvent decision logic — no real device is
involved; "active transfer" is simulated by flipping a TransferEngine's
internal _running flag directly (whitebox), and QMessageBox.warning is
monkeypatched so the test never blocks on a real modal dialog.

A checkpoint review of this slice found that the original "Quit anyway"
branch unmounted immediately on confirmation, with no coordination with the
worker thread at all — i.e. confirming the dialog during a real TO_DEVICE
write ("Add to iPhone"/"Send to iPhone") would tear the mount out from
under an in-flight write, exactly what Finding 9 was supposed to prevent.
The tests from test_quit_anyway_calls_cancel_and_join_before_unmounting
onward cover the fix: closeEvent must cancel + join before ever calling
unmount_current(), and must refuse to close (stay open) if that
confirmation doesn't arrive in time — "Quit anyway" is consent to cancel
the transfer, not a bypass of the safety check.
"""
import threading
import time

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from core.transfer import TransferDirection
from ui.main_window import MainWindow


def _make_window(qapp):
    window = MainWindow()
    # Background device polling isn't needed for this test and would just
    # add noise (subprocess calls to idevice_id every 3s); stop it, and
    # make sure it's stopped even if an assertion fails.
    window._dev_manager.stop_polling()
    return window


def test_close_is_blocked_while_music_transfer_active_and_unmount_not_entered(qapp, monkeypatch):
    window = _make_window(qapp)
    try:
        window.music_tab._transfer._running = True

        warned = {"called": False}

        def fake_warning(parent, title, text, buttons, default_button):
            warned["called"] = True
            return QMessageBox.Cancel  # least-destructive default: user cancels

        monkeypatch.setattr(QMessageBox, "warning", fake_warning)

        unmount_calls = {"count": 0}
        real_unmount = window._dev_manager.unmount_current

        def spy_unmount_current():
            unmount_calls["count"] += 1
            return real_unmount()

        monkeypatch.setattr(window._dev_manager, "unmount_current", spy_unmount_current)

        event = QCloseEvent()
        window.closeEvent(event)

        assert warned["called"] is True, "user must be warned before closing with an active transfer"
        assert unmount_calls["count"] == 0, (
            "unmount path must not be entered while an active transfer is protected"
        )
        assert event.isAccepted() is False, "close must be refused (event ignored) on Cancel"
    finally:
        window.music_tab._transfer._running = False


def test_close_is_blocked_while_my_computer_transfer_active(qapp, monkeypatch):
    window = _make_window(qapp)
    try:
        window.my_computer_tab._transfer._running = True
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Cancel)

        unmount_calls = {"count": 0}
        monkeypatch.setattr(
            window._dev_manager, "unmount_current",
            lambda: unmount_calls.__setitem__("count", unmount_calls["count"] + 1),
        )

        event = QCloseEvent()
        window.closeEvent(event)

        assert unmount_calls["count"] == 0
        assert event.isAccepted() is False
    finally:
        window.my_computer_tab._transfer._running = False


def test_close_proceeds_when_user_confirms_quit_anyway(qapp, monkeypatch):
    """
    No worker thread was ever actually started here (_running is set
    directly, whitebox) — so cancel()/join() no-op immediately since
    engine._thread is None, and this exercises only the "confirmed, and
    there was nothing left to actually wait for" leg. See
    test_quit_anyway_refuses_to_unmount_if_join_times_out below for the
    case that actually distinguishes the hardened behavior.
    """
    window = _make_window(qapp)
    try:
        window.music_tab._transfer._running = True
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Yes)

        unmount_calls = {"count": 0}
        real_unmount = window._dev_manager.unmount_current

        def spy_unmount_current():
            unmount_calls["count"] += 1
            return real_unmount()

        monkeypatch.setattr(window._dev_manager, "unmount_current", spy_unmount_current)

        event = QCloseEvent()
        window.closeEvent(event)

        assert unmount_calls["count"] == 1, "explicit confirmation must allow close to proceed"
        assert event.isAccepted() is True
    finally:
        window.music_tab._transfer._running = False


def test_quit_anyway_calls_cancel_and_join_before_unmounting(qapp, monkeypatch):
    """
    Confirming "Quit anyway" must cancel the active engine and confirm it
    stopped (join) strictly before unmount_current() is ever called — not
    unmount first and clean up after.
    """
    window = _make_window(qapp)
    try:
        window.music_tab._transfer._running = True
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Yes)

        call_order = []
        monkeypatch.setattr(window.music_tab._transfer, "cancel",
                             lambda: call_order.append("cancel"))
        monkeypatch.setattr(window.music_tab._transfer, "join",
                             lambda timeout=None: call_order.append("join") or True)
        monkeypatch.setattr(window._dev_manager, "unmount_current",
                             lambda: call_order.append("unmount"))

        event = QCloseEvent()
        window.closeEvent(event)

        assert "cancel" in call_order, "closeEvent must request cancellation"
        assert "join" in call_order, "closeEvent must confirm the worker actually stopped"
        assert call_order.index("cancel") < call_order.index("join") < call_order.index("unmount"), (
            f"unmount must only follow a confirmed cancel+join, got order: {call_order}"
        )
        assert event.isAccepted() is True
    finally:
        window.music_tab._transfer._running = False


def test_quit_anyway_refuses_to_unmount_if_join_times_out(qapp, monkeypatch):
    """
    The critical hardened property: if cancellation cannot be confirmed
    complete within the timeout, "Quit anyway" must NOT unmount — the
    close must be refused (window stays open) rather than force-unmounting
    a device that might still be mid-write. This is the exact scenario a
    checkpoint review flagged as unsafe in the original implementation.
    """
    window = _make_window(qapp)
    try:
        window.music_tab._transfer._running = True
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Yes)
        monkeypatch.setattr(window.music_tab._transfer, "cancel", lambda: None)
        monkeypatch.setattr(window.music_tab._transfer, "join", lambda timeout=None: False)  # never confirms stopped

        unmount_calls = {"count": 0}
        monkeypatch.setattr(
            window._dev_manager, "unmount_current",
            lambda: unmount_calls.__setitem__("count", unmount_calls["count"] + 1),
        )

        event = QCloseEvent()
        window.closeEvent(event)

        assert unmount_calls["count"] == 0, (
            "unmount must never be entered if cancellation could not be confirmed, "
            "even after the user clicked Quit anyway"
        )
        assert event.isAccepted() is False, "close must be refused when the worker can't be confirmed stopped"
    finally:
        window.music_tab._transfer._running = False


def test_quit_anyway_with_real_to_device_transfer_cancels_before_unmounting(qapp, monkeypatch, tmp_path):
    """
    End-to-end proof with a real worker thread and a real TO_DEVICE job
    (exactly "Add to iPhone"): confirming "Quit anyway" mid-copy must
    cancel and wait for the actual worker to stop before unmount_current()
    is ever called, and the partial destination file must not survive.
    """
    window = _make_window(qapp)
    try:
        engine = window.music_tab._transfer
        hold = threading.Event()
        entered = threading.Event()

        def on_job_progress(job):
            entered.set()
            hold.wait(timeout=5)

        engine._chunk_size = 1024
        engine.set_callbacks(
            on_job_progress=on_job_progress,
            on_all_complete=window.music_tab._transfer_bridge.all_complete.emit,
        )

        src = tmp_path / "song.mp3"
        src.write_bytes(b"x" * (1024 * 20))
        dest = tmp_path / "iphone_vlc" / "song.mp3"
        engine.add_job(str(src), str(dest), TransferDirection.TO_DEVICE)
        engine.start()

        assert entered.wait(timeout=5), "worker never reached the mid-copy checkpoint"
        assert dest.exists(), "destination file should exist mid-copy"
        assert engine.is_running is True

        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.Yes)
        unmount_calls = {"count": 0}
        monkeypatch.setattr(
            window._dev_manager, "unmount_current",
            lambda: unmount_calls.__setitem__("count", unmount_calls["count"] + 1),
        )

        # Release the blocked worker shortly after closeEvent requests
        # cancellation, simulating a real in-flight write finally noticing
        # the cancel flag between chunks.
        def release_shortly():
            time.sleep(0.2)
            hold.set()
        threading.Thread(target=release_shortly, daemon=True).start()

        event = QCloseEvent()
        window.closeEvent(event)

        assert unmount_calls["count"] == 1, "a confirmed-stopped transfer must still allow close to proceed"
        assert event.isAccepted() is True
        assert engine.is_running is False
        assert not dest.exists(), "the cancelled TO_DEVICE write must not leave a partial file behind"
    finally:
        window.music_tab._transfer._running = False


def test_close_proceeds_without_warning_when_no_transfer_active(qapp, monkeypatch):
    window = _make_window(qapp)

    warned = {"called": False}
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **kw: warned.__setitem__("called", True) or QMessageBox.Cancel,
    )

    event = QCloseEvent()
    window.closeEvent(event)

    assert warned["called"] is False, "no warning should appear when nothing is transferring"
    assert event.isAccepted() is True


def test_active_transfer_tab_names_reports_both_tabs(qapp):
    window = _make_window(qapp)
    try:
        assert window._active_transfer_tab_names() == []

        window.music_tab._transfer._running = True
        assert window._active_transfer_tab_names() == ["Music"]

        window.my_computer_tab._transfer._running = True
        assert window._active_transfer_tab_names() == ["Music", "My Computer"]
    finally:
        window.music_tab._transfer._running = False
        window.my_computer_tab._transfer._running = False

"""
Regression coverage for DeviceManager's poll-thread lifecycle.

CI caught a real segfault (exit 139) in the Qt bridge tests. The actual
mechanism, verified directly against core/device.py before any fix: the
old stop_polling() only set a shared bool and never waited for the poll
thread to actually exit, and the poll loop's time.sleep(interval) wasn't
interruptible — so a "stopped" DeviceManager could still have a live
thread sleeping for up to `interval` seconds afterward. Tests construct
many MainWindow()s in quick succession (test_close_active_transfer_guard.py,
test_player_bar_vlc_fallback.py); each one's poll thread, once it woke up,
would call back into a Qt bridge object (self._bridge.connected/disconnected)
belonging to a MainWindow that a *later* test had already moved past —
calling into a QObject whose C++ side may already be torn down is a
classic PySide6 segfault vector.

_get_udid is monkeypatched to avoid real subprocess calls (and to be
fast/deterministic) — these tests are about thread lifecycle, not device
detection.
"""
import threading
import time

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from core.device import DeviceManager
from ui.main_window import MainWindow


def _quiet_manager(interval=0.05):
    """A DeviceManager whose _get_udid never touches a real subprocess."""
    mgr = DeviceManager()
    mgr._get_udid = lambda: None
    return mgr


def test_stop_polling_leaves_no_live_thread():
    """Requirement 1: stop_polling() actually leaves no live poll thread."""
    mgr = _quiet_manager()
    mgr.start_polling(interval=0.05)
    assert mgr.is_polling is True

    confirmed = mgr.stop_polling(timeout=5)

    assert confirmed is True
    assert mgr.is_polling is False
    assert mgr._poll_thread is None or not mgr._poll_thread.is_alive()


def test_stop_polling_wakes_a_sleeping_wait_promptly():
    """
    Requirement 2: a sleeping interval wait is woken promptly by stop —
    stop_polling() must not have to wait out anywhere near the full
    interval before returning.
    """
    mgr = _quiet_manager()
    mgr.start_polling(interval=10.0)  # long interval — old code would sleep up to 10s
    time.sleep(0.05)  # let the loop enter its first wait

    start = time.monotonic()
    confirmed = mgr.stop_polling(timeout=5)
    elapsed = time.monotonic() - start

    assert confirmed is True
    assert elapsed < 1.0, (
        f"stop_polling() took {elapsed:.2f}s against a 10s interval — "
        "the wait was not interrupted promptly"
    )


def test_repeated_start_polling_does_not_create_multiple_workers():
    """Requirement 3: repeated start_polling() cannot create concurrent poll workers."""
    mgr = _quiet_manager()
    mgr.start_polling(interval=0.05)
    first_thread = mgr._poll_thread
    assert first_thread is not None and first_thread.is_alive()

    mgr.start_polling(interval=0.05)  # must be a no-op while one is already running
    second_thread = mgr._poll_thread

    assert second_thread is first_thread, "start_polling() spawned a second worker thread"

    assert mgr.stop_polling(timeout=5) is True


def test_start_polling_after_stop_spawns_a_fresh_worker():
    """A clean stop must not prevent a legitimate later restart (e.g. reconnect UI flow)."""
    mgr = _quiet_manager()
    mgr.start_polling(interval=0.05)
    first_thread = mgr._poll_thread
    assert mgr.stop_polling(timeout=5) is True
    assert not first_thread.is_alive()

    mgr.start_polling(interval=0.05)
    second_thread = mgr._poll_thread

    assert second_thread is not first_thread
    assert second_thread.is_alive()
    assert mgr.stop_polling(timeout=5) is True


def test_stop_polling_is_idempotent_and_safe_with_no_worker():
    mgr = _quiet_manager()
    assert mgr.stop_polling(timeout=1) is True  # never started — must not raise/hang
    assert mgr.stop_polling(timeout=1) is True  # double-stop — still safe


def test_stop_polling_from_the_poll_thread_itself_is_guarded():
    """
    joining the current thread is impossible/guarded: if something calls
    stop_polling() from inside the poll thread's own execution, it must
    not deadlock or raise — it should report "not confirmed" (False),
    since a thread cannot wait for itself to finish.
    """
    mgr = _quiet_manager()
    result_holder = {}

    def on_connected(device):
        # Running on the poll thread itself, mid-iteration.
        result_holder["result"] = mgr.stop_polling(timeout=1)

    mgr._get_udid = lambda: "fake-udid"
    mgr._fetch_device_info = lambda udid: object()  # truthy "device"
    mgr.set_callbacks(on_connected=on_connected, on_disconnected=lambda: None)
    mgr.start_polling(interval=0.05)

    deadline = time.monotonic() + 5
    while "result" not in result_holder and time.monotonic() < deadline:
        time.sleep(0.01)

    assert result_holder.get("result") is False, (
        "stop_polling() called from the poll thread itself must report "
        "False (not confirmed), not deadlock or raise"
    )

    # Clean up for real, from the test (main) thread.
    assert mgr.stop_polling(timeout=5) is True


def test_mainwindow_lifecycle_leaves_no_poll_thread_behind(qapp):
    """
    Requirement 4: a MainWindow test lifecycle does not leave polling
    threads behind after cleanup — the exact scenario that produced the
    segfault CI caught, exercised through the real production path
    (MainWindow.__init__ -> _start_device_polling, and closeEvent's
    stop_polling() call), not a hand-rolled DeviceManager.
    """
    before = threading.active_count()

    window = MainWindow()
    assert window._dev_manager.is_polling is True

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() is True

    after = threading.active_count()

    assert window._dev_manager.is_polling is False
    assert after == before, (
        f"thread count went from {before} to {after} — a poll thread "
        "leaked past MainWindow.closeEvent()"
    )


def test_repeated_mainwindow_construct_and_close_does_not_accumulate_threads(qapp):
    """
    The actual leak pattern: many MainWindow()s constructed and closed in
    quick succession (as the test suite does) must not accumulate live
    poll threads across iterations.
    """
    baseline = threading.active_count()

    for _ in range(5):
        window = MainWindow()
        event = QCloseEvent()
        window.closeEvent(event)
        assert threading.active_count() == baseline, (
            "poll threads accumulated across repeated MainWindow construct/close cycles"
        )


def test_close_is_blocked_when_stop_polling_not_confirmed(qapp, monkeypatch):
    """
    Regression test for the follow-up hardening: closeEvent() must consume
    stop_polling()'s return value, not just call it. If the poll worker
    can't be confirmed stopped within its bounded timeout, teardown must
    not proceed — no "quit anyway" override, unlike the transfer-cancel
    gate (which does offer one after a confirmed cancel request). This
    matters because a real single poll iteration can legitimately spend
    up to ~5s in _get_udid() plus several more 5s ideviceinfo calls, so a
    10s bounded join can genuinely return False without anything being
    broken — the caller must still treat that as "not safe to tear down."
    """
    window = MainWindow()
    try:
        monkeypatch.setattr(window._dev_manager, "stop_polling", lambda timeout=10.0: False)

        unmount_calls = {"count": 0}
        monkeypatch.setattr(
            window._dev_manager, "unmount_current",
            lambda: unmount_calls.__setitem__("count", unmount_calls["count"] + 1),
        )
        cleanup_calls = {"count": 0}
        monkeypatch.setattr(
            window.player_bar, "cleanup",
            lambda: cleanup_calls.__setitem__("count", cleanup_calls["count"] + 1),
        )
        warned = {"called": False}
        monkeypatch.setattr(
            QMessageBox, "warning",
            lambda *a, **kw: warned.__setitem__("called", True) or QMessageBox.Ok,
        )

        event = QCloseEvent()
        window.closeEvent(event)

        assert event.isAccepted() is False, "close must be refused when stop_polling() isn't confirmed"
        assert unmount_calls["count"] == 0, "unmount must never be entered without confirmed stop"
        assert cleanup_calls["count"] == 0, "PlayerBar cleanup must never be entered without confirmed stop"
        assert warned["called"] is True, "user must be warned that the worker couldn't be confirmed stopped"
    finally:
        window._dev_manager.stop_polling()


def test_close_proceeds_when_stop_polling_confirmed(qapp):
    """Preserve the existing successful-close behavior when stop_polling() returns True."""
    window = MainWindow()

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted() is True
    assert window._dev_manager.is_polling is False

"""
Regression coverage for Finding 2 / Slice B: replacing QTimer.singleShot
worker-thread completion handling with real Qt signal bridges.

Minimal Qt test harness proving the actual mechanism: a callback invoked
from a plain threading.Thread (exactly how TransferEngine calls
on_job_progress/on_all_complete) reaches a slot on the main thread via
_TransferBridge's Qt signals — and that the slot genuinely executes with
main-thread affinity, not just "eventually, somehow".

QTimer.singleShot(0, ...) scheduled from a bare threading.Thread never fires
(no event loop pumps on that thread), which is exactly the bug this
demonstrates has been eliminated: the signal-based path fires deterministically
once the main thread processes events, from any thread.
"""
import threading

from PySide6.QtCore import QCoreApplication, QThread

from ui.main_window import _TransferBridge, MusicTab, MyComputerTab


def test_signal_emitted_from_worker_thread_reaches_main_thread_slot(qapp):
    bridge = _TransferBridge()

    received = {}
    main_thread = QThread.currentThread()

    def slot(job):
        received["job"] = job
        received["thread"] = QThread.currentThread()

    bridge.job_progress.connect(slot)

    def worker():
        # Exactly how TransferEngine._execute_job invokes on_job_progress:
        # a direct call from inside a plain threading.Thread, no event loop
        # of its own.
        bridge.job_progress.emit("fake-job-payload")

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive()

    # The connection is a queued cross-thread connection, so the slot does
    # not run until the main thread's event loop processes it.
    deadline_iterations = 200
    for _ in range(deadline_iterations):
        QCoreApplication.processEvents()
        if "job" in received:
            break

    assert received.get("job") == "fake-job-payload", (
        "signal emitted from a background thread never reached the main-thread slot"
    )
    assert received["thread"] is main_thread, (
        "slot ran on the wrong thread — cross-thread signal affinity broken"
    )


def test_singleshot_from_bare_thread_never_fires_control_case(qapp):
    """
    Control case demonstrating exactly why the old code was broken: the
    same experiment, but using QTimer.singleShot(0, ...) from a bare
    threading.Thread instead of a Signal. This must NOT fire, proving the
    old pattern really was dead code and the Signal-based replacement is
    the actual fix, not a coincidental change.
    """
    from PySide6.QtCore import QTimer

    fired = threading.Event()

    def worker():
        QTimer.singleShot(0, fired.set)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)

    for _ in range(50):
        QCoreApplication.processEvents()

    assert not fired.is_set(), (
        "QTimer.singleShot from a bare thread fired — if this ever starts "
        "passing, the audit's core premise for Finding 2 no longer holds "
        "and this test suite's reasoning should be revisited"
    )


def test_music_tab_transfer_progress_reaches_slot_from_worker_thread(qapp):
    """
    End-to-end proof for the actual MusicTab wiring (not just the bridge in
    isolation): TransferEngine's on_job_progress callback, which now points
    at _transfer_bridge.job_progress.emit, actually updates transfer_bar
    when invoked from a background thread.
    """
    tab = MusicTab()
    tab.transfer_bar.show()
    tab.transfer_bar.setRange(0, 1)

    from core.transfer import TransferJob, TransferDirection, TransferStatus
    job = TransferJob(source="a", destination="b", filename="a.mp3",
                       status=TransferStatus.COMPLETE)
    tab._transfer._queue.append(job)

    # _setup_transfer() (run during MusicTab.__init__) already wired
    # TransferEngine's on_job_progress callback to
    # tab._transfer_bridge.job_progress.emit — invoke it exactly as
    # TransferEngine._execute_job would, from a background thread.
    def worker():
        tab._transfer._on_job_progress(job)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)

    for _ in range(200):
        QCoreApplication.processEvents()
        if tab.transfer_bar.value() == 1:
            break

    assert tab.transfer_bar.value() == 1, (
        "MusicTab's transfer progress bar was never updated by a callback "
        "originating on a background thread"
    )


def test_my_computer_tab_has_transfer_bridge(qapp):
    """MyComputerTab must be wired the same way as MusicTab (both were
    named explicitly in the audit as broken)."""
    tab = MyComputerTab()
    assert hasattr(tab, "_transfer_bridge")
    assert tab._transfer._on_job_progress == tab._transfer_bridge.job_progress.emit
    assert tab._transfer._on_all_complete == tab._transfer_bridge.all_complete.emit

"""
Regression coverage for Phase 0B Slice 2, section 7: MainWindow surfaces
the capability decision without turning startup into a wall of modal
dialogs — a normal/compatible environment shows nothing extra, every
other state gets a concise, visible, truthful reason.

Exercises MainWindow._apply_capability_to_ui() directly (the one place
that translates a CapabilityDecision into UI text) plus the actual
_mount_device() failure-messaging path for a hard-blocked environment.
Background device polling is stopped immediately after construction —
this file isn't testing poll behavior and a live poll thread would just
add subprocess noise.
"""
from PySide6.QtWidgets import QMessageBox

from core.capability import CapabilityDecision, RuntimeCapability, WritePolicy
from ui.main_window import MainWindow


def _decision(write_policy: WritePolicy, reason="test reason") -> CapabilityDecision:
    return CapabilityDecision(
        capability=RuntimeCapability(
            ifuse_present=True, ifuse_version=(1, 1, 3), ifuse_version_raw="ifuse 1.1.3",
            idevice_id_present=True, ideviceinfo_present=True, unmount_binary="fusermount3",
        ),
        write_policy=write_policy,
        reason=reason,
    )


def _make_window(qapp):
    window = MainWindow()
    window._dev_manager.stop_polling()
    return window


def test_write_enabled_shows_no_banner(qapp):
    window = _make_window(qapp)
    window._apply_capability_to_ui(_decision(WritePolicy.WRITE_ENABLED, "Compatible ifuse version detected."))
    assert window.capability_label.isHidden()


def test_read_only_legacy_shows_visible_reason(qapp):
    window = _make_window(qapp)
    decision = _decision(WritePolicy.READ_ONLY_LEGACY, "Installed ifuse (1.1.3) predates the verified floor.")
    window._apply_capability_to_ui(decision)
    assert not window.capability_label.isHidden()
    assert "1.1.3" in window.capability_label.text()


def test_known_corrupting_shows_visible_reason(qapp):
    window = _make_window(qapp)
    decision = _decision(WritePolicy.BLOCKED_KNOWN_CORRUPTING, "Installed ifuse is exactly 1.2.0 — data corruption bug.")
    window._apply_capability_to_ui(decision)
    assert not window.capability_label.isHidden()
    assert "1.2.0" in window.capability_label.text()
    assert "corruption" in window.capability_label.text().lower()


def test_missing_ifuse_shows_visible_reason(qapp):
    window = _make_window(qapp)
    decision = _decision(WritePolicy.BLOCKED_MISSING_IFUSE, "ifuse is not installed.")
    window._apply_capability_to_ui(decision)
    assert not window.capability_label.isHidden()
    assert "not installed" in window.capability_label.text().lower()


def test_startup_probe_result_is_reflected_before_any_mount_attempt(qapp, monkeypatch):
    """Capability must be known before mount/write is allowed — proven
    here by constructing MainWindow with a pre-wired blocked decision and
    checking the banner reflects it immediately, with no mount click."""
    monkeypatch.setattr(
        "core.device.probe_capability",
        lambda: RuntimeCapability(ifuse_present=False),
    )
    window = MainWindow()
    try:
        assert not window.capability_label.isHidden()
        assert "ifuse" in window.capability_label.text().lower()
    finally:
        window._dev_manager.stop_polling()


def test_mount_failure_for_blocked_policy_shows_capability_reason_not_generic_message(qapp, monkeypatch):
    window = _make_window(qapp)
    window._dev_manager._capability_provider = lambda: _decision(
        WritePolicy.BLOCKED_KNOWN_CORRUPTING, "Installed ifuse is exactly 1.2.0 — do not use in production."
    )
    # _mount_device() reads self._dev_manager.device (a DeviceInfo); fake
    # just enough of a connected device to pass the early-return guard.
    from core.device import DeviceInfo
    window._dev_manager._device = DeviceInfo(udid="fake-udid", name="Test iPhone", connected=True)

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda self, title, text: warnings.append((title, text)) or QMessageBox.Ok)

    window._mount_device()

    assert len(warnings) == 1
    title, text = warnings[0]
    assert title == "Mount Unavailable"
    assert "1.2.0" in text
    assert "production" in text.lower()

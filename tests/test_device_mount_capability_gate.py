"""
Regression coverage for Phase 0B Slice 2, spec item 10 and section 6:
DeviceManager.mount_media() must consult capability policy *before*
invoking ifuse, and a hard-blocked (or otherwise unmountable)
environment must never reach the actual ifuse subprocess call — proven
here by asserting subprocess.run is never called with "ifuse" as the
first argument, not just by checking the return value.

Every test injects a synthetic capability_provider directly into
DeviceManager — no real environment probing involved, and no real
device touched.
"""
import os
import subprocess as subprocess_module
from types import SimpleNamespace

import pytest

from core.device import DeviceManager
from core.capability import CapabilityDecision, RuntimeCapability, WritePolicy


def _decision(write_policy: WritePolicy, **capability_overrides) -> CapabilityDecision:
    base = dict(
        ifuse_present=True, ifuse_version=(1, 2, 1), ifuse_version_raw="ifuse 1.2.1",
        idevice_id_present=True, ideviceinfo_present=True, unmount_binary="fusermount3",
    )
    base.update(capability_overrides)
    return CapabilityDecision(
        capability=RuntimeCapability(**base),
        write_policy=write_policy,
        reason=f"test decision: {write_policy.value}",
    )


class _RecordingRun:
    """subprocess.run stand-in that records every call and never touches
    a real process — used to prove ifuse specifically was or wasn't
    invoked, not just to fake a return value."""

    def __init__(self, ifuse_returncode=0):
        self.calls = []
        self.ifuse_returncode = ifuse_returncode

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if cmd[0] == "ifuse":
            return SimpleNamespace(returncode=self.ifuse_returncode, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def invoked_ifuse(self) -> bool:
        return any(call[0] == "ifuse" for call in self.calls)


# ── 10. Exact 1.2.0 / any BLOCKED_* state never invokes the ifuse subprocess ─

def test_known_corrupting_version_never_invokes_ifuse_subprocess(monkeypatch):
    recorder = _RecordingRun()
    monkeypatch.setattr(subprocess_module, "run", recorder)

    mgr = DeviceManager(capability_provider=lambda: _decision(
        WritePolicy.BLOCKED_KNOWN_CORRUPTING, ifuse_version=(1, 2, 0), ifuse_version_raw="ifuse 1.2.0",
    ))
    mount = mgr.mount_media()

    assert mount is None
    assert recorder.invoked_ifuse() is False, "the ifuse subprocess must never be invoked for a hard-blocked environment"
    assert mgr.mount_dir is None


def test_missing_ifuse_never_invokes_ifuse_subprocess(monkeypatch):
    recorder = _RecordingRun()
    monkeypatch.setattr(subprocess_module, "run", recorder)

    mgr = DeviceManager(capability_provider=lambda: _decision(
        WritePolicy.BLOCKED_MISSING_IFUSE, ifuse_present=False, ifuse_version=None, ifuse_version_raw="",
    ))
    mount = mgr.mount_media()

    assert mount is None
    assert recorder.invoked_ifuse() is False
    assert mgr.mount_dir is None


def test_no_unmount_mechanism_never_invokes_ifuse_subprocess(monkeypatch):
    recorder = _RecordingRun()
    monkeypatch.setattr(subprocess_module, "run", recorder)

    mgr = DeviceManager(capability_provider=lambda: _decision(
        WritePolicy.BLOCKED_NO_UNMOUNT, unmount_binary=None,
    ))
    mount = mgr.mount_media()

    assert mount is None
    assert recorder.invoked_ifuse() is False, (
        "MoTunes must not create a mount it has no demonstrated way to tear down"
    )


# ── Read-only / legacy states still mount (reads must keep working) ─────────

@pytest.mark.parametrize("policy", [WritePolicy.WRITE_ENABLED, WritePolicy.READ_ONLY_LEGACY, WritePolicy.READ_ONLY_UNVERIFIED_VERSION])
def test_mountable_policies_do_invoke_ifuse_and_succeed(monkeypatch, policy):
    recorder = _RecordingRun(ifuse_returncode=0)
    monkeypatch.setattr(subprocess_module, "run", recorder)

    mgr = DeviceManager(capability_provider=lambda: _decision(policy))
    mount = mgr.mount_media()

    assert mount is not None, f"{policy} must still allow a mount for reads"
    assert recorder.invoked_ifuse() is True
    assert mgr.mount_dir == mount
    mgr.unmount_current()


# ── Capability is re-probed immediately before the mount, not just trusted
#    from whatever a stale earlier read said ──────────────────────────────────

def test_mount_media_reprobes_capability_immediately_before_mounting(monkeypatch):
    """A caller that never explicitly calls refresh_capability() must
    still get a fresh decision at mount time — mount_media() does not
    trust a capability reading from before this call."""
    recorder = _RecordingRun()
    monkeypatch.setattr(subprocess_module, "run", recorder)

    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        # First call happens inside mount_media() itself — there is no
        # earlier call in this test, proving mount_media() doesn't skip
        # probing just because __init__ already set a placeholder.
        return _decision(WritePolicy.WRITE_ENABLED)

    mgr = DeviceManager(capability_provider=provider)
    assert calls["n"] == 0, "constructing DeviceManager must not itself probe"

    mgr.mount_media()
    assert calls["n"] == 1, "mount_media() must probe capability exactly once, immediately before mounting"


def test_constructing_device_manager_defaults_to_fail_closed_before_any_refresh():
    """Before refresh_capability() is ever called, DeviceManager must not
    assume a permissive default — capability starts as 'unknown', which
    is policy-equivalent to 'nothing detected'."""
    mgr = DeviceManager(capability_provider=lambda: _decision(WritePolicy.WRITE_ENABLED))
    assert mgr.capability.can_mount is False, (
        "the placeholder before any real probe must be conservative, not permissive"
    )


# ── A caller invoking mount_media() directly (bypassing any UI) is still refused

def test_direct_mount_media_call_is_refused_for_blocked_policy_without_ui(monkeypatch):
    recorder = _RecordingRun()
    monkeypatch.setattr(subprocess_module, "run", recorder)
    mgr = DeviceManager(capability_provider=lambda: _decision(WritePolicy.BLOCKED_KNOWN_CORRUPTING))

    # No UI, no MainWindow involved at all — direct method invocation.
    result = mgr.mount_media()

    assert result is None
    assert recorder.invoked_ifuse() is False


# ── _do_unmount fusermount3 / fusermount fallback ────────────────────────────

def test_do_unmount_tries_fusermount3_first(monkeypatch, tmp_path):
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess_module, "run", _fake_run)
    mgr = DeviceManager(capability_provider=lambda: _decision(WritePolicy.WRITE_ENABLED))

    path = tmp_path / "some_mount"
    path.mkdir()
    mgr._do_unmount(str(path))

    assert calls[0][0] == "fusermount3"
    assert not path.exists()


def test_do_unmount_falls_back_to_fusermount_when_fusermount3_is_absent(monkeypatch, tmp_path):
    calls = []

    def _fake_run(cmd, **kwargs):
        if cmd[0] == "fusermount3":
            raise FileNotFoundError("no such binary")
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess_module, "run", _fake_run)
    mgr = DeviceManager(capability_provider=lambda: _decision(WritePolicy.WRITE_ENABLED))

    path = tmp_path / "some_mount"
    path.mkdir()
    mgr._do_unmount(str(path))

    assert calls == [["fusermount", "-u", str(path)]]
    assert not path.exists()


def test_do_unmount_never_raises_when_both_binaries_are_absent(monkeypatch, tmp_path):
    def _fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(subprocess_module, "run", _fake_run)
    mgr = DeviceManager(capability_provider=lambda: _decision(WritePolicy.WRITE_ENABLED))

    path = tmp_path / "some_mount"
    path.mkdir()
    mgr._do_unmount(str(path))  # must not raise

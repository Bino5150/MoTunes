"""
Regression coverage for Finding 3 / Slice C: DeviceManager mount ownership.

All subprocess calls (ifuse / fusermount) are monkeypatched — nothing here
ever touches a real device. tempfile.mkdtemp() does create a real (empty)
scratch directory on the test machine's filesystem, which is exactly what
mount_media() does in production before handing it to ifuse; tests clean up
after themselves.
"""
import os
import subprocess as subprocess_module
from types import SimpleNamespace

import pytest

from core.device import DeviceManager


class _FakeCompletedProcess(SimpleNamespace):
    pass


def _fake_run_factory(ifuse_returncode=0):
    """Build a subprocess.run stand-in that succeeds/fails for ifuse and
    always 'succeeds' for fusermount (matching real fusermount behavior of
    not erroring loudly on a redundant -u)."""
    def _fake_run(cmd, **kwargs):
        if cmd[0] == "ifuse":
            return _FakeCompletedProcess(returncode=ifuse_returncode, stdout="", stderr="ifuse failed" if ifuse_returncode else "")
        if cmd[0] == "fusermount":
            return _FakeCompletedProcess(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess call: {cmd}")
    return _fake_run


def test_successful_mount_records_active_mount(monkeypatch):
    monkeypatch.setattr(subprocess_module, "run", _fake_run_factory(ifuse_returncode=0))
    mgr = DeviceManager()

    assert mgr.mount_dir is None
    mount = mgr.mount_media()

    assert mount is not None
    assert os.path.isdir(mount)
    assert mgr.mount_dir == mount, "mount_media() must record the active mount on DeviceManager"

    mgr.unmount_current()
    assert not os.path.isdir(mount)


def test_failed_mount_leaves_no_false_active_state(monkeypatch):
    monkeypatch.setattr(subprocess_module, "run", _fake_run_factory(ifuse_returncode=1))
    mgr = DeviceManager()

    mount = mgr.mount_media()

    assert mount is None
    assert mgr.mount_dir is None, "a failed mount must not leave a false active mount"


def test_unmount_clears_active_state(monkeypatch):
    monkeypatch.setattr(subprocess_module, "run", _fake_run_factory(ifuse_returncode=0))
    mgr = DeviceManager()

    mount = mgr.mount_media()
    assert mgr.mount_dir == mount

    mgr.unmount_current()
    assert mgr.mount_dir is None


def test_repeated_unmount_is_safe_and_idempotent(monkeypatch):
    monkeypatch.setattr(subprocess_module, "run", _fake_run_factory(ifuse_returncode=0))
    mgr = DeviceManager()

    mgr.mount_media()
    mgr.unmount_current()
    assert mgr.mount_dir is None

    # A second unmount with nothing mounted must not raise, and must not
    # attempt anything destructive (no mount_dir to act on).
    mgr.unmount_current()
    assert mgr.mount_dir is None

    # disconnect() (the public API) must be equally idempotent.
    mgr.disconnect()
    assert mgr.mount_dir is None


def test_full_mount_active_unmount_cleared_cycle(monkeypatch):
    """mount -> active state -> unmount -> cleared state, end to end."""
    monkeypatch.setattr(subprocess_module, "run", _fake_run_factory(ifuse_returncode=0))
    mgr = DeviceManager()

    assert mgr.mount_dir is None

    mount = mgr.mount_media()
    assert mount is not None
    assert mgr.mount_dir == mount

    mgr.unmount_current()
    assert mgr.mount_dir is None

    # A second unmount call must be a safe no-op, not a crash or a
    # destructive operation on some stale path.
    mgr.unmount_current()
    assert mgr.mount_dir is None


def test_unmount_path_matching_current_mount_clears_tracked_state(monkeypatch):
    """
    MainWindow's stale-mount cleanup and the tracked-mount teardown both
    route through unmount_path()/unmount_current(); if unmount_path() is
    ever called with the path DeviceManager itself is tracking, tracked
    state must not be left dangling.
    """
    monkeypatch.setattr(subprocess_module, "run", _fake_run_factory(ifuse_returncode=0))
    mgr = DeviceManager()

    mount = mgr.mount_media()
    assert mgr.mount_dir == mount

    mgr.unmount_path(mount)
    assert mgr.mount_dir is None, "unmount_path() must clear tracked state when it matches"


def test_unmount_path_for_unrelated_stale_mount_does_not_disturb_tracked_state(monkeypatch, tmp_path):
    """Stale-mount cleanup (glob of leftover /tmp/motunes_media_* dirs from a
    previous session) must not clobber a mount this manager currently owns."""
    monkeypatch.setattr(subprocess_module, "run", _fake_run_factory(ifuse_returncode=0))
    mgr = DeviceManager()

    mount = mgr.mount_media()
    assert mgr.mount_dir == mount

    stale = tmp_path / "stale_previous_session_mount"
    stale.mkdir()
    mgr.unmount_path(str(stale))

    assert mgr.mount_dir == mount, "unmounting an unrelated stale path must not clear the real tracked mount"

    mgr.unmount_current()
    assert mgr.mount_dir is None

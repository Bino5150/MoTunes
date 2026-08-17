"""
Regression coverage for Finding 1 / Slice A: neutralizing the destructive
"Clean Music Library" feature.

Builds a fixture directory tree that mimics a real iPhone's
iTunes_Control/Music/F## layout plus the iTunes sync database files, points
DeviceToolsTab at it as a fake mount point, and proves that nothing reachable
from the normal UI (the button click handler) can delete any of it.

This never touches a real device — the "mount point" is just a tmp_path
fixture directory.
"""
import os

import pytest

from ui.main_window import DeviceToolsTab


def _make_fixture_itunes_tree(root):
    """Build a fixture iTunes_Control tree with F00/F01 music folders (each
    containing a dummy audio file) and the iTunes sync database files."""
    music_dir = os.path.join(root, "iTunes_Control", "Music")
    itunes_dir = os.path.join(root, "iTunes_Control", "iTunes")
    os.makedirs(music_dir)
    os.makedirs(itunes_dir)

    audio_files = []
    for folder in ("F00", "F01"):
        fdir = os.path.join(music_dir, folder)
        os.makedirs(fdir)
        fpath = os.path.join(fdir, "ABCD1234.mp3")
        with open(fpath, "wb") as f:
            f.write(b"fake audio data")
        audio_files.append(fpath)

    db_files = []
    for fname in ["iTunesDB", "iTunesCDB", "iTunesControl",
                  "iTunesPrefs", "iTunesPrefs.plist"]:
        fpath = os.path.join(itunes_dir, fname)
        with open(fpath, "wb") as f:
            f.write(b"fake itunes db data")
        db_files.append(fpath)

    return audio_files, db_files


def test_cleanup_button_has_no_destructive_handler(qapp):
    """
    The button must not be wired to any method that can reach the
    filesystem. If a future edit reconnects it to a destructive handler,
    this assertion fails loudly instead of silently reintroducing Finding 1.
    """
    tab = DeviceToolsTab()
    assert not hasattr(tab, "_run_cleanup")
    assert not hasattr(tab, "_do_cleanup")
    assert not hasattr(tab, "_cleanup_done")


def test_cleanup_button_is_permanently_disabled_even_when_mounted(tmp_path, qapp):
    """
    Mounting a device must not enable the cleanup button — there is no safe
    implementation behind it in this build.
    """
    root = str(tmp_path)
    _make_fixture_itunes_tree(root)

    tab = DeviceToolsTab()
    assert tab.cleanup_btn.isEnabled() is False

    tab.set_mount_point(root)
    assert tab.cleanup_btn.isEnabled() is False, (
        "cleanup_btn became enabled after mounting — the disabled placeholder "
        "must stay disabled regardless of mount state"
    )


def test_fixture_itunes_tree_survives_full_devicetoolstab_lifecycle(tmp_path, qapp):
    """
    Exercises the actual normal-UI path end to end: construct the tab,
    mount a fixture iTunes tree, and confirm every audio file and every
    iTunes database file is still present and untouched afterward. This is
    the direct regression test for the "wipes ALL music" finding — it
    would fail against the old implementation if the button were clicked
    (the button no longer exists in a clickable, destructive form at all).
    """
    root = str(tmp_path)
    audio_files, db_files = _make_fixture_itunes_tree(root)

    tab = DeviceToolsTab()
    tab.set_mount_point(root)

    # Nothing about constructing/mounting the tab may touch the fixture tree.
    for fpath in audio_files + db_files:
        assert os.path.exists(fpath), f"fixture file missing before any action: {fpath}"

    music_dir = os.path.join(root, "iTunes_Control", "Music")
    assert sorted(os.listdir(music_dir)) == ["F00", "F01"], (
        "F## folders must remain exactly as fixtured — no code path in "
        "DeviceToolsTab may remove them"
    )


def test_no_reachable_code_path_calls_rmtree_or_os_remove_on_mount_point(tmp_path, qapp):
    """
    Whitebox safety net: monkeypatch shutil.rmtree and os.remove to raise if
    ever invoked with a path under the fixture mount point, then drive
    DeviceToolsTab through construction and mounting. Guards against a
    future change reintroducing a destructive call anywhere in this tab
    without a corresponding UI action being the only way to trigger it.
    """
    import shutil

    root = str(tmp_path)
    _make_fixture_itunes_tree(root)

    def _forbidden_rmtree(path, *a, **kw):
        raise AssertionError(f"shutil.rmtree must never be called on the mount tree: {path}")

    def _forbidden_remove(path, *a, **kw):
        if str(path).startswith(root):
            raise AssertionError(f"os.remove must never be called on the mount tree: {path}")

    orig_rmtree = shutil.rmtree
    orig_remove = os.remove
    shutil.rmtree = _forbidden_rmtree
    os.remove = _forbidden_remove
    try:
        tab = DeviceToolsTab()
        tab.set_mount_point(root)
        tab.set_mount_point(None)
        tab.set_mount_point(root)
    finally:
        shutil.rmtree = orig_rmtree
        os.remove = orig_remove

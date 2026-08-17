"""
Regression coverage for the VLC-runtime-detection defect CI exposed: a
GitHub Actions runner has the python-vlc pip package (via
requirements-dev.txt) but no actual native libvlc installed. `import vlc`
succeeds regardless (it's a ctypes wrapper that only touches the native
library lazily), so the old HAS_VLC flag was True — but constructing
_vlc.MediaPlayer() is what actually first touches libvlc, and on that
runner it raised:

    NameError: no function 'libvlc_new'

...crashing every test that constructed a real MainWindow(), since
PlayerBar() is built unconditionally as part of MainWindow._setup_ui().

These tests inject a fake `_vlc` module object into ui.main_window's
namespace rather than assuming a real `vlc` package is importable in
whatever environment runs this suite — python-vlc isn't installed in
every dev/CI environment (this sandbox included), so HAS_VLC_BINDINGS can
legitimately be False here too. Patching in a fake lets these tests
exercise the "bindings present, native runtime absent" case exactly as CI
hit it, independent of what's actually installed locally.
"""
import ui.main_window as mw
from ui.main_window import PlayerBar, MainWindow, _make_vlc_player


class _FakeVlcModule:
    """Stand-in for the `vlc` module — just needs a MediaPlayer callable."""
    def __init__(self, media_player_factory):
        self.MediaPlayer = media_player_factory


def _patch_vlc(monkeypatch, media_player_factory):
    monkeypatch.setattr(mw, "HAS_VLC_BINDINGS", True)
    monkeypatch.setattr(mw, "_vlc", _FakeVlcModule(media_player_factory), raising=False)


def test_make_vlc_player_returns_none_on_nameerror(monkeypatch):
    """Core mechanism: the exact failure class CI hit must be caught."""
    def raise_nameerror():
        raise NameError("no function 'libvlc_new'")

    _patch_vlc(monkeypatch, raise_nameerror)

    assert _make_vlc_player() is None


def test_make_vlc_player_returns_none_on_oserror(monkeypatch):
    """
    A sibling native-loading failure mode: some python-vlc versions/
    platforms surface a missing libvlc as OSError from the underlying
    ctypes/dlopen call rather than NameError. Both must degrade the same
    way — this is why the except clause covers both, not because of
    speculative broad exception handling.
    """
    def raise_oserror():
        raise OSError("libvlc.so.5: cannot open shared object file")

    _patch_vlc(monkeypatch, raise_oserror)

    assert _make_vlc_player() is None


def test_make_vlc_player_returns_none_when_bindings_missing(monkeypatch):
    """The pre-existing case (python-vlc not installed at all) must still work."""
    monkeypatch.setattr(mw, "HAS_VLC_BINDINGS", False)
    assert _make_vlc_player() is None


def test_make_vlc_player_returns_real_player_when_runtime_works(monkeypatch):
    """
    Preserve working VLC playback when a valid native VLC installation is
    present — the fix must not turn a working player into None.
    """
    sentinel = object()
    _patch_vlc(monkeypatch, lambda: sentinel)

    assert _make_vlc_player() is sentinel


def test_playerbar_construction_survives_missing_native_runtime(qapp, monkeypatch):
    """
    PlayerBar construction must gracefully degrade to self._player = None
    — not raise — and playback controls must remain in the existing
    no-player disabled state.
    """
    def raise_nameerror():
        raise NameError("no function 'libvlc_new'")

    _patch_vlc(monkeypatch, raise_nameerror)

    bar = PlayerBar()  # must not raise

    assert bar._player is None
    assert bar.play_btn.isEnabled() is False
    assert bar.prev_btn.isEnabled() is False
    assert bar.next_btn.isEnabled() is False


def test_mainwindow_constructs_without_native_vlc(qapp, monkeypatch):
    """
    End-to-end proof matching the actual CI failure: MainWindow() (which
    builds PlayerBar unconditionally inside _setup_ui) must remain fully
    constructible when the native VLC runtime is unavailable.
    """
    def raise_nameerror():
        raise NameError("no function 'libvlc_new'")

    _patch_vlc(monkeypatch, raise_nameerror)

    window = MainWindow()  # must not raise
    try:
        assert window.player_bar._player is None
        assert window.player_bar.play_btn.isEnabled() is False
    finally:
        window._dev_manager.stop_polling()

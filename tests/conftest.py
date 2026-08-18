"""
Shared pytest fixtures for MoTunes' regression suite.

Forces the Qt offscreen platform plugin before PySide6 is ever imported by a
test module, so the whole suite runs headlessly (no real display / Xvfb
needed) and never touches a real iPhone or its filesystem.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Add project root to sys.path so `import core...` / `import ui...` work
# the same way motunes.py sets it up for the real app.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

import core.device as device_module
from core.capability import RuntimeCapability


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication instance shared by every test that needs one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _default_permissive_capability(monkeypatch):
    """
    Every DeviceManager() constructed during a test — directly, or
    indirectly via MainWindow() — gets a permissive, write-enabled
    capability by default. Without this, DeviceManager's real capability
    probe (PATH lookups + `ifuse --version`) reflects whatever happens to
    be installed on the machine actually running the suite, which is
    exactly the "tests depend on real system packages" outcome Phase 0B
    Slice 2 exists to keep out of the test suite itself. Tests that
    specifically exercise capability policy override this within
    themselves via their own monkeypatch/capability_provider.
    """
    fake_capability = RuntimeCapability(
        ifuse_present=True, ifuse_version=(1, 2, 1), ifuse_version_raw="ifuse 1.2.1",
        idevice_id_present=True, ideviceinfo_present=True, unmount_binary="fusermount3",
    )
    monkeypatch.setattr(device_module, "probe_capability", lambda: fake_capability)

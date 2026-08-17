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


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication instance shared by every test that needs one."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

"""Where the app keeps exams, templates and settings: %LOCALAPPDATA%\\OMR, or, for the portable copy (a
portable.txt next to OMR.exe), a data folder beside it, so the whole thing moves on a USB stick."""

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def portable_dir() -> Path | None:
    """The data folder next to the portable app, or None when the app is installed or run from source."""
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).parent
        if (here / "portable.txt").is_file():
            return here / "data"
    return None


def data_dir() -> Path:
    return portable_dir() or Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / "OMR"

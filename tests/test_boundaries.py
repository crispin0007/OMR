import importlib
import pkgutil
import sys

import omr_core

UI_MODULES = ("PySide6", "pytwain", "win32api")


def test_core_imports_no_ui_or_windows_modules():
    # Constitution II: omr_core must run without the desktop stack.
    for mod in pkgutil.walk_packages(omr_core.__path__, "omr_core."):
        importlib.import_module(mod.name)
    assert not [m for m in UI_MODULES if m in sys.modules]

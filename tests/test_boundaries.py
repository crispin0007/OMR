import subprocess
import sys

UI_MODULES = ("PySide6", "pytwain", "win32api")

# A fresh interpreter, because other tests (the app's) import PySide6 into this one.
CHECK = f"""
import importlib, pkgutil, sys
import omr_core
for mod in pkgutil.walk_packages(omr_core.__path__, "omr_core."):
    importlib.import_module(mod.name)
print([m for m in {UI_MODULES!r} if m in sys.modules])
"""


def test_core_imports_no_ui_or_windows_modules():
    # Constitution II: omr_core must run without the desktop stack.
    out = subprocess.run([sys.executable, "-c", CHECK], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"

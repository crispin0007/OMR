# PyInstaller recipe for the Windows app: pyinstaller packaging/omr.spec (see packaging/README.md).
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

a = Analysis(
    [str(SRC / "omr_app" / "__main__.py")],
    pathex=[str(SRC)],
    datas=[
        (str(SRC / "omr_core" / "fonts"), "omr_core/fonts"),
        (str(SRC / "omr_app" / "icon.png"), "omr_app"),
        (str(ROOT / "templates"), "templates"),
        *copy_metadata("omr"),  # the version shown in Help
    ],
    excludes=["tkinter", "matplotlib", "pytest", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork",
              "PySide6.QtOpenGL", "PySide6.QtPdf", "PySide6.QtSvg", "PySide6.QtVirtualKeyboard"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="OMR", icon=str(ROOT / "packaging" / "omr.ico"),
          console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="OMR")

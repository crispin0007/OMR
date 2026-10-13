# PyInstaller recipe for the app: pyinstaller packaging/omr.spec (see packaging/README.md). On Windows and Linux it
# makes the folder dist/OMR; on macOS also dist/OMR Checker.app.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

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
    hiddenimports=collect_submodules("reportlab.graphics.barcode"),  # its barcode types are imported by name
    excludes=["tkinter", "matplotlib", "pytest", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork",
              "PySide6.QtOpenGL", "PySide6.QtPdf", "PySide6.QtSvg", "PySide6.QtVirtualKeyboard"],
)
pyz = PYZ(a.pure)
icon = ROOT / ("packaging/omr.ico" if sys.platform == "win32" else "src/omr_app/icon.png")  # PNG made into .icns
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="OMR", icon=str(icon), console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="OMR")
if sys.platform == "darwin":
    version = next(line.split('"')[1] for line in (ROOT / "pyproject.toml").read_text().splitlines()
                   if line.startswith("version = "))
    app = BUNDLE(coll, name="OMR Checker.app", icon=str(icon), bundle_identifier="io.github.crispin0007.omr",
                 version=version, info_plist={"NSHighResolutionCapable": True, "CFBundleDisplayName": "OMR Checker",
                                              "LSMinimumSystemVersion": "11.0"})

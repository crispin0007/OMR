# Windows app and installer

Teachers install OMR like any Windows program; they don't need Python.

On a Windows PC with Python 3.11 or newer and [Inno Setup 6](https://jrsoftware.org/isinfo.php), run in
the repository folder:

```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

This makes `dist\OMR\OMR.exe` (the app, which also runs from a USB stick) and
`dist\OMR-Setup-<version>.exe` (the installer, with a Start menu entry and an optional desktop shortcut).

- Exams, scans and templates stay in `%LOCALAPPDATA%\OMR`; installing a new version or uninstalling
  keeps them.
- `omr.spec` is the PyInstaller recipe, `omr.iss` the Inno Setup script, `make_icon.py` draws the icon.
- Licences: PyInstaller is GPL with an exception that allows shipping the built app under any licence;
  Inno Setup's licence allows free and commercial use. Neither ends up as code in the app.

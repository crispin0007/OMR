# Building the downloads

Teachers install OMR Checker like any program; they don't need Python.

## Publishing a release

1. Set the new version in `pyproject.toml` (for example `version = "0.2.0"`), commit and push.
2. Tag that commit with the same version, starting with `v`, and push the tag:
   ```
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. GitHub Actions (`.github/workflows/release.yml`) builds every download on Windows, macOS (Apple
   Silicon and Intel) and Linux, and publishes a Release with them, `SHA256SUMS.txt`, the download
   table from `release-notes.md` and the list of changes since the last tag. It takes about 20
   minutes. It refuses a tag that doesn't match `pyproject.toml`.

To try the builds without publishing anything, open Actions > Release > **Run workflow**. The files
appear as artifacts at the bottom of that run's page.

The downloads are not signed with a paid certificate, so Windows and macOS warn the first time. The
README tells people how to open them anyway.

## Windows

On a Windows PC with Python 3.11 or newer and [Inno Setup 6.3 or newer](https://jrsoftware.org/isinfo.php),
run in the repository folder:

```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

This makes, in `dist\`:

- `OMR\OMR.exe`: the app itself.
- `OMR-Setup-<version>.exe`: the installer.
- `OMR-Portable-<version>.zip`: the same app with nothing to install.

The version comes from `pyproject.toml`.

## The installer

- **Pages:** a welcome page and a finish page with the OMR Checker panel, the licence (Apache 2.0),
  the install folder, a desktop shortcut (optional), and a finish page that can start the app.
- **Who it installs for:** it asks whether to install for everyone (needs administrator rights,
  into Program Files) or only for the current user (no administrator rights needed).
- **Start menu:** OMR Checker and Uninstall OMR Checker.
- **Updating:** running a newer installer updates the app in place, in the same folder. It closes a
  running OMR Checker first. Exams, scans and templates in `%LOCALAPPDATA%\OMR` and settings in
  `%APPDATA%\OMR` are never touched.
- **Uninstalling** (Settings > Apps) removes the app, then asks whether to delete the exams and
  settings too. The default is No. A silent uninstall (`/VERYSILENT`) never deletes them.
- **Details shown in Settings > Apps and the file's properties:** name, version, publisher
  ("OMR Checker project"), and links to the project, issues and releases.
- **No file association:** the app opens no document type of its own (backups are SQLite files,
  which other programs use too), so the installer registers none.

Files:

- `omr.spec`: the PyInstaller recipe.
- `omr.iss`: the Inno Setup script.
- `make_wizard_images.py`: draws the installer's side panel and corner logo at every display scale
  into `build\wizard` (build outputs, not kept in git).
- `make_icon.py`: draws the app icon.

## The portable zip

The portable zip is the app folder with a `portable.txt` file in it. When `OMR.exe` finds that file
beside it, it keeps exams, scans, templates and settings in a `data` folder next to it instead of in
`%LOCALAPPDATA%`. Unzip it somewhere you can write to (a USB stick, Documents), not into Program
Files. Delete `portable.txt` to make that copy use `%LOCALAPPDATA%\OMR` like the installed app.

## Code signing

Without a signature, Windows SmartScreen warns "Windows protected your PC" on the first run, and
the person has to press **More info > Run anyway**. Signing removes the "unknown publisher" warning.
SmartScreen still needs some reputation to build up for a new certificate. An EV certificate
skips that wait.

1. Buy a code-signing certificate from a certificate authority (for example DigiCert, Sectigo or
   SSL.com). Since 2023 the private key must live on a hardware token or a cloud signing service,
   so the CA will tell you how to sign with it. The build uses Microsoft's `signtool`, which most of
   them support.
2. Install the Windows SDK (it has `signtool.exe`).
3. Before running `build.ps1`, set:
   ```
   $env:OMR_SIGN_CERT = "C:\path\to\certificate.pfx"      # a .pfx file, or
   $env:OMR_SIGN_CERT = "<SHA-1 thumbprint>"               # a certificate in the Windows store or on a token
   $env:OMR_SIGN_PASSWORD = "<the .pfx password>"          # only for a .pfx file
   ```
4. The build signs `OMR.exe`, the installer and the uninstaller with SHA-256, and timestamps each
   signature (timestamp.digicert.com), so they stay valid after the certificate expires.

Nothing is signed when `OMR_SIGN_CERT` is not set. No certificate is kept in this repository.

## Check a build on a clean Windows PC

The installer is built and tested on Windows only. Before publishing a release, on a Windows 10 or
11 PC (or VM) that has never had OMR Checker:

1. Run `OMR-Setup-<version>.exe`. Check:
   - the welcome page shows the blue OMR Checker panel, and the other pages the small logo top right;
   - the licence page, the folder page, and the desktop shortcut tick box are there.
2. Finish with **Start OMR Checker now** ticked. The app opens. Create an exam, import one scan, and
   close the app.
3. Check the Start menu entry, the desktop shortcut (if ticked), and Settings > Apps, which should show
   the version and publisher.
4. Run the same installer again, or a newer one. It should skip the folder page and update in place,
   and the exam should still be there.
5. With the app open, run the installer again. It should offer to close the app first.
6. Uninstall from Settings > Apps and answer **No** to deleting exams. `%LOCALAPPDATA%\OMR\omr.db`
   should still exist. Install again, and the exam should be back.
7. Uninstall again and answer **Yes**. `%LOCALAPPDATA%\OMR` and `%APPDATA%\OMR` should be gone.
8. Install "only for me" from a standard (non-administrator) account. No administrator prompt should
   appear.
9. Unzip `OMR-Portable-<version>.zip` to a USB stick and run `OMR.exe`. Create an exam. A `data`
   folder should appear beside it, and `%LOCALAPPDATA%\OMR` should be unchanged.
10. Run it on a 150% display scale. The installer images should be sharp and the app window should
    fit the screen.

## macOS

On a Mac with Python 3.11 or newer:

```
python3 -m pip install ".[app]" pyinstaller
pyinstaller --noconfirm --distpath dist --workpath build packaging/omr.spec
packaging/macos/build.sh
```

This makes `dist/OMR-Checker-<version>-macos-apple-silicon.dmg` (or `-intel`, matching the Mac it was
built on). The app has an ad-hoc signature only, which Apple Silicon needs to run it at all. Data goes
to `~/Library/Application Support/OMR`. Scanning straight from a feeder is Windows-only; on a Mac,
people scan into a watched folder.

## Linux

On Ubuntu 22.04 or newer (the oldest system you build on is the oldest it runs on):

```
python3 -m pip install ".[app]" pyinstaller
pyinstaller --noconfirm --distpath dist --workpath build packaging/omr.spec
packaging/linux/build.sh
```

This makes:

- `omr-checker_<version>_amd64.deb`: installs into `/opt/omr-checker`, adds `omr-checker` and a menu
  entry, and pulls in the X11 libraries Qt needs.
- `OMR-Checker-<version>-x86_64.AppImage`: runs on most distributions.
- `OMR-Checker-<version>-linux-x86_64.tar.gz`: the app folder; run `OMR/OMR`.

Data goes to `~/.local/share/OMR`.

## Check a release on each system

**macOS** (not tested yet; built only by GitHub Actions):

1. Open the `.dmg` for your chip and drag OMR Checker to Applications.
2. Double-click it and expect the block. Then right-click > Open, or on macOS 15+ use Privacy &
   Security > Open Anyway. The app should start.
3. Create an exam, print a sheet to PDF, and import a scan of it. Check that the result appears and
   that a sheet number barcode reads back.
4. Quit and reopen the app. The exam should still be there (in `~/Library/Application Support/OMR`).
5. Check the Dock icon and that the window fits a 13-inch screen.

**Linux** (the .deb and the AppImage were built and started on Ubuntu 24.04 in a test machine):

1. On a desktop Ubuntu or Mint, run `sudo apt install ./omr-checker_*.deb`. OMR Checker should appear
   in the app menu with its icon, and open.
2. Create an exam, save the sheet as a PDF, import a scan, export the merit list.
3. Remove it with `sudo apt remove omr-checker`. Your exams in `~/.local/share/OMR` stay.
4. On another distribution (Fedora, for example), `chmod +x` the AppImage and run it.

## Licences

PyInstaller is GPL with an exception that allows shipping the built app under any licence. Inno
Setup's licence allows free and commercial use. Neither ends up as code in the app.

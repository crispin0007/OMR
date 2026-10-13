#!/usr/bin/env bash
# Linux downloads from dist/OMR (run `pyinstaller packaging/omr.spec` first): a .deb for Ubuntu and Debian,
# an AppImage for any distribution, and a .tar.gz of the app folder. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/../.."
version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
here=packaging/linux

tar -C dist -czf "dist/OMR-Checker-$version-linux-x86_64.tar.gz" OMR

# .deb: the app in /opt/omr-checker, `omr-checker` on the PATH, and a menu entry.
deb=build/deb
rm -rf "$deb"
mkdir -p "$deb/DEBIAN" "$deb/opt" "$deb/usr/bin" "$deb/usr/share/applications" "$deb/usr/share/icons/hicolor/256x256/apps"
cp -r dist/OMR "$deb/opt/omr-checker"
ln -s /opt/omr-checker/OMR "$deb/usr/bin/omr-checker"
cp "$here/omr-checker.desktop" "$deb/usr/share/applications/"
cp src/omr_app/icon.png "$deb/usr/share/icons/hicolor/256x256/apps/omr-checker.png"
cat > "$deb/DEBIAN/control" <<CONTROL
Package: omr-checker
Version: $version
Section: education
Priority: optional
Architecture: amd64
Maintainer: OMR Checker project
Homepage: https://github.com/crispin0007/omr
Depends: libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-image0, libxcb-render-util0, libxcb-shape0,
 libxcb-xinerama0, libxcb-randr0, libxcb-xkb1, libxkbcommon-x11-0, libegl1, libgl1, libfontconfig1, libdbus-1-3
Description: Free, offline OMR sheet scanner and answer sheet maker
 Prints OMR answer sheets, reads filled sheets from scans and gives marks,
 ranks and merit lists, all offline.
CONTROL
dpkg-deb --build --root-owner-group "$deb" "dist/omr-checker_${version}_amd64.deb"

# AppImage: the same folder with a launcher; appimagetool packs it into one runnable file.
app=build/AppDir
rm -rf "$app"
mkdir -p "$app/usr/lib"
cp -r dist/OMR "$app/usr/lib/omr-checker"
cp "$here/omr-checker.desktop" "$app/"
cp src/omr_app/icon.png "$app/omr-checker.png"
printf '#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/usr/lib/omr-checker/OMR" "$@"\n' > "$app/AppRun"
chmod +x "$app/AppRun"
tool=build/appimagetool
if [ ! -x "$tool" ]; then
    curl -fsSL -o "$tool" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$tool"
fi
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$tool" --no-appstream "$app" "dist/OMR-Checker-$version-x86_64.AppImage"
ls -l dist

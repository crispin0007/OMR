#!/usr/bin/env bash
# The macOS download: a .dmg with OMR Checker.app, a link to Applications and the first-open steps. Run after
# `pyinstaller packaging/omr.spec` on a Mac; the .dmg is for that Mac's chip (arm64 or x86_64).
set -euo pipefail
cd "$(dirname "$0")/../.."
version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
chip=$(uname -m)
[ "$chip" = "x86_64" ] && label=intel || label=apple-silicon

# Not signed with an Apple certificate (none is bought); an ad-hoc signature lets it run on Apple Silicon.
codesign --force --deep --sign - "dist/OMR Checker.app"

stage=build/dmg
rm -rf "$stage"
mkdir -p "$stage"
cp -R "dist/OMR Checker.app" "$stage/"
ln -s /Applications "$stage/Applications"
cp "packaging/macos/First open - read me.txt" "$stage/"
hdiutil create -volname "OMR Checker" -srcfolder "$stage" -ov -format UDZO "dist/OMR-Checker-$version-macos-$label.dmg"

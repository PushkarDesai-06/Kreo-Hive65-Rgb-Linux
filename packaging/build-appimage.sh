#!/usr/bin/env bash
# Build Keyboard Studio as an AppImage:
#   1. PyInstaller freezes the app into a one-folder bundle
#   2. the bundle goes into an AppDir with AppRun, a .desktop file and an icon
#   3. appimagetool packs the AppDir into a single runnable file
#
#   pip install -r packaging/requirements-build.txt
#   packaging/build-appimage.sh [version]      # -> dist/Keyboard_Studio-<version>-x86_64.AppImage
#
# Set APPIMAGETOOL to use an existing appimagetool; otherwise it is downloaded.
set -euo pipefail

cd "$(dirname "$0")/.."
VERSION="${1:-$(git describe --tags --always --dirty 2>/dev/null || echo dev)}"
ARCH="${ARCH:-x86_64}"
PYTHON="${PYTHON:-python3}"
BUILD=build
APPDIR="$BUILD/AppDir"
OUT="dist/Keyboard_Studio-${VERSION}-${ARCH}.AppImage"

echo "==> freezing with PyInstaller"
rm -rf "$BUILD/pyinstaller" dist/keyboard-studio "$APPDIR"
"$PYTHON" -m PyInstaller --noconfirm --clean \
    --distpath dist --workpath "$BUILD/pyinstaller" packaging/keyboard-studio.spec

echo "==> assembling the AppDir"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/keyboard-studio "$APPDIR/usr/lib/keyboard-studio"
install -m 0755 packaging/AppRun "$APPDIR/AppRun"
install -m 0644 packaging/keyboard-studio.desktop "$APPDIR/keyboard-studio.desktop"
install -m 0644 packaging/keyboard-studio.desktop "$APPDIR/usr/share/applications/"
install -m 0644 packaging/keyboard-studio.png "$APPDIR/keyboard-studio.png"
install -m 0644 packaging/keyboard-studio.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
ln -sf keyboard-studio.png "$APPDIR/.DirIcon"

TOOL="${APPIMAGETOOL:-$BUILD/appimagetool-${ARCH}.AppImage}"
if [ ! -x "$TOOL" ]; then
    echo "==> downloading appimagetool"
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    chmod +x "$TOOL"
fi

echo "==> packing $OUT"
mkdir -p dist
# extract-and-run: works without FUSE (CI containers, minimal systems)
ARCH="$ARCH" APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" "$OUT"
ls -lh "$OUT"
du -sh dist/keyboard-studio | sed 's/^/unpacked: /'

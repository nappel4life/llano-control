#!/usr/bin/env bash
# Baut die AppImage fuer Linux: eine Datei, die auf jeder Distribution laeuft.
#
#   packaging/build-appimage.sh          # Ergebnis in out/
#
# Noetig sind PyInstaller und PyQt6 in der Umgebung (pip install pyinstaller
# pyqt6) sowie ein Netzwerkzugriff, falls appimagetool geholt werden muss.
# Das Ergebnis heißt llano-control-<Version>-x86_64.AppImage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/out"
APPDIR="$OUT/llano-control.AppDir"
ARCH="${ARCH:-x86_64}"
NAME="llano-control"

cd "$ROOT"
VERSION="${VERSION:-$(python3 -c 'import llanotool; print(llanotool.__version__)')}"
echo "== llano-control $VERSION =="

PYINSTALLER="${PYINSTALLER:-pyinstaller}"
if ! command -v "$PYINSTALLER" >/dev/null 2>&1; then
    echo "PyInstaller fehlt: pip install pyinstaller" >&2
    exit 1
fi

echo "-- Programmdateien"
rm -rf "$ROOT/dist" "$ROOT/build" "$APPDIR"
"$PYINSTALLER" --noconfirm --clean --distpath "$ROOT/dist" "$ROOT/packaging/llano.spec"

echo "-- AppDir"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
         "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo"
cp -a "$ROOT/dist/$NAME/." "$APPDIR/usr/lib/$NAME"

cp "$ROOT/assets/llano.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/$NAME.svg"
cp "$ROOT/assets/llano.svg" "$APPDIR/$NAME.svg"
cp "$ROOT/assets/llano.png" "$APPDIR/$NAME.png"
cp "$ROOT/assets/llano.png" "$APPDIR/.DirIcon"

# Damit ein Softwarezentrum die AppImage nicht als namenlos zeigt.
source "$ROOT/packaging/appdata.sh"
write_appdata "$ROOT/contrib/llano-control.appdata.xml" \
    "$APPDIR/usr/share/metainfo/$NAME.appdata.xml" "$VERSION"

cat > "$APPDIR/$NAME.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=llano Control
GenericName=Notebookkuehler
Comment=Luefterkurve, LEDs und Effekte des llano V12 Ultra
Exec=llano-control %U
Icon=llano-control
Terminal=false
Categories=System;Settings;HardwareSettings;
StartupNotify=true
DESKTOP

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
# Ohne Angabe oeffnet die AppImage die Oberflaeche. Ein Anfang mit "-" gehoert
# auch der Oberflaeche (--tray, --minimized); alles andere ist Kommandozeile:
#   ./llano-control.AppImage
#   ./llano-control.AppImage --tray
#   ./llano-control.AppImage fan 60
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/usr/lib/llano-control"
if [ "$#" -eq 0 ]; then
    exec "$HERE/llano-control"
fi
case "$1" in
    -*) exec "$HERE/llano-control" "$@" ;;
    *)  exec "$HERE/llano" "$@" ;;
esac
APPRUN
chmod +x "$APPDIR/AppRun"

echo "-- appimagetool"
TOOL="${APPIMAGETOOL:-}"
if [ -z "$TOOL" ]; then
    # Absichtlich nicht in out/, damit das Werkzeug nicht mit den fertigen
    # Dateien in die Veroeffentlichung wandert.
    mkdir -p "$ROOT/.bau"
    TOOL="$ROOT/.bau/appimagetool-$ARCH.AppImage"
    if [ ! -x "$TOOL" ]; then
        curl -fsSL -o "$TOOL" \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
        chmod +x "$TOOL"
    fi
fi

OUTPUT="$OUT/$NAME-$VERSION-$ARCH.AppImage"
rm -f "$OUTPUT"
# Kein FUSE noetig auf Bau-Servern.
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUTPUT"

ls -lh "$OUTPUT"
echo "Fertig: $OUTPUT"
echo "Ausfuehren: chmod +x '$OUTPUT' && './$OUTPUT'"

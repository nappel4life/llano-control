#!/usr/bin/env bash
# Baut die tragbare Datei fuer Linux: ein Ordner mit Programm, entpacken und
# laufen lassen. Kein FUSE, kein AppImage-Dienst, nichts zum Installieren -
# praktisch auf Distributionen ohne libfuse2 (Arch und CachyOS zum Beispiel).
#
#   packaging/build-portable.sh            # Ergebnis in out/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/out"
NAME="llano-control"
ARCH="$(uname -m)"

cd "$ROOT"
VERSION="${VERSION:-$(python3 -c 'import llanotool; print(llanotool.__version__)')}"
STAGE="$OUT/$NAME-$VERSION-linux-$ARCH"

PYINSTALLER="${PYINSTALLER:-pyinstaller}"
command -v "$PYINSTALLER" >/dev/null 2>&1 || {
    echo "PyInstaller fehlt: pip install pyinstaller" >&2; exit 1; }

echo "-- Programmdateien"
rm -rf "$ROOT/dist" "$ROOT/build" "$STAGE"
"$PYINSTALLER" --noconfirm --clean --distpath "$ROOT/dist" "$ROOT/packaging/llano.spec"

echo "-- Tragbare Mappe"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a "$ROOT/dist/$NAME/." "$STAGE/"
cp "$ROOT/LICENSE" "$STAGE/"

cat > "$STAGE/llano-gui" <<'LAUNCH'
#!/usr/bin/env bash
# Oberflaeche starten: ./llano-gui   (oder ./llano-control/llano-control)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/llano-control" "$@"
LAUNCH

cp "$ROOT/contrib/70-llano.rules" "$STAGE/"

cat > "$STAGE/ANLEITUNG.txt" <<'TEXT'
llano Control - tragbare Ausgabe fuer Linux

Es ist nichts zu installieren. Aus diesem Ordner heraus:

  ./llano-gui              Oberflaeche starten (auch mit --tray)
  ./llano status           was macht der Kuehler gerade?
  ./llano selftest         kann dieser Rechner den Kuehler?
  ./llano fan 60           Luefter auf 60 Prozent

Der Kuehler ist eine USB-HID-App (374a:b101). Unter Linux braucht der
angemeldete Benutzer Rechte fuer /dev/hidraw*; die Regel dazu liegt bei:

  sudo cp 70-llano.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules && sudo udevadm trigger

Danach den Stecker einmal abziehen und wieder stecken. Ob es geklappt hat:
./llano selftest

Fuer die Oberflaeche ist Qt mit seinen X11-/Wayland-Bibliotheken im Ordner
schon enthalten; auf dem Rechner selbst fehlen hochstens die
X11-Werkzeugbibliotheken, und die hat ein Schreibtisch-System ohnehin.
TEXT
chmod +x "$STAGE/llano-gui"

mkdir -p "$OUT"
tar -C "$OUT" -czf "$OUT/$NAME-$VERSION-linux-$ARCH.tar.gz" "$NAME-$VERSION-linux-$ARCH"
rm -rf "$STAGE"
ls -lh "$OUT/$NAME-$VERSION-linux-$ARCH.tar.gz"

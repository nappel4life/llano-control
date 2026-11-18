#!/usr/bin/env bash
# Baut eine .deb-Datei fuer Debian, Ubuntu und verwandte Distributionen.
#
#   packaging/build-deb.sh                 # Ergebnis in out/
#
# Noetig ist dpkg-deb (gehört zu dpkg). Die udev-Regel wandert mit ins Paket,
# damit der Kuehler nach dem Einstecken sofort dem angemeldeten Benutzer gehört.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/out"
NAME="llano-control"
MAINTAINER="${MAINTAINER:-nappel4life}"
EMAIL="${EMAIL:-27081473+nappel4life@users.noreply.github.com}"
ARCH="${DEB_ARCH:-all}"

cd "$ROOT"
VERSION="${VERSION:-$(python3 -c 'import llanotool; print(llanotool.__version__)')}"
PREFIX="$OUT/${NAME}_${VERSION}_${ARCH}"
PKG="$PREFIX/${NAME}"

command -v dpkg-deb >/dev/null 2>&1 || { echo "dpkg-deb fehlt (Paket dpkg)." >&2; exit 1; }

echo "== $NAME $VERSION =="
rm -rf "$PREFIX"
mkdir -p "$PKG/DEBIAN" \
         "$PKG/usr/bin" \
         "$PKG/usr/lib/$NAME" \
         "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/scalable/apps" \
         "$PKG/usr/share/doc/$NAME" \
         "$PKG/usr/share/metainfo" \
         "$PKG/usr/lib/udev/rules.d"

echo "-- Paketinhalt"
cp -a "$ROOT/llanotool" "$PKG/usr/lib/$NAME/"
find "$PKG/usr/lib/$NAME" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp -a "$ROOT/assets" "$PKG/usr/lib/$NAME/"
cp -a "$ROOT/contrib" "$PKG/usr/lib/$NAME/"
cp "$ROOT/README.md" "$PKG/usr/lib/$NAME/"

cat > "$PKG/usr/bin/llano" <<'WRAPPER'
#!/usr/bin/env bash
# llano V12 Ultra Steuerung, installiert als Paket.
exec /usr/bin/python3 "/usr/lib/llano-control/llano-entry.py" "$@"
WRAPPER

cat > "$PKG/usr/lib/$NAME/llano-entry.py" <<'ENTRY'
#!/usr/bin/python3
"""Einstiegspunkt fuer die Installation unter /usr/lib/llano-control."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llanotool.cli import main

if __name__ == "__main__":
    sys.exit(main())
ENTRY
chmod 755 "$PKG/usr/bin/llano" "$PKG/usr/lib/$NAME/llano-entry.py"

sed "s|^Exec=.*|Exec=/usr/bin/llano gui|" "$ROOT/contrib/llano-control.desktop" \
    > "$PKG/usr/share/applications/$NAME.desktop"
cp "$ROOT/assets/llano.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/$NAME.svg"
cp "$ROOT/contrib/70-llano.rules" "$PKG/usr/lib/udev/rules.d/70-llano.rules"

# Die AppStream-Datei ist das, was ein Softwarezentrum ueber das Programm
# erzaehlt: Kurzbeschreibung, Lizenz, ein Bild.
source "$ROOT/packaging/appdata.sh"
write_appdata "$ROOT/contrib/llano-control.appdata.xml" \
    "$PKG/usr/share/metainfo/$NAME.appdata.xml" "$VERSION"
install -m 644 "$ROOT/LICENSE" "$PKG/usr/share/doc/$NAME/copyright"
gzip -9nc "$ROOT/README.md" > "$PKG/usr/share/doc/$NAME/README.md.gz"

echo "-- control"
SIZE="$(du -sk "$PKG" --exclude=DEBIAN | cut -f1)"
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: $NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Installed-Size: $SIZE
Maintainer: $MAINTAINER <$EMAIL>
Depends: python3 (>= 3.10)
Recommends: python3-pyqt6
Homepage: https://github.com/nappel4life/llano-control
Description: Steuerung des llano V12 Ultra Notebookkuehlers
 Der Notebookkuehler llano V12 Ultra (USB 374a:b101) haelt unter Windows nur
 die Herstellersoftware "MythCool". Dieses Paket steuert ihn unter Linux:
 Lueftergeschwindigkeit in Abhaengigkeit von den Temperaturensoren des
 Notebooks, dazu Farben, Effekte, Takt und Helligkeit der LEDs.
 .
 Kommandozeile, Hintergrunddienst und Qt-Oberflaeche; die udev-Regel liegt
 bei, damit der angemeldete Benutzer das Geraet ohne Root ansprechen darf.
CONTROL

cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
# Die udev-Regel gilt erst, nachdem udev sie neu gelesen hat und der Stecker
# einmal ab und wieder angesteckt wurde.
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
fi
echo "llano: USB-Stecker des Kuehlers einmal ziehen und wieder stecken, dann"
echo "llano: llano status. Die Oberflaeche startet mit: llano gui"
exit 0
POST
cat > "$PKG/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
fi
exit 0
PRERM
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm"

OUTPUT="$OUT/${NAME}_${VERSION}_${ARCH}.deb"
rm -f "$OUTPUT"
# XZ statt des Voreinstellungs: das koennen auch aeltere dpkg-Fassungen lesen,
# und die paketierten Dateien sind damit nicht groesser.
dpkg-deb --build --root-owner-group -Zxz "$PKG" "$OUTPUT"
ls -lh "$OUTPUT"
echo "Fertig: $OUTPUT"

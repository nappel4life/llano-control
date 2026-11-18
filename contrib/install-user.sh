#!/usr/bin/env bash
# Tragt die llano-Oberflaeche ein: ins KDE-Menue, optional in den Autostart und
# optional als Dienst, der den Kuehler beim Anmelden ein- und beim
# Herunterfahren ausschaltet.
#
#   contrib/install-user.sh                      -> Menueeintrag + Symbol
#   contrib/install-user.sh --autostart          -> ausserdem beim Anmelden starten
#   contrib/install-user.sh --power              -> ausserdem Ein/Aus-Dienst
#   contrib/install-user.sh --autostart --power  -> beides zusammen
#   contrib/install-user.sh --remove             -> alles wieder entfernen
#
# Alles davon liegt im eigenen Benutzerkonto, nichts unter /etc.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="llano-power.service"

autostart=false
power=false

for argument in "$@"; do
    case "$argument" in
        --autostart) autostart=true ;;
        --power)     power=true ;;
        --remove)
            rm -f "$ICON_DIR/llano-control.svg" \
                  "$APPS_DIR/llano-control.desktop" \
                  "$AUTOSTART_DIR/llano-control.desktop"
            systemctl --user disable --now "$UNIT" 2>/dev/null || true
            rm -f "$UNIT_DIR/$UNIT"
            systemctl --user daemon-reload 2>/dev/null || true
            echo "entfernt."
            exit 0 ;;
        *) echo "Unbekannte Option: $argument  (moeglich: --autostart, --power, --remove)" >&2
           exit 1 ;;
    esac
done

mkdir -p "$ICON_DIR" "$APPS_DIR"

cp "$ROOT/assets/llano.svg" "$ICON_DIR/llano-control.svg"
# Der Menüeintrag zeigt auf dieses Auschecken; nach einem Umzug einfach noch
# einmal aufrufen, dann steht dort der neue Weg.
sed "s|^Exec=.*|Exec=$ROOT/llano gui|" "$ROOT/contrib/llano-control.desktop" \
    > "$APPS_DIR/llano-control.desktop"
chmod +x "$ROOT/llano"

if $autostart; then
    mkdir -p "$AUTOSTART_DIR"
    sed "s|^Exec=.*|Exec=$ROOT/llano gui|" "$ROOT/contrib/llano-control.desktop" \
        > "$AUTOSTART_DIR/llano-control.desktop"
    echo "Autostart aktiv: die Steuerung faehrt beim naechsten Anmelden hoch."
else
    rm -f "$AUTOSTART_DIR/llano-control.desktop"
fi

if $power; then
    mkdir -p "$UNIT_DIR"
    cp "$ROOT/contrib/llano-power.service" "$UNIT_DIR/$UNIT"
    systemctl --user daemon-reload
    # --now schaltet den Kuehler auch gerade eben ein, nicht erst beim naechsten Mal.
    systemctl --user enable --now "$UNIT"
    echo "Ein/Aus-Dienst aktiv: Kuehler beim Anmelden an, beim Abmelden und"
    echo "beim Herunterfahren aus. Nachzusehen mit: systemctl --user status $UNIT"
fi

# Symbol-Thema neu einlesen, falls das Werkzeug vorhanden ist.
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "menueeintrag: $APPS_DIR/llano-control.desktop"
echo "symbol:       $ICON_DIR/llano-control.svg"
echo "Start:        $ROOT/llano gui"

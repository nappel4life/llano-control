#!/usr/bin/env bash
# AppStream-Datei fuer Programmstarter und Softwarezentren. Die Vorlage liegt in
# contrib/, dieses Skript setzt nur die Versionszeile ein, damit in einer
# fertigen Datei nicht die Version von vorgestern steht.
#
# Benennung: BUILD_DATE (JJJJ-MM-TT) uebernehmen Bau-Umgebungen, die es genau
# wissen wollen; sonst gilt der Tag des Baus.

write_appdata() {
    local quelle="$1" ziel="$2" version="$3" datum
    datum="${BUILD_DATE:-$(date +%F)}"

    [ -f "$quelle" ] || { echo "AppStream-Vorlage fehlt: $quelle" >&2; return 1; }

    mkdir -p "$(dirname "$ziel")"
    sed "s|<!-- RELEASES -->|<releases><release version=\"$version\" date=\"$datum\" /></releases>|" \
        "$quelle" > "$ziel"

    # Die Markierung muss verschwunden sein, sonst steht sie spaeter in jedem
    # Softwarezentrum mit drin.
    if grep -qF "<!-- RELEASES -->" "$ziel"; then
        echo "AppStream-Markierung nicht ersetzt" >&2
        return 1
    fi
    return 0
}

#!/usr/bin/env python3
"""Schreibt die Byte-Folien, an denen beide Fassungen gemessen werden.

Dieses Programm ist die Bruecke zwischen der Python-Fassung, die am echten
Kuehler gemessen wurde, und der Rust-Fassung, die noch nicht am Geraet war:
Beide muessen am Ende exakt dieselben neun Byte auf den Bus legen und
dieselben neun Byte gleich lesen. Wer nur die eine Implementierung gegen die
andere prueft, bestaetigt hoechstens, dass beide denselben Denkfehler haben.

Aufruf:

    python3 tools/protokoll-vektoren.py            # schreibt tests/byte-vektoren.json
    python3 tools/protokoll-vektoren.py --pruefen  # unveraendert? (fuer den Bau)

Die Datei enthaelt absichtlich nur Zahlen und Namen, keine Kommentare: Sie
landet in beiden Sprachen als Daten, nicht als Code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llanotool import protocol  # noqa: E402

ZIEL = Path(__file__).resolve().parent.parent / "tests" / "byte-vektoren.json"


def bytes_text(daten: bytes) -> str:
    return " ".join(f"{b:02x}" for b in daten)


def schreibe_vektoren() -> dict:
    """Alle Faelle, die ein Bericht kennen muss."""
    faelle = [
        # Name, Befehl, Parameter
        ("stufe eins", "luefter", {"speed": 1, "color": 0}),
        ("stufe vierzig gruen", "luefter", {"speed": 40, "color": 2}),
        ("stufe hundert", "luefter", {"speed": 100, "color": 2}),
        ("zu niedrig wird auf eins gehoben", "luefter", {"speed": 0, "color": 2}),
        ("zu hoch wird gedeckelt", "luefter", {"speed": 150, "color": 2}),
        ("duester und aus", "luefter", {
            "speed": 55, "color": 3, "effect": 4, "effect_speed": 3,
            "brightness": 0, "light_on": False, "powered_on": False,
        }),
        ("beleuchtung laesst die Stufe stehen", "beleuchtung", {
            "fan_speed": 66, "color": 3, "effect": 1, "effect_speed": 2,
            "brightness": 128,
        }),
        ("beleuchtung mit Stufe null", "beleuchtung", {
            "fan_speed": 0, "color": 0, "effect": 0, "brightness": 255,
        }),
        ("beleuchtung aus mit Effekt", "beleuchtung", {
            "fan_speed": 25, "color": 4, "effect": 2, "effect_speed": 1,
            "brightness": 200, "light_on": False,
        }),
        ("volle Helligkeit", "beleuchtung", {
            "fan_speed": 33, "color": 1, "effect": 0, "brightness": 0xFF,
        }),
    ]

    schreiben = []
    for name, befehl, parameter in faelle:
        if befehl == "luefter":
            bericht = protocol.build_fan_report(**parameter)
        else:
            bericht = protocol.build_light_report(**parameter)
        schreiben.append({
            "name": name,
            "befehl": befehl,
            "parameter": parameter,
            "bytes": bytes_text(bericht),
        })

    pruefsummen = []
    for bericht in schreiben:
        koerper = bytes.fromhex(bericht["bytes"].replace(" ", ""))[1:8]
        pruefsummen.append({
            "koerper": bytes_text(koerper),
            "summe": f"{protocol.checksum(koerper):02x}",
        })

    lesen = []
    for name, _befehl, parameter in faelle:
        # Jeder geschrieben Bericht ist auch ein moeglicher Lesebericht: Das
        # Geraet antwortet mit demselben Aufbau.
        if _befehl == "luefter":
            bericht = protocol.build_fan_report(**parameter)
        else:
            bericht = protocol.build_light_report(**parameter)
        zustand = protocol.parse_state(bericht)
        lesen.append({
            "name": name,
            "bytes": bytes_text(bericht),
            "zustand": {
                "mode": zustand.mode,
                "fan_speed": zustand.fan_speed,
                "rpm_anzeige": zustand.rpm_display,
                "powered_on": zustand.powered_on,
                "light_on": zustand.light_on,
                "effect": zustand.effect,
                "effect_name": zustand.effect_name,
                "color": zustand.color,
                "color_name": zustand.color_name,
                "effect_speed": zustand.effect_speed,
                "brightness": zustand.brightness,
            },
        })

    # Der Modus, den die Herstellersoftware setzt, wenn ihr eigenes Rad dreht.
    bericht = bytes([0x00, 0x88, 62, 0x00, 0x01, 0x02, 0x01, 0x00])
    bericht = bericht[:8] + bytes([protocol.checksum(bericht[1:8])])
    zustand = protocol.parse_state(bericht)
    lesen.append({
        "name": "antwort des eigenen Drehrads",
        "bytes": bytes_text(bericht),
        "zustand": {
            "mode": zustand.mode,
            "fan_speed": zustand.fan_speed,
            "rpm_anzeige": zustand.rpm_display,
            "powered_on": zustand.powered_on,
            "light_on": zustand.light_on,
            "effect": zustand.effect,
            "effect_name": zustand.effect_name,
            "color": zustand.color,
            "color_name": zustand.color_name,
            "effect_speed": zustand.effect_speed,
            "brightness": zustand.brightness,
        },
    })

    # Kaputte Berichte muessen in beiden Fassungen abgewiesen werden.
    guter = bytes([0x00, 0x01, 0x28, 0x00, 0x00, 0x00, 0x00, 0xFF])
    guter = guter[:8] + bytes([protocol.checksum(guter[1:8])])
    falsche_summe = bytearray(guter)
    falsche_summe[8] ^= 0xFF
    zurueckweisen = [
        {"name": "zu kurz", "bytes": bytes_text(guter[:7]), "grund": "zu kurz"},
        {"name": "Summe verdreht", "bytes": bytes_text(bytes(falsche_summe)),
         "grund": "pruefsumme"},
    ]

    return {
        "erklaerung": (
            "Erzeugt von tools/protokoll-vektoren.py aus der am Geraet "
            "geprueften Python-Fassung. Beide Fassungen muessen diese "
            "Berichte Byte fuer Byte bauen und gleich lesen."
        ),
        "protokoll": {
            "vendor_id": protocol.VENDOR_ID,
            "product_id": protocol.PRODUCT_ID,
            "koerper_laenge": protocol.BODY_LEN,
            "puffer_laenge": protocol.BUFFER_LEN,
            "befehl_beleuchtung": protocol.CMD_LIGHT,
            "befehl_luefter": protocol.CMD_FAN,
            "effekt_aus_flag": protocol.LIGHT_OFF_FLAG,
            "farben": protocol.COLORS,
            "effekte": protocol.EFFECTS,
        },
        "pruefsummen": pruefsummen,
        "schreiben": schreiben,
        "lesen": lesen,
        "zurueckweisen": zurueckweisen,
    }


def main() -> int:
    daten = schreibe_vektoren()
    text = json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if "--pruefen" in sys.argv:
        if ZIEL.exists() and ZIEL.read_text(encoding="utf-8") == text:
            print("Byte-Folien unveraendert.")
            return 0
        print("Die Byte-Folien passen nicht mehr zum Python-Protokoll: "
              "tools/protokoll-vektoren.py erneut aufrufen und die Datei "
              "mitschicken.", file=sys.stderr)
        return 1
    ZIEL.write_text(text, encoding="utf-8")
    print(f"{ZIEL}: {len(daten['schreiben'])} Schreib- und "
          f"{len(daten['lesen'])} Leseberichte, "
          f"{len(daten['zurueckweisen'])} abzuweisende.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

from llanotool import config as config_mod  # noqa: E402
from llanotool import protocol  # noqa: E402
from llanotool.curve import CurveFollower, interpolate  # noqa: E402

ZIEL = Path(__file__).resolve().parent.parent / "tests" / "byte-vektoren.json"


def bytes_text(daten: bytes) -> str:
    return " ".join(f"{b:02x}" for b in daten)


def kurven_vektoren() -> dict:
    """Was die Kurve aus Temperaturen macht - fur beide Fassungen.

    Die Werte stammen aus der Python-Fassung, nicht aus einem Kopf: Wer die
    Rundung oder die Hysterese andert, andert diese Datei mit, und die
    Rust-Prufung fallt auf, statt dass beide Implementierungen still
    auseinanderlaufen. Die Zwischenfaelle mit der halben Prozentstufe sind
    absichtlich dabei - Python rundet zur geraden Zahl, Rust wurde von der Null
    weg runden, und genau dazwischen liegt der Unterschied.
    """
    standard = config_mod.DEFAULTS["curve"]
    faelle = [
        ("standardkurve", standard,
         [20.0, 44.9, 45.0, 50.0, 55.0, 60.0, 65.5, 70.0, 91.9, 92.0, 200.0]),
        ("halbe Prozentstufe", [[40, 25], [42, 28]],
         [40.0, 40.5, 41.0, 41.5, 42.0]),
        ("gerade und ungerade Mischung", [[40, 26], [42, 27]],
         [40.0, 41.0, 41.999, 42.0]),
        ("zwei Punkte", [[30, 6], [80, 60]], [20.0, 30.0, 55.0, 80.0, 99.0]),
        ("flacher Verlauf", [[40, 20], [40.5, 20], [90, 21]], [39.0, 40.2, 60.0, 95.0]),
    ]
    interpolation = [
        {"name": name, "kurve": kurve, "grad": grad, "stufe": interpolate(kurve, grad)}
        for name, kurve, temperaturen in faelle
        for grad in temperaturen
    ]

    folgen = [
        ("drei Grad Hysterese", standard, 3.0,
         [60.0, 70.0, 68.0, 67.0, 66.0, 62.0, 45.0]),
        ("keine Hysterese", standard, 0.0, [70.0, 68.0, 66.0]),
        ("grosser Abstand", standard, 12.0, [80.0, 70.0, 60.0, 50.0]),
        ("erst kalt dann heiss", [[30, 6], [80, 60]], 3.0,
         [30.0, 31.0, 79.0, 80.0, 55.0, 50.0]),
    ]
    verfolgung = []
    for name, kurve, hysterese, messungen in folgen:
        folger = CurveFollower(kurve, hysterese)
        verfolgung.append({
            "name": name,
            "kurve": kurve,
            "hysterese": hysterese,
            "messungen": messungen,
            "stufen": [folger.update(grad) for grad in messungen],
        })

    return {"interpolation": interpolation, "verfolgung": verfolgung}


def einstellungs_vektoren() -> dict:
    """Die Standardwerte und die Kurvennachschau, wie Python sie trifft."""
    rohfaelle = [
        ("leer", []),
        ("ein Punkt", [[70, 40]]),
        ("unsortiert", [[70, 40], [45, 20], [55, 30]]),
        ("zu hoch und zu niedrig", [[60, 900], [40, -5]]),
        ("Buchstaben dabei", [[70, 40], ["warm", 5], [50, None]]),
        ("Zahlen als Text", [["60", "80"]]),
        ("null Punkte uebrig", [[None, None], ["x", "y"]]),
        ("gleiche Temperatur", [[60, 30], [60, 40]]),
    ]
    return {
        "standardwerte": config_mod._normalise_curve(config_mod.DEFAULTS["curve"]),
        "schluessel": sorted(config_mod.DEFAULTS),
        "kurven_normierung": [
            {"name": name, "roh": roh, "erwartet": config_mod._normalise_curve(roh)}
            for name, roh in rohfaelle
        ],
    }


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
        "kurve": kurven_vektoren(),
        "einstellungen": einstellungs_vektoren(),
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
          f"{len(daten['zurueckweisen'])} abzuweisende, "
          f"{len(daten['kurve']['interpolation'])} Kurvenwerte und "
          f"{len(daten['kurve']['verfolgung'])} Hysterese-Verlaeufe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Ein nachgebauter Messhelfer fuer die Pruefungen.

Die echte Bruecke ist ein Windows-Programm; ein Prueflauf hier hat keines.
Dieses Skript spricht dieselbe Zeilenfolge und kann die Faelle spielen, die am
echten Geraet sonst erst nach einem Feldbericht auffielen: der Helfer, der
nichts meldet, der Helfer, an dem die Laufzeit scheitert, und der Helfer, der
gleich wieder geht.

Es haengt an seiner Standardeingabe wie das echte Programm: zu, und es geht.

  python3 tests/helfer_probeweise.py [--einmal|--sofort|--kaputt|--fehler|--bleibt]
"""

import argparse
import json
import sys
import time

START = {"art": "start", "erhoeht": True, "treiber": True,
         "treiber_fassung": "2.0.9", "bibliothek": "0.9.6.0", "geraete": 3,
         "takt": 1000}

WERTE = [
    {"geraet": "CPU", "messstelle": "CPU (Package)", "wert": 54.0},
    {"geraet": "CPU", "messstelle": "Core #0", "wert": 55.0},
    {"geraet": "CPU", "messstelle": "Core #1", "wert": 57.0},
    {"geraet": "GPU", "messstelle": "GPU Hot Spot", "wert": 66.0},
    {"geraet": "Mainboard", "messstelle": "Nichts", "wert": None},
    {"geraet": "Mainboard", "messstelle": "Frost", "wert": -12.0},
]


def schreibe(daten) -> None:
    sys.stdout.write(json.dumps(daten, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def abschied() -> None:
    """Die Standardeingabe ist der Kanarienvogel: zu heisst Abschied."""
    try:
        while sys.stdin.read(1):
            pass
    except (OSError, ValueError):
        return


def main() -> int:
    befehl = argparse.ArgumentParser(add_help=False)
    befehl.add_argument("--einmal", action="store_true")
    befehl.add_argument("--sofort", action="store_true")
    befehl.add_argument("--kaputt", action="store_true")
    befehl.add_argument("--fehler", action="store_true")
    befehl.add_argument("--bleibt", action="store_true")
    befehl.add_argument("--takt", type=int, default=1000)
    args, _ = befehl.parse_known_args()

    if args.kaputt:
        sys.stderr.write("The process cannot find the runtime 'mscoree.dll'.\n")
        sys.stderr.flush()
        return 3
    if args.fehler:
        schreibe({"art": "fehler",
                  "text": "TypeInitializationException: Treiber abgelehnt"})
        return 2

    schreibe(START)
    if args.sofort:
        return 0
    schreibe({"art": "werte", "zeit": int(time.time()), "temperaturen": WERTE})
    if args.einmal:
        return 0
    abschied()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

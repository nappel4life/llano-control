"""Startpunkt fuer die fertige Programmdatei der Oberflaeche.

Dasselbe Kommando wie in der Kommandozeile, nur mit vorangesetztem
``gui``, damit ein Doppelklick auf die Datei die Oberflaeche oeffnet und nicht
die Hilfetexte. Alles dahinter geht durch: ``llano-control.exe --tray``.
"""

from __future__ import annotations

import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llanotool.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["gui", *sys.argv[1:]]))

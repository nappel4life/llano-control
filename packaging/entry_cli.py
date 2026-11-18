"""Startpunkt fuer die fertige Programmdatei der Kommandozeile.

PyInstaller braucht ein Skript zum Analysieren; dieses hier weiterzugeben ist
der ganze Trick. Der Anfang des Suchpfads sorgt dafuer, dass die Datei auch
ohne Installation aus dem Projektordner heraus laeuft.
"""

from __future__ import annotations

import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llanotool.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

"""Der eine Griff, an dem die Windows-Suche bisher gescheitert ist.

Windows legt den Schnittstellenpfad als UTF-16 in einen Puffer und beendet ihn
mit einem weiten Nullzeichen. Nach zwei Nullbyte zu suchen findet dieses Ende
einen Byte zu frueh: Das obere Byte des letzten Zeichens ist bei ASCII selbst
null und liegt direkt neben dem unteren Byte des Endzeichens. Ueber bleibt ein
ungerader Rest, der nicht mehr zu decodieren ist.

Die Folge war auf einem echten Windows zu sehen: Die Aufzaehlung zahlte ihre
Schnittstellen, las aber keine einzige, und zurueck blieb "kein Geraet" auf
einem Rechner, dessen Tastatur die meinte. Deshalb steht das Lesen hier; die
Windows-Fassung ruft genau diese Funktion.
"""

import unittest

from llanotool.device_common import wide_text

BEISPIELPFAD = (r"\\?\hid#vid_374a&pid_b101#7&1eb58206&0&0000"
                r"#{4d1e55b2-f16f-11cf-88cb-001111000030}")


def puffer(pfad: str) -> bytes:
    """Ein Schnittstellenpfad, so wie Windows ihn hinlegt: vier Byte Groessen-
    angabe, der Text, ein weites Nullzeichen, dann nur noch Nullbyte."""
    return (b"\x08\x00\x00\x00" + pfad.encode("utf-16-le") + b"\x00\x00"
            + bytes(4096))


class Schnittstellenpfad(unittest.TestCase):
    def test_der_pfad_vom_Geraet(self):
        self.assertEqual(wide_text(puffer(BEISPIELPFAD)), BEISPIELPFAD)

    def test_gerade_und_ungerade_lange_Pfade(self):
        """Auf die Zeichenzahl kommt es an, nicht auf die Bytezahl."""
        for breite in (1, 2, 3, 4, 40, 41):
            with self.subTest(breite=breite):
                self.assertEqual(wide_text(puffer("h" * breite)), "h" * breite)

    def test_Umlaute_bleiben_wie_sie_sind(self):
        pfad = r"\\?\hid#v12-ultra-üöä"
        self.assertEqual(wide_text(puffer(pfad)), pfad)

    def test_nichts_ist_leer_und_kein_Fehler(self):
        self.assertEqual(wide_text(bytes(64)), "")

    def test_auch_ohne_Groessenangabe_direkt_am_Text(self):
        text = BEISPIELPFAD.encode("utf-16-le") + b"\x00\x00" + bytes(32)
        self.assertEqual(wide_text(text, 0), BEISPIELPFAD)


if __name__ == "__main__":                          # pragma: no cover
    unittest.main()

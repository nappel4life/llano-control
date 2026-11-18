"""Die Windows-Strukturen in ihrer echten Groesse.

Jede dieser Strukturen fuellt eine Windows-Bibliothek bis zu ihrem eigenen Ende
und fragt nicht, wie lang das Gegenueber ist. Eine zu kurz nachgebaute Struktur
bekommt dann mehr ab, als sie fassen kann, zerstoert ihren Nachbarn im Speicher
und faellt spaeter an ganz anderer Stelle um - so ist die Oberflaeche beim
Fensterbauen umgekippt, mit einer Zugriffsverletzung beim Aufraeumen.

Deshalb stehen hier die Groessen fest, nicht die Inhalte: Wer eine Struktur
kuerzer macht, muss erst diese Pruefungen umschreiben.
"""

import ctypes
import sys
import unittest

NUR_WINDOWS = unittest.skipUnless(sys.platform == "win32",
                                  "Windows holt sich seine Bibliotheken selbst")


@NUR_WINDOWS
class Strukturgroessen(unittest.TestCase):
    def setUp(self):
        from llanotool import device_windows
        self.geraet = device_windows

    def test_kapazitaeten_fassen_die_ganze_struktur(self):
        # HidP_GetCaps schreibt 64 Byte, neuere Windows-Fassungen 66. Weniger
        # war hier nachgebaut - der Rest ging in den Nachbarn.
        self.assertGreaterEqual(ctypes.sizeof(self.geraet.HIDP_CAPS), 66,
                                "HidP_GetCaps schreibt hinter das Ende des Objekts")

    def test_gelesene_felder_stehen_vorne(self):
        felder = [name for name, _ in self.geraet.HIDP_CAPS._fields_]
        self.assertEqual(felder[:5], ["UsagePage", "Usage", "InputReportByteLength",
                                      "OutputReportByteLength",
                                      "FeatureReportByteLength"])

    def test_ereigniskennung_sitzt_an_der_rechten_Stelle(self):
        # Nach den beiden Zaehlern kommt ein gemeinsamer Platz fuer Versatz und
        # Zeiger, danach die Kennung. Stand dort ein eigenes Feld, fand Windows
        # eine leere Kennung und setzte das Ereignis nie.
        selbst = self.geraet.OVERLAPPED
        self.assertEqual(ctypes.sizeof(selbst), 32)
        self.assertEqual(getattr(selbst, "hEvent").offset, 24)

    def test_geraetekennung_und_schnittstelle_passt(self):
        self.assertEqual(ctypes.sizeof(self.geraet.HIDD_ATTRIBUTES), 8)
        # 4 Byte Groessenangabe, 16 Byte Klassenkennung, 4 Byte Flags, 8 Byte
        # Zeiger - auf 64 Bit, wie der Installer sie ausliefert.
        self.assertEqual(ctypes.sizeof(self.geraet.SP_DEVICE_INTERFACE_DATA), 32)


if __name__ == "__main__":
    unittest.main()

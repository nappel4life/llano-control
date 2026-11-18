"""Der Speicherblock, den HWiNFO unter Windows offen hält, und sein Inhalt.

Darauf zu bauen, was ein anderes Programm in den Speicher schreibt, ist nur mit
zwei Dingen sicher: erstens niemals von eingebauten Groessen ausgehen (der
Block nennt seine eigenen Schrittweiten), zweitens pruefen, was passiert, wenn
die Angaben anders liegen, als es der eigene Rechner gerade zufaellig
vorfindet.

HWiNFO laeuft hier nicht - und ausserhalb von Windows gar nicht. Also werden
die Baetze unten mit einem selbstgebauten Block gespielt: zwei Lagen des
Zeitstempels, verschiedene Polsterungen, Messarten, die keine Temperaturen
sind, und ein Block, der stecken bleibt.
"""

import struct
import unittest

from llanotool import sensors_hwiinfo as hwiinfo

ZEIT = 1_700_000_000


def feld(text: str, laenge: int = 128) -> bytes:
    return text.encode("cp1252")[:laenge].ljust(laenge, b"\x00")


def gruppe(name: str, wie_es_heisst: str = "", groesse: int = 272) -> bytes:
    return (struct.pack("<II", 1, 0) + feld(wie_es_heisst) + feld(name)
            + b"\x00" * (groesse - 8 - 256))


def messwert(art: int, gruppen_nr: int, marke: str, wert: float,
             wie_es_heisst: str = "", groesse: int = 328) -> bytes:
    """Ein Messwert mit den vier Zahlen am Ende, dazwischen Polsterung."""
    anfang = struct.pack("<III", art, gruppen_nr, 7)
    mitte = feld(wie_es_heisst) + feld(marke) + feld("°C", 16)
    zahlen = struct.pack("<dddd", wert, 0.0, 0.0, wert)
    polster = groesse - len(anfang) - len(mitte) - len(zahlen)
    if polster < 0:
        raise ValueError("zu kleiner Messwert fuer diese Polsterung")
    return anfang + mitte + b"\x00" * polster + zahlen


def block(gruppen_liste, werte_liste, zeit_ab: int = 16, messzeit: int = ZEIT,
          groesse_gruppe: int = 272, groesse_wert: int = 328) -> bytes:
    """Ein Block, wie HWiNFO ihn legt - inklusive der Lucke vor dem Zeitstempel.

    Der Zeitstempel ist ein ``__time64_t``: je nach Bausatz liegt er direkt
    hinter den Versionszahlen (12) oder an einer Achtgrenze (16). Beides kommt
    vor, der Leser muss beide finden koennen.
    """
    ab_gruppen = 64
    ab_werte = ab_gruppen + len(gruppen_liste) * groesse_gruppe
    sechs = struct.pack("<IIIIII", ab_gruppen, groesse_gruppe, len(gruppen_liste),
                        ab_werte, groesse_wert, len(werte_liste))
    wenn_ausgerichtet = hwiinfo.SIGNATUR + struct.pack("<II", 4, 0) + b"\x00" * 4
    wenn_dicht = hwiinfo.SIGNATUR + struct.pack("<II", 4, 0)
    kopfteil = ((wenn_ausgerichtet if zeit_ab == 16 else wenn_dicht)
                + struct.pack("<q", messzeit) + sechs)
    return kopfteil.ljust(ab_gruppen, b"\x00") + b"".join(gruppen_liste + werte_liste)


class Vorspann(unittest.TestCase):
    def test_beide_Lagen_des_Zeitstempels(self):
        for zeit_ab in (16, 12):
            with self.subTest(zeit_ab=zeit_ab):
                puffer = block([gruppe("CPU")], [messwert(1, 0, "Package", 54.0)],
                               zeit_ab=zeit_ab)
                angaben = hwiinfo.kopf(puffer)
                self.assertIsNotNone(angaben)
                self.assertEqual(angaben["messzeit"], ZEIT)
                self.assertEqual(angaben["anzahl_werte"], 1)

    def test_fremder_Block_ist_keiner(self):
        self.assertIsNone(hwiinfo.kopf(b"XXXX" + b"\x00" * 200))
        self.assertIsNone(hwiinfo.kopf(b""))
        self.assertEqual(hwiinfo.messwerte(b"Quatsch"), [])

    def test_unsinnige_Menge_wehrt_ab(self):
        puffer = bytearray(block([gruppe("CPU")], [messwert(1, 0, "Package", 54.0)]))
        struct.pack_into("<I", puffer, 44, 900_000)     # versprochene Messwerte
        self.assertIsNone(hwiinfo.kopf(bytes(puffer)))


class Messwerte(unittest.TestCase):
    def test_nur_Temperaturen(self):
        puffer = block([gruppe("CPU")], [
            messwert(1, 0, "Package", 54.0),
            messwert(3, 0, "CPU Fan", 2400.0),          # Luefterdrehzahl
            messwert(6, 0, "Core Clock", 3800.0),       # Takt
            messwert(7, 0, "CPU Total", 33.0),          # Auslastung
        ])
        gefunde = {wert.marke: wert.wert for wert in hwiinfo.messwerte(puffer)}
        self.assertEqual(gefunde, {"CPU Package": 54.0})

    def test_unsinnige_Grade_zaehlen_nicht(self):
        puffer = block([gruppe("CPU")], [
            messwert(1, 0, "Nulle", 0.0),               # bedeutet: nicht vorhanden
            messwert(1, 0, "Kalt", -12.0),
            messwert(1, 0, "Geschmolzen", 301.0),
            messwert(1, 0, "Rechtes Mass", 149.0),
        ])
        self.assertEqual([wert.marke for wert in hwiinfo.messwerte(puffer)],
                         ["CPU Rechtes Mass"])

    def test_eigener_Name_vor_dem_vorgegebenen(self):
        puffer = block([gruppe("CPU-Paket", "CPU")],
                       [messwert(1, 0, "Der eigene Name", 61.0, "Package")])
        wert = hwiinfo.messwerte(puffer)[0]
        self.assertEqual(wert.marke, "CPU-Paket Der eigene Name")
        self.assertEqual(wert.kennung, "hwiinfo:CPU-Paket Der eigene Name")

    def test_Gruppenname_wird_nicht_zweimal_gelegt(self):
        puffer = block([gruppe("CPU")], [messwert(1, 0, "CPU (Package)", 58.0)])
        self.assertEqual(hwiinfo.messwerte(puffer)[0].marke, "CPU (Package)")

    def test_Kernwerte_weichen_dem_Gesamtwert(self):
        puffer = block([gruppe("CPU")], [
            messwert(1, 0, "CPU (Package)", 57.0),
            messwert(1, 0, "Core #1", 55.0),
            messwert(1, 0, "Core #2", 61.0),
            messwert(1, 0, "PCH", 49.0),
        ])
        self.assertEqual([wert.marke for wert in hwiinfo.messwerte(puffer)],
                         ["CPU (Package)", "CPU PCH"])
        self.assertEqual(len(hwiinfo.messwerte(puffer, kerne=True)), 4)

    def test_Kernwerte_bleiben_ohne_Gesamtwert(self):
        puffer = block([gruppe("CPU")], [messwert(1, 0, "Core #1", 55.0),
                                        messwert(1, 0, "Core #2", 61.0)])
        self.assertEqual(len(hwiinfo.messwerte(puffer)), 2)

    def test_Polsterung_ist_gleichgueltig(self):
        knapp = block([gruppe("CPU", groesse=264)],
                      [messwert(1, 0, "Package", 54.0, groesse=316)],
                      groesse_gruppe=264, groesse_wert=316)
        reichlich = block([gruppe("CPU", groesse=280)],
                          [messwert(1, 0, "Package", 54.0, groesse=352)],
                          groesse_gruppe=280, groesse_wert=352)
        for name, puffer in (("knapp", knapp), ("reichlich", reichlich)):
            with self.subTest(polsterung=name):
                wert = hwiinfo.messwerte(puffer)[0]
                self.assertEqual((wert.marke, wert.wert), ("CPU Package", 54.0))


class Leser(unittest.TestCase):
    """Der Teil, der den Block oeffnet - hier mit untergeschobenem Speicher."""

    def setUp(self):
        self._echt = hwiinfo._puffer
        self.addCleanup(setattr, hwiinfo, "_puffer", self._echt)

    def _gib(self, puffer):
        hwiinfo._puffer = lambda: puffer

    def test_ohne_Block_wird_nichts_behauptet(self):
        self._gib(None)
        leser = hwiinfo.HWiNFO(ttl=0)
        self.assertEqual(leser.lesen(), {})
        self.assertEqual(leser.hinweis(), hwiinfo.TEXT_START)
        self.assertIsNone(leser.stillstand)

    def test_mit_Block_kommen_die_Werte(self):
        self._gib(block([gruppe("CPU")], [messwert(1, 0, "Package", 61.5)]))
        leser = hwiinfo.HWiNFO(ttl=0)
        self.assertEqual(leser.lesen(), {"hwiinfo:CPU Package": 61.5})
        self.assertIsNone(leser.hinweis())
        self.assertIsNone(leser.stillstand)

    def test_stillstand_nach_genug_gleichen_Messzeiten(self):
        self._gib(block([gruppe("CPU")], [messwert(1, 0, "Package", 61.5)]))
        leser = hwiinfo.HWiNFO(ttl=0)
        for _ in range(hwiinfo.STEHEN_NACH + 1):
            leser.lesen()
        self.assertIsNotNone(leser.stillstand)
        self.assertEqual(leser.lesen(), {"hwiinfo:CPU Package": 61.5})

    def test_mit_neuer_Messzeit_ist_nichts_mit_Stillstand(self):
        zeit = [ZEIT]
        hwiinfo._puffer = lambda: block([gruppe("CPU")],
                                        [messwert(1, 0, "Package", 61.5)],
                                        messzeit=zeit[0])
        leser = hwiinfo.HWiNFO(ttl=0)
        for _ in range(hwiinfo.STEHEN_NACH + 2):
            zeit[0] += 3
            leser.lesen()
        self.assertIsNone(leser.stillstand)

    def test_fremder_Block_meldet_seinen_Grund(self):
        self._gib(b"XXXX" + b"\x00" * 300)
        leser = hwiinfo.HWiNFO(ttl=0)
        self.assertEqual(leser.lesen(), {})
        self.assertIn("fremd", leser.grund)


if __name__ == "__main__":                          # pragma: no cover
    unittest.main()

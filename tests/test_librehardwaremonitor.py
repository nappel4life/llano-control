"""Der Baum, den LibreHardwareMonitor über seinen Web-Server ausliefert.

Die Werte kommen als einer Baum, genau so, wie ihn das Programm auf dem
Bildschirm zeigt: Knoten mit Kindern, Blaetter sind Messwerte. Getestet wird
hier ein nachgebauter Baum, weil das Programm selbst hier nicht laeuft - und
weil gerade die Eigenheiten durchgespielt sein wollen, die nur in dieser einen
Welt vorkommen: nacktes `null` bei einem Geraet, das gerade nichts meldet, `NaN`
als Wort, Komma statt Punkt im formatierten Text und Messarten, die keine
Temperaturen sind.

Die Tests stammen aus dem Aufbau, den die Web-Schnittstelle selbst erzeugt
(Knoten mit „Type“, „RawValue“ und „Value“), nicht aus einer Beispieldatei -
damit eine neue Fassung des Programms auffaellt, sobald sie etwas anderes
liefert, und nicht erst am Kuehler.
"""

import unittest

from llanotool import sensors
from llanotool import sensors_lhm as lhm


def knoten(text: str, **eigene):
    knoten_wert = {"Text": text, "Children": []}
    knoten_wert.update(eigene)
    return knoten_wert


def baum():
    """Ein Baum wie vom Server: Rechner -> Geraet -> Messart -> Messwert."""
    return knoten("Sensor", Children=[knoten("Computer", Children=[
        knoten("Intel Core i7 8700K", Children=[
            knoten("Temperatures", Children=[
                knoten("CPU Package", Type="Temperature", RawValue=54.0,
                       Value="54.0 °C"),
                knoten("Core #1", Type="Temperature", RawValue=52.0, Value="52.0 °C"),
                knoten("Core #2", Type="Temperature", RawValue=61.0, Value="61.0 °C"),
                knoten("CPU Total", Type="Load", RawValue=12.0, Value="12.0 %"),
            ]),
            knoten("Fan Speeds", Children=[
                knoten("CPU Fan", Type="Fan", RawValue=2400.0, Value="2400 RPM"),
            ]),
        ]),
        knoten("NVIDIA GeForce RTX", Children=[
            knoten("Temperatures", Children=[
                # Ohne nackten Wert: dann bleibt nur der formatierte Text - mit
                # Komma, weil der Rechner auf Deutsch steht.
                knoten("GPU Core", Type="Temperature", RawValue=None, Value="57,5 °C"),
                knoten("Hot Spot", Type="Temperature", RawValue="NaN", Value="NaN °C"),
                knoten("Nicht da", Type="Temperature", RawValue=0.0, Value="0.0 °C"),
            ]),
        ]),
    ])])


class Baum(unittest.TestCase):
    def test_nur_Temperaturen_und_ihre_Namen(self):
        found = {wert.marke: wert.wert for wert in lhm.temperaturen(baum())}
        self.assertEqual(found, {
            "Intel Core i7 8700K CPU Package": 54.0,
            "Intel Core i7 8700K Core #1": 52.0,
            "Intel Core i7 8700K Core #2": 61.0,
            "NVIDIA GeForce RTX GPU Core": 57.5,
        })

    def test_Kennung_hat_die_Quelle(self):
        wert = lhm.temperaturen(baum())[0]
        self.assertEqual(wert.kennung, "lhm:Intel Core i7 8700K CPU Package")

    def test_nan_und_null_sind_keine_Temperatur(self):
        marken = {wert.marke for wert in lhm.temperaturen(baum())}
        self.assertNotIn("NVIDIA GeForce RTX Hot Spot", marken)
        self.assertNotIn("NVIDIA GeForce RTX Nicht da", marken)

    def test_Kernwerte_weichen_dem_Gesamtwert(self):
        ohne = lhm.ohne_einzelkerne(lhm.temperaturen(baum()))
        self.assertEqual([wert.marke for wert in ohne],
                         ["Intel Core i7 8700K CPU Package",
                          "NVIDIA GeForce RTX GPU Core"])

    def test_leerer_Baum_ist_kein_Fehler(self):
        for kaputt in (None, "text", [], {}, 7):
            with self.subTest(baum=kaputt):
                self.assertEqual(lhm.temperaturen(kaputt), [])

    def test_andere_Ebene_ohne_Grobvater(self):
        # Ein Baum, der gleich mit dem Geraet anfaengt, hat keinen Grobvater -
        # dann ist der Vater die Gruppe, und nicht irgendetwas dahinter.
        kleiner = knoten("Intel Core", Children=[
            knoten("CPU Package", Type="Temperature", RawValue=49.0)])
        wert = lhm.temperaturen(kleiner)[0]
        self.assertEqual(wert.marke, "Intel Core CPU Package")


class Zahlen(unittest.TestCase):
    def test_nackte_Zahl_hat_Vorrang(self):
        self.assertEqual(lhm._zahl({"RawValue": 44.0, "Value": "99.0 °C"}), 44.0)

    def test_Komma_und_Einheit(self):
        self.assertEqual(lhm._zahl({"Value": "57,5 °C"}), 57.5)
        self.assertEqual(lhm._zahl({"Value": "63.0"}), 63.0)

    def test_unmoegliche_Werte(self):
        for knoten_wert in ({"RawValue": None, "Value": ""},
                            {"RawValue": "NaN", "Value": "NaN °C"},
                            {"RawValue": 0.0},
                            {"RawValue": -30.0},
                            {"RawValue": 400.0},
                            {"RawValue": True},
                            {}):
            with self.subTest(knoten=knoten_wert):
                self.assertIsNone(lhm._zahl(knoten_wert))


class Leser(unittest.TestCase):
    """Der Kunde des Servers - hier mit unterschobener Antwort."""

    def setUp(self):
        self._echt = lhm._abruf
        self.addCleanup(setattr, lhm, "_abruf", self._echt)

    def _antwort(self, inhalt):
        lhm._abruf = lambda adresse: inhalt

    def test_ohne_Antwort_ohne_Werte(self):
        self._antwort(None)
        leser = lhm.LHM(ttl=0)
        self.assertEqual(leser.lesen(), {})
        self.assertIsNotNone(leser.hinweis())

    def test_Werte_kommen_und_verschwinden_wieder(self):
        self._antwort(baum())
        leser = lhm.LHM(ttl=0)
        self.assertEqual(leser.lesen(),
                         {"lhm:Intel Core i7 8700K CPU Package": 54.0,
                          "lhm:NVIDIA GeForce RTX GPU Core": 57.5})
        self.assertIsNone(leser.hinweis())
        self._antwort(None)
        self.assertEqual(leser.lesen(), {})
        self.assertIsNotNone(leser.hinweis())

    def test_adresse_aus_der_Umgebung(self):
        import os

        alte = os.environ.get("LLANO_LHM")
        os.environ["LLANO_LHM"] = "http://127.0.0.1:9/data.json"
        try:
            self.assertEqual(lhm.LHM().adresse, "http://127.0.0.1:9/data.json")
        finally:
            if alte is None:
                del os.environ["LLANO_LHM"]
            else:
                os.environ["LLANO_LHM"] = alte

    def test_unerreichbare_Adresse_ist_stille(self):
        # Ein Port, an dem nichts hoert: keine Ausnahme, nur ein leerer Mund.
        leser = lhm.LHM(ttl=0, adresse="http://127.0.0.1:9/data.json")
        self.assertEqual(leser.lesen(), {})

    def test_die_erste_Antwort_darf_zaubern(self):
        # LibreHardwareMonitor baut seine Datei erst beim Fragen zusammen, und
        # gleich nach dem Start dauert das schon einmal eine Sekunde. Eine halbe
        # Frist haette daraus still "kein Helfer" gemacht.
        self.assertGreaterEqual(lhm.FRIST, 2.0)


class WasDerAntwortFehlt(unittest.TestCase):
    """Der Satz unter der Auswahl, wenn die Messhilfe redet, aber nicht weiss.

    Der Fall ist haeufiger als jede andere Erklaerung: LibreHardwareMonitor
    laeuft, antwortet willig - und nennt keine Prozessortemperatur, weil ihm
    ohne Administratorrechte der Blick in den Prozessor verweigert wird.
    Dafuer zu schweigen war die schlechteste aller Auskuenfte.
    """

    class Helfer:
        stillstand = None

        def __init__(self, werte):
            self._werte = werte

        def lesen(self):
            return dict(self._werte)

        def hinweis(self):
            return None

    def _messstellen(self, werte):
        messstellen = sensors.Sensors()
        messstellen._zones = None
        messstellen._hwiinfo = None
        messstellen._lhm = self.Helfer(werte)
        messstellen.read = lambda collapse=True: dict(werte)
        return messstellen

    def test_sie_antwortet_ohne_prozessor(self):
        selbst = self._messstellen({"lhm:Mainboard": 41.0})
        self.assertIn("Administrator", selbst.note())

    def test_sie_antwortet_garnicht(self):
        selbst = self._messstellen({})
        self.assertIn("Shared Memory", selbst.note())

    def test_sie_nennt_den_prozessor(self):
        selbst = self._messstellen({"lhm:CPU (Package)": 52.0})
        self.assertIsNone(selbst.note())


if __name__ == "__main__":                          # pragma: no cover
    unittest.main()

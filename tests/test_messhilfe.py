"""Die mitgebrachte Messhilfe: ein Helferprozess, der fuer uns zaehlt.

Geprueft wird hier die *Zusammenarbeit*, und zwar mit einem echten
Kindprozess (``tests/helfer_probeweise.py``), der dieselben Zeilen schreibt wie
die Windowsbruecke: Was aus einer Meldung wird, was fehlt, wenn etwas fehlt,
und dass nichts wirft, wenn der Helfer nicht kann. Ob die richtige Bibliothek
am richtigen Ort liegt, entscheidet die Bauautomatik auf einem echten Windows
- nur sie kann diese Frage stellen.
"""

import pathlib
import re
import sys
import time
import unittest
from unittest import mock

from llanotool import sensors as sensoren
from llanotool import sensors_messhilfe as helfer
from llanotool.sensors_hwiinfo import ohne_einzelkerne

WURZEL = pathlib.Path(__file__).resolve().parents[1]
ATTRAPPE = str(WURZEL / "tests" / "helfer_probeweise.py")
BRUECKE_QUELLTEXT = (WURZEL / "packaging" / "messhilfe" / "messhilfe.cs").read_text(encoding="utf-8")


def gespraech(*schalter: str, verfall: float = 30.0, neustarts: int = 1) -> helfer.Messhilfe:
    """Eine Quelle, die sich ihren Helfer selbst baut - den nachgebauten."""
    return helfer.Messhilfe(befehl=[sys.executable, ATTRAPPE, *schalter],
                            verfall=verfall, neustarts=neustarts, frist=0.0)


def warte(quelle, bis: float = 8.0) -> dict:
    """So lange fragen, bis der Helfer das erste Mal geantwortet hat."""
    ende = time.monotonic() + bis
    while time.monotonic() < ende:
        werte = quelle.lesen()
        if werte:
            return werte
        time.sleep(0.05)
    return {}


class AusDenZeilenDesHelfers(unittest.TestCase):
    def test_die_namen_der_messstellen(self):
        quelle = gespraech("--bleibt")
        try:
            self.assertEqual(warte(quelle), {
                "lhm:CPU (Package)": 54.0,
                "lhm:GPU Hot Spot": 66.0,
            })
        finally:
            quelle.schliessen()

    def test_der_helfer_erzaehlt_was_er_kann(self):
        quelle = gespraech("--bleibt")
        try:
            warte(quelle)
            bericht = quelle.bericht
            self.assertTrue(bericht["treiber"])
            self.assertEqual(bericht["treiber_fassung"], "2.0.9")
            self.assertEqual(bericht["bibliothek"], "0.9.6.0")
            self.assertEqual(bericht["geraete"], 3)
            self.assertIsNone(quelle.hinweis())
        finally:
            quelle.schliessen()

    def test_unsinnige_zahlen_bleiben_weg(self):
        werte = helfer.temperaturen({"art": "werte", "temperaturen": [
            {"geraet": "CPU", "messstelle": "echt", "wert": 47.5},
            {"geraet": "CPU", "messstelle": "schwimmend", "wert": None},
            {"geraet": "CPU", "messstelle": "frost", "wert": -5},
            {"geraet": "CPU", "messstelle": "gluehend", "wert": 240},
            {"geraet": "CPU", "messstelle": "wort", "wert": "waerm"},
            {"geraet": "", "messstelle": "", "wert": 50},
            "kein woerterbuch",
        ]})
        self.assertEqual([(wert.marke, wert.wert) for wert in werte],
                         [("CPU echt", 47.5)])
        self.assertEqual(werte[0].kennung, "lhm:CPU echt")

    def test_einzelkerne_weichen_dem_gesamtwert(self):
        werte = ohne_einzelkerne(helfer.temperaturen({"art": "werte", "temperaturen": [
            {"geraet": "CPU", "messstelle": "Core #0", "wert": 55.0},
            {"geraet": "CPU", "messstelle": "Core #1", "wert": 57.0},
            {"geraet": "CPU", "messstelle": "Package", "wert": 56.0},
        ]}))
        self.assertEqual([wert.marke for wert in werte], ["CPU Package"])

    def test_die_antwort_eines_stehengebliebenen_helfers_verdirbt_nichts(self):
        quelle = gespraech("--bleibt", verfall=0.2)
        try:
            self.assertTrue(warte(quelle))
            time.sleep(0.4)
            self.assertEqual(quelle.lesen(), {})
        finally:
            quelle.schliessen()

    def test_der_selbstbericht_nennt_treiber_und_rechte(self):
        quelle = gespraech("--bleibt")
        try:
            zeilen = quelle.selbstbericht()
            self.assertTrue(any("0.9.6.0" in zeile for zeile in zeilen), zeilen)
            self.assertTrue(any("Treiber da" in zeile for zeile in zeilen), zeilen)
        finally:
            quelle.schliessen()


class WennDerHelferNichtKann(unittest.TestCase):
    def test_ein_helfer_ohne_verstehendes_wort_laesst_sich_hoeren(self):
        # Der Fall "die .NET-Laufzeit fehlt": der Helfer schreibt etwas, aber
        # keine Zeile nach unserer Verabredung. Was er sagt, darf nicht im
        # Nichts verschwinden - es ist die einzige Auskunft, die es gibt.
        quelle = gespraech("--kaputt")
        try:
            self.assertEqual(quelle.lesen(), {})
            time.sleep(0.5)
            self.assertIn("mscoree", quelle.hinweis() or "")
        finally:
            quelle.schliessen()

    def test_der_helfer_meldet_seinen_eigenen_fehler(self):
        quelle = gespraech("--fehler")
        try:
            self.assertEqual(quelle.lesen(), {})
            for _ in range(60):
                if quelle.grund:
                    break
                time.sleep(0.05)
            self.assertIn("Treiber abgelehnt", quelle.grund or "")
            self.assertIn("Treiber abgelehnt", quelle.hinweis() or "")
        finally:
            quelle.schliessen()

    def test_ohne_datei_bleibt_die_quelle_still(self):
        with mock.patch.object(helfer, "datei", return_value=None):
            quelle = helfer.Messhilfe()
            self.assertFalse(quelle.anwesend)
            self.assertEqual(quelle.lesen(), {})
            self.assertIsNone(quelle.hinweis())

    def test_ein_umgefallener_helfer_laeuft_nicht_endlos_nach(self):
        quelle = gespraech("--sofort", neustarts=2)
        try:
            for _ in range(40):
                quelle.lesen()
                time.sleep(0.02)
            self.assertLessEqual(quelle._versuche, 3)
            self.assertEqual(quelle.lesen(), {})
        finally:
            quelle.schliessen()

    def test_abschied_macht_den_helfer_zu(self):
        quelle = gespraech("--bleibt")
        warte(quelle)
        prozess = quelle._prozess
        self.assertIsNotNone(prozess)
        quelle.schliessen()
        prozess.wait(timeout=5)
        self.assertEqual(prozess.returncode, 0)     # der Kanarienvogel: hoeflicher Abschied
        quelle.schliessen()                         # zweimal schliessen ist erlaubt
        self.assertEqual(quelle.lesen(), {})
        self.assertIsNone(quelle._prozess)          # und es laeuft keiner heimlich nach


class DieSeiteFragtNach(unittest.TestCase):
    def setUp(self):
        self.messstellen = sensoren.Sensors()
        self.messstellen._zones = None
        self.messstellen._hwiinfo = None
        # Ein Prueflauf hier hat einen echten Prozessor, und der zaelte sonst
        # als "der Prozessor ist ja schon abgedeckt" - die Hinweise sind aber
        # genau fuer den Fall da, dass keiner der Helfer ihn meldet.
        self.prozessor = False
        self.uebersehen = mock.patch.object(sensoren.Sensors, "_hat_cpu_temperatur",
                                            lambda selbst: self.prozessor)
        self.uebersehen.start()

    def tearDown(self):
        self.uebersehen.stop()
        self.messstellen._lhm = mock.Mock(lesen=lambda: {}, stillstand=None,
                                          anwesend=False, hinweis=lambda: None)

    def test_die_seite_erzaehlt_vom_treiber_statt_von_der_installation(self):
        self.messstellen._messhilfe = mock.Mock(
            lesen=lambda: {}, stillstand=None, anwesend=True,
            hinweis=lambda: "Dieser Rechner hat keinen Treiber dafuer (PawnIO).")
        self.assertIn("PawnIO", self.messstellen.note())

    def test_ohne_jede_messhilfe_bleibt_der_bekannte_satz(self):
        self.messstellen._messhilfe = mock.Mock(lesen=lambda: {}, stillstand=None,
                                                anwesend=False, hinweis=lambda: None)
        note = self.messstellen.note()
        self.assertIn("Shared Memory", note)
        self.assertIn("CPU-Temperaturen mitinstallieren", note)

    def test_eine_nicht_vorhandene_Messhilfe_zehlt_nicht_als_stumm(self):
        # Der Fall, den nur die Bauautomatik sieht: Die mitgebrachte Messhilfe
        # liegt dort nicht, und der Web-Server liefert ein Mainboard, aber
        # keinen Prozessor. Eine Quelle, die gar nicht da ist, darf die
        # Auskunft nicht in ein Schweigen verwandeln.
        with mock.patch.object(helfer, "datei", return_value=None):
            self.messstellen._messhilfe = helfer.Messhilfe()
        self.messstellen._lhm = mock.Mock(lesen=lambda: {"lhm:Mainboard": 41.0},
                                          stillstand=None, hinweis=lambda: None)
        self.assertIn("Administrator", self.messstellen.note())

    def test_der_treibergrund_gewinnt_auch_neben_einer_liefernden_quelle(self):
        # Grafikkarte und Mainboard meldet sie auch ohne Treiber. Der Grund,
        # warum der Prozessor fehlt, steht trotzdem da - sonst erklart die
        # fröhliche Quelle das Fehlen eines Werts, das sie selbst nicht kennt.
        self.messstellen._messhilfe = mock.Mock(
            lesen=lambda: {}, stillstand=None, anwesend=True,
            hinweis=lambda: "Dieser Rechner hat keinen Treiber dafuer (PawnIO).")
        self.messstellen._lhm = mock.Mock(lesen=lambda: {"lhm:GPU Hot Spot": 61.0},
                                          stillstand=None, hinweis=lambda: None)
        note = self.messstellen.note()
        self.assertIn("PawnIO", note)
        self.assertNotIn("Shared Memory", note)

    def test_eine_liefernde_quelle_laesst_die_andere_erklaeren(self):
        self.prozessor = True         # dieselbe Quelle meldet ihn ja
        self.messstellen._messhilfe = mock.Mock(
            lesen=lambda: {"lhm:CPU (Package)": 51.0}, stillstand=None,
            anwesend=True, hinweis=lambda: None)
        self.assertIsNone(self.messstellen.note())


class DieVerabredungUeberDieSprachenHinweg(unittest.TestCase):
    """C# und Python reden nur ueber Woerter - also wird nachgerechnet.

    Ein vertippter Schluessel in der einen Sprache faellt in der anderen nicht
    auf: Der Helfer schreibt fröhlich weiter, und die Quelle schweigt. Diese
    Pruefung haelt beiden den Spiegel hin.
    """

    def test_die_schluessel_stimmen_ueberein(self):
        for schluessel in ("art", "werte", "temperaturen", "geraet", "messstelle",
                           "wert", "start", "erhoeht", "treiber", "treiber_fassung",
                           "bibliothek", "geraete", "fehler", "text"):
            self.assertIn(f'"{schluessel}"', BRUECKE_QUELLTEXT,
                          f"der Helfer schreibt '{schluessel}' nie")
            self.assertIn(f'"{schluessel}"',
                          (WURZEL / "llanotool" / "sensors_messhilfe.py").read_text(encoding="utf-8"),
                          f"die Quelle liest '{schluessel}' nie")

    def test_der_helfer_haengt_an_der_standardeingabe(self):
        self.assertIn("OpenStandardInput", BRUECKE_QUELLTEXT)

    def test_mit_der_bibliothek_liest_auch_der_unterknoten(self):
        self.assertIn("SubHardware", BRUECKE_QUELLTEXT)

    def test_die_uebersetzungszeilen_werden_nicht_unterwegs_auseinandergezogen(self):
        # Der Fehler, den nur die Bauautomatik sieht: "/out:" + Pfad innerhalb
        # einer Mappe ergibt zwei Felder, und der Uebersetzer bekommt ein
        # "/out:" ohne Datei. Deshalb steht jede Angabe als eigenes Feld da.
        skript = (WURZEL / "packaging" / "messhilfe" / "bauen.ps1").read_text(encoding="utf-8")
        feld, rest = skript.split("$Zeilen = @(", 1)
        block = rest.split(")", 1)[0]
        for feld in block.splitlines():
            # Die Optionsnamen enthalten selbst ein Plus ("/optimize+"), also
            # wird nur ausserhalb der Anfuehrungszeichen nachgerechnet.
            nackt = re.sub(r'"[^"]*"', "", feld)
            self.assertNotIn("+", nackt, f"in {feld.strip()} wird wieder addiert")
            self.assertNotIn(",", nackt, f"{feld.strip()} haengt an einem Komma")
        for angabe in ("/out:", "/reference:$BibliothekAntwort", "System.Core.dll"):
            self.assertIn(angabe, block)

    def test_die_uebersetzung_schliesst_die_fremden_bausteine_aus(self):
        skript = (WURZEL / "packaging" / "messhilfe" / "bauen.ps1").read_text(encoding="utf-8")
        fenster, liste = skript.split("$Oberflaeche = @(", 1)
        ausschluss = liste.split(")", 1)[0]
        for baustein in ("Aga.Controls.dll", "OxyPlot.dll", "OxyPlot.WindowsForms.dll",
                         "Microsoft.Win32.TaskScheduler.dll"):
            self.assertIn(baustein, ausschluss, f"{baustein} bleibt doch im Paket")
        # BlackSharp.Core wird von der Bibliothek referenziert: wer es als
        # Fensterbaustein abtut, bekommt eine fehlende Baugruppe beim Oeffnen.
        self.assertNotIn("BlackSharp.Core.dll", ausschluss)
        self.assertIn("llano-messhilfe.exe", skript)
        self.assertIn("LESEAMICH.md", skript)


if __name__ == "__main__":
    unittest.main()

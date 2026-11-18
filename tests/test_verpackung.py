"""Was der Windows-Installer verspricht, muss er auch liefern.

Der Installer ist die einzige Datei, die jemand ohne Kommandozeile anfasst, und
er laesst sich hier nicht ausfuehren. Was sich pruefen laesst, sind die
Zusagen, die in ihm stehen: dass es den Helfer-Haken gibt, dass er auf den Ordner
zeigt, den die Bauautomatik fuellt, und dass die Einstellungen, die er dabeilegt,
die Schluessel nennen, welche die Messhilfe wirklich liest. Ein Tippfehler darin
faellt sonst erst auf einem Rechner auf, auf dem jemand gerade nach seiner
Prozessortemperatur sucht.
"""

import pathlib
import unittest
import xml.etree.ElementTree as Baum

WURZEL = pathlib.Path(__file__).resolve().parents[1]
INSTALLER = (WURZEL / "packaging" / "windows" / "llano.iss").read_text(encoding="utf-8")
EINSTELLUNGEN = (WURZEL / "packaging" / "windows" / "helfer.config").read_text(encoding="utf-8")

# Die vier Schluessel, die LibreHardwareMonitor in seinem MainForm liest.
# Heissen sie anders, ist der Web-Server nach der Installation einfach aus.
SCHLUESSEL = {"runWebServerMenuItem": "True", "listenerPort": "8085",
              "startMinMenuItem": "True", "minTrayMenuItem": "True"}


class HakenFuerDieMesshilfe(unittest.TestCase):
    def setUp(self):
        # Gelesen wird wie von der Messhilfe selbst: als XML, nicht als Text.
        # Ein kaputtes Zeichen darin faellt hier auf, nicht erst am Geraet.
        wurzel = Baum.fromstring(EINSTELLUNGEN)
        self.werte = {element.get("key"): element.get("value")
                      for element in wurzel.iter("add")}

    def test_der_haken_existiert_und_ist_an(self):
        self.assertIn('Name: "cpu"', INSTALLER)
        zeile = [z for z in INSTALLER.splitlines() if z.startswith('Name: "cpu"')]
        self.assertNotIn("unchecked", zeile[0],
                         "ohne CPU-Werte ist die Kurve halb so wertvoll")

    def test_er_kopiert_in_den_Ordner_der_Bauautomatik(self):
        self.assertIn('Source: "..\\..\\paket\\helfer\\*"', INSTALLER)
        self.assertIn('DestDir: "{app}\\helfer"', INSTALLER)
        self.assertIn("skipifsourcedoesntexist", INSTALLER,
                      "ein Bau von Hand soll ohne den Ordner nicht scheitern")

    def test_ein_Update_macht_den_Ordner_leer(self):
        # Das alte Lied: ein Update ueberschreibt Gleichnamiges, der Rest bleibt.
        self.assertIn('Type: filesandordirs; Name: "{app}\\helfer"', INSTALLER)

    def test_anmeldung_und_abschied_zusammen(self):
        self.assertIn('/Create /F /TN "llano Messhilfe"', INSTALLER)
        self.assertIn('/Delete /F /TN "llano Messhilfe"', INSTALLER)
        self.assertIn("taskkill", INSTALLER)     # laufende Datei = halbe Deinstallation

    def test_die_Einstellungen_nennen_die_richtigen_Woerter(self):
        for schluessel, wert in SCHLUESSEL.items():
            self.assertEqual(self.werte.get(schluessel), wert)

    def test_der_Port_ist_der_der_Anfrage(self):
        # sensors_lhm fragt 127.0.0.1:8085/data.json - die Messhilfe muss auf
        # derselben Zahl hoeren, sonst ist der Haken ein leeres Versprechen.
        from llanotool import sensors_lhm
        self.assertEqual(self.werte["listenerPort"], "8085")
        self.assertIn(":8085/", sensors_lhm.ADRESSE)


if __name__ == "__main__":
    unittest.main()

"""Was die Einstellungsdatei alles enthalten darf - und was daraus wird.

Die Datei ueberlebt ein Deinstallieren mit Absicht: sie enthaelt die Kurve, die
sich jemand erarbeitet hat. Genau deshalb liegt sie nach einer Neuinstallation
noch da, und genau deshalb steht sie schon mal von einer anderen Fassung oder
von der Rust-Seite geschrieben darin. Ein Feldbericht sah so aus: Nach dem
Einspielen offnete sich die Oberflaeche nicht mehr, erst das Loeschen der Datei
half.

Der Grund war kein einzelner Wert, sondern die Art, wie gelesen wurde: jeder
Wert ging ungeprueft durch, und ein einziges null genugt - ``int(None)`` beim
Bauen des Fensters -, und die Oberflaeche ist weg, nachdem sie den Kuehler
eingeschaltet hat. Deshalb wird beim Lesen alles geformt, und darauf zielen
diese Pruefungen: herauskommt immer eine Einstellungsdatei, mit der sich
arbeiten laesst.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

import llanotool
from llanotool import config as config_mod
from llanotool import protocol

UNTERWEGS = {
    "mode": None,
    "manual_speed": None,
    "sensors": None,
    "curve": None,
    "hysteresis": None,
    "poll_seconds": None,
    "write_interval": None,
    "min_speed_step": None,
    "light": None,
    "power_on_start": None,
    "power_off_on_exit": None,
}


class Lesen(unittest.TestCase):
    """Jeder Wert wird so behandelt, als kaeme er aus einer fremden Hand."""

    def test_nichts_in_der_Datei(self):
        cfg = config_mod.sauber({})
        for schluessel, wert in config_mod.DEFAULTS.items():
            with self.subTest(schluessel=schluessel):
                self.assertEqual(cfg[schluessel], wert)

    def test_ueberall_nur_nichts_hin(self):
        cfg = config_mod.sauber(UNTERWEGS)
        for schluessel, wert in config_mod.DEFAULTS.items():
            with self.subTest(schluessel=schluessel):
                self.assertEqual(cfg[schluessel], wert)

    def test_Zahlen_durfen_Texte_sein(self):
        cfg = config_mod.sauber({"manual_speed": "60", "hysteresis": "3",
                                 "poll_seconds": "abc"})
        self.assertEqual(cfg["manual_speed"], 60)
        self.assertEqual(cfg["hysteresis"], 3.0)
        self.assertEqual(cfg["poll_seconds"], config_mod.DEFAULTS["poll_seconds"])

    def test_Stufen_bleiben_im_Bereich(self):
        cfg = config_mod.sauber({"manual_speed": -40})
        self.assertEqual(cfg["manual_speed"], 0)
        cfg = config_mod.sauber({"manual_speed": 5000})
        self.assertEqual(cfg["manual_speed"], 100)

    def test_Wahr_ist_keine_Stufe(self):
        self.assertEqual(config_mod.sauber({"manual_speed": True})["manual_speed"],
                         config_mod.DEFAULTS["manual_speed"])

    def test_modus_Namen_von_beiden_Fassungen(self):
        for schreibweise, erwartet in (("kurve", "auto"), ("Auto", "auto"),
                                       ("automatisch", "auto"), ("manuell", "manual"),
                                       ("MANUAL", "manual")):
            with self.subTest(schreibweise=schreibweise):
                self.assertEqual(config_mod.sauber({"mode": schreibweise})["mode"],
                                 erwartet)

    def test_unbekannter_Modus_wird_der_vorgeschlagene(self):
        for schreibweise in ("web", "", None, 7):
            with self.subTest(schreibweise=schreibweise):
                cfg = config_mod.sauber({"mode": schreibweise})
                self.assertEqual(cfg["mode"], config_mod.DEFAULTS["mode"])

    def test_Schalter_verstehen_ja_und_nein(self):
        cfg = config_mod.sauber({"power_off_on_exit": "nein", "power_on_start": "ja"})
        self.assertFalse(cfg["power_off_on_exit"])
        self.assertTrue(cfg["power_on_start"])

    def test_Licht_wird_vollstaendig(self):
        cfg = config_mod.sauber({"light": {"on": True}})
        self.assertEqual(sorted(cfg["light"]), sorted(config_mod.DEFAULTS["light"]))

    def test_Lichtwerte_ohne_Anschlag(self):
        cfg = config_mod.sauber({"light": {"color": 99, "effect": -3, "speed": "2",
                                           "brightness": 99999}})
        self.assertEqual(cfg["light"]["color"], len(protocol.COLORS) - 1)
        self.assertEqual(cfg["light"]["effect"], 0)
        self.assertEqual(cfg["light"]["speed"], 2)
        self.assertEqual(cfg["light"]["brightness"], 255)

    def test_Messstellen_als_Text_oder_leer(self):
        self.assertEqual(config_mod.sauber({"sensors": "nvidia:GPU"})["sensors"],
                         ["nvidia:GPU"])
        self.assertEqual(config_mod.sauber({"sensors": []})["sensors"], [])

    def test_Kurve_aus_Muell_wird_brauchbar(self):
        cfg = config_mod.sauber({"curve": {"45": 20}})
        self.assertEqual(cfg["curve"], config_mod.DEFAULTS["curve"])
        cfg = config_mod.sauber({"curve": [[80, 90], ["40", "20"], ["x", 5], [60]]})
        self.assertEqual(cfg["curve"], [[40.0, 20], [80.0, 90]])

    def test_fremde_Schluessel_stoeren_nicht(self):
        cfg = config_mod.sauber({"tray": False, "web_port": 8080, "mode": "auto"})
        self.assertEqual(cfg["mode"], "auto")
        self.assertNotIn("web_port", cfg)

    def test_ungerade_Menge_nutzt_nichts(self):
        for kaputt in (None, "text", 7, ["x"]):
            with self.subTest(kaputt=kaputt):
                cfg = config_mod.sauber(kaputt)
                self.assertEqual(cfg["mode"], config_mod.DEFAULTS["mode"])


class Datei(unittest.TestCase):
    """Die Datei selbst: lesen, schreiben, und woraus sie stammt."""

    def setUp(self):
        ordner = tempfile.mkdtemp()
        self.pfad = os.path.join(ordner, "config.json")
        self.umgebung = {"LLANO_CONFIG": self.pfad}
        self.alte = dict(os.environ)
        os.environ.update(self.umgebung)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.alte)

    def _schreibe(self, inhalt: dict) -> None:
        with open(self.pfad, "w", encoding="utf-8") as handle:
            json.dump(inhalt, handle)

    def test_liesbare_Datei_von_frueher(self):
        self._schreibe({"version": "1.0.0", "mode": "kurve", "manual_speed": None,
                        "light": {"color": 77}})
        with contextlib.redirect_stdout(io.StringIO()):
            cfg = config_mod.load()
        self.assertEqual(cfg["version"], "1.0.0")
        self.assertEqual(cfg["mode"], "auto")
        self.assertEqual(cfg["manual_speed"], config_mod.DEFAULTS["manual_speed"])
        self.assertEqual(cfg["light"]["color"], len(protocol.COLORS) - 1)

    def test_Schreiben_verraet_die_eigene_Fassung(self):
        config_mod.save(config_mod.load())
        with open(self.pfad, encoding="utf-8") as handle:
            geschrieben = json.load(handle)
        self.assertEqual(geschrieben["version"], llanotool.__version__)
        self.assertEqual(config_mod.load()["version"], llanotool.__version__)

    def test_unlesbare_Datei_ist_kein_Hindernis(self):
        with open(self.pfad, "w", encoding="utf-8") as handle:
            handle.write("{ das hier ist kein json")
        with contextlib.redirect_stdout(io.StringIO()) as fang:
            cfg = config_mod.load()
        self.assertEqual(cfg["mode"], config_mod.DEFAULTS["mode"])
        self.assertIn("beschadigt", fang.getvalue())

    def test_es_wird_laut_wenn_etwas_verbogen_wurde(self):
        self._schreibe({"manual_speed": None})
        with contextlib.redirect_stdout(io.StringIO()) as fang:
            config_mod.load()
        self.assertIn("manual_speed", fang.getvalue())

    def test_stille_Datei_bleibt_stille(self):
        config_mod.save({"mode": "manual", "manual_speed": 30})
        with contextlib.redirect_stdout(io.StringIO()) as fang:
            config_mod.load()
        self.assertEqual(fang.getvalue(), "")


if __name__ == "__main__":                          # pragma: no cover
    unittest.main()

"""Was die Oberflaeche ueber ihren eigenen Start aufhebt.

Eine verpackte Oberflaeche hat kein Terminal, in dem sie etwas sagen koennte;
ihre Datei ist der einzige Bericht. Wer meldet, dass kein Fenster kommt, muss
daran also erkennen koennen, *wo* es stehen blieb - sonst bleibt nichts uebrig
als Raten, und Raten hat hier schon einmal einen Tag gekostet.
"""

import faulthandler
import logging
import os
import tempfile
import unittest
from unittest import mock

from llanotool import cli

try:                                     # der Prueflauf ohne Oberflaeche kennt kein Qt
    import llanotool.gui                 # noqa: F401
    ohne_oberflaeche = False
except ImportError:
    ohne_oberflaeche = True


class Startprotokoll(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.TemporaryDirectory()
        self.umgebung = mock.patch.dict(
            os.environ,
            {"LLANO_CONFIG": os.path.join(self.ordner.name, "config.json")})
        self.umgebung.start()

        self.wurzel = logging.getLogger()
        self.llano = logging.getLogger("llano")
        self.handler_der_wurzel = list(self.wurzel.handlers)
        self.handler_von_llano = list(self.llano.handlers)
        self.stufe_von_llano = self.llano.level
        self.faenger_anaus = not faulthandler.is_enabled()

    def tearDown(self):
        for handler in list(self.wurzel.handlers):
            if handler not in self.handler_der_wurzel:
                self.wurzel.removeHandler(handler)
                handler.close()
        for handler in list(self.llano.handlers):
            if handler not in self.handler_von_llano:
                self.llano.removeHandler(handler)
                handler.close()
        self.llano.setLevel(self.stufe_von_llano)
        if self.faenger_anaus:
            faulthandler.disable()
        self.umgebung.stop()
        self.ordner.cleanup()

    def _protokoll(self):
        pfad = cli.protokolldatei()
        self.assertTrue(os.path.exists(pfad), "die Protokolldatei fehlt")
        with open(pfad, encoding="utf-8") as datei:
            return datei.read()

    def test_die_datei_bekommt_mehr_als_der_bildschirm(self):
        # Ein Start, der mitten im Fensterbauen stirbt, ist von einem, der nie
        # angefangen hat, nur durch die feinen Zeilen zu unterscheiden.
        logging.basicConfig(level=logging.INFO)      # genau so fängt cmd_gui an
        cli.protokolldatei()
        self.assertEqual(self.llano.level, logging.DEBUG)
        datei = [h for h in self.llano.handlers if isinstance(h, logging.FileHandler)]
        self.assertEqual(len(datei), 1)
        self.assertEqual(datei[0].level, logging.DEBUG)
        auf_dem_schirm = [h for h in self.wurzel.handlers
                          if h not in datei and h.level == logging.INFO]
        self.assertTrue(auf_dem_schirm, "die Konsole soll nicht jedes Detail sehen")

    def test_auch_ein_harter_abbruch_landet_in_der_datei(self):
        # Eine gestuerzte Bibliothek wirft keinen Python-Fehler. Ohne diesen
        # Faenger ware ein solcher Absturz spurlos - genau der Fall, der hier
        # schon einmal ratlos zurueckgelassen hat.
        cli.protokolldatei()
        self.assertTrue(faulthandler.is_enabled())

    @unittest.skipIf(ohne_oberflaeche,
                     "ohne PyQt6 gibt es keinen Start, der aufhalfen konnte")
    def test_der_anfang_steht_drin_und_sein_Ende_auch(self):
        with mock.patch("llanotool.gui.run",
                        side_effect=RuntimeError("das Fenster blieb halbfertig")):
            with self.assertRaises(SystemExit) as kasten:
                cli.cmd_gui(mock.Mock(verbose=False, minimized=False, tray=False))
        protokoll = self._protokoll()
        self.assertIn("Oberflaeche startet", protokoll)
        self.assertIn("das Fenster blieb halbfertig", protokoll)
        self.assertIn("haengen geblieben", str(kasten.exception))

if __name__ == "__main__":
    unittest.main()

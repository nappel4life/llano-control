"""Die zwei Dateien, die beide Fassungen teilen muessen.

Die Rust-Fassung und die Python-Fassung steuern denselben Kuehler, und sie
bemerken einander ausschließlich über zwei Pfade: die Einstellungsdatei und die
Sperrdatei. Liegen die auseinander, stehen zwei Steuerungen am Geraet, lesen sich
die Antworten der Statusanfrage weg und halten das Geraet gleichzeitig fest --
gesehen unter Windows, wo die Rust-Fassung die Sperrdatei nach `/tmp` und damit
nach `C:\\tmp` legte, die Python-Fassung nach `%LOCALAPPDATA%\\llano`.

Die Regeln hier sind deshalb absichtlich die der Python-Fassung: `loop.py` ist
der Ort, an dem sie stehen, und `rust/src/lock.rs` nimmt denselben Wert.
"""

import os
import unittest
from unittest import mock

from llanotool import config as config_mod
from llanotool import loop


class Sperrdatei(unittest.TestCase):
    """Der Ort der Sperrdatei, für jedes Betriebssystem einzeln."""

    def test_unter_windows_gilt_localappdata(self):
        vorgabe = r"C:\Users\nappe\AppData\Local"
        with mock.patch.object(loop, "IS_WINDOWS", True), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": vorgabe}, clear=True):
            self.assertEqual(loop.runtime_dir(), os.path.join(vorgabe, "llano"))
            self.assertTrue(loop.lock_path().endswith(
                os.path.join("llano", "daemon.lock")))

    def test_unter_windows_ohne_localappdata_bleibt_es_beim_llano_ordner(self):
        with mock.patch.object(loop, "IS_WINDOWS", True), \
                mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(loop.runtime_dir().endswith("llano"))

    def test_unter_linux_gilt_die_laufzeit_der_shell(self):
        with mock.patch.object(loop, "IS_WINDOWS", False), \
                mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"},
                                clear=True):
            self.assertEqual(loop.runtime_dir(), "/run/user/1000/llano")

    def test_unter_linux_ohne_laufzeit_weichet_auf_tmp_aus(self):
        with mock.patch.object(loop, "IS_WINDOWS", False), \
                mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(loop.lock_path(), "/tmp/llano/daemon.lock")

    def test_eine_Vorgabe_aus_der_umgebung_gewinnt(self):
        with mock.patch.dict(os.environ, {"LLANO_LOCK": "/tmp/andere.lock"},
                             clear=True):
            self.assertEqual(loop.lock_path(), "/tmp/andere.lock")


class Einstellungsdatei(unittest.TestCase):
    """Auch die Konfiguration muss für beide Fassungen dieselbe Datei sein."""

    def test_unter_windows_in_roaming_unterm_llano_ordner(self):
        vorgabe = r"C:\Users\nappe\AppData\Roaming"
        with mock.patch.object(os, "name", "nt"), \
                mock.patch.dict(os.environ, {"APPDATA": vorgabe}, clear=True):
            self.assertEqual(config_mod.config_path(),
                             os.path.join(vorgabe, "llano", "config.json"))

    def test_unter_linux_in_der_konfiguration(self):
        with mock.patch.object(os, "name", "posix"), \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/home/x/.config"},
                                clear=True):
            self.assertEqual(config_mod.config_path(),
                             "/home/x/.config/llano/config.json")


if __name__ == "__main__":
    unittest.main()

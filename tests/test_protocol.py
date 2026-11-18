"""Tests für Protokoll-Arithmetik und Lüfterkurve.

Die Byte-Vektoren stammen aus authentischen Protokoll-Mitschnitten des Geraets,
damit eine Aenderung hier sofort auffaellt.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llanotool import protocol
from llanotool.curve import CurveFollower, interpolate


class Checksum(unittest.TestCase):
    def test_bekannte_vektoren(self):
        cases = {
            # LED-Kommando: aus, Lauflicht, orange, Helligkeit 255
            bytes.fromhex("003c00830400ff"): 0x3D,
            # Statusbericht: Stufe 60, Lauflicht, orange
            bytes.fromhex("883c00030400ff"): 0x35,
            # Status anfordernd
            bytes.fromhex("80000000000000"): 0x7F,
            # Firmware anfordernd
            bytes.fromhex("81000000000000"): 0x7E,
        }
        for body, expected in cases.items():
            with self.subTest(body=body.hex()):
                self.assertEqual(len(body), protocol.BODY_LEN)
                self.assertEqual(protocol.checksum(body), expected)

    def test_summe_ueber_alle_berichtsbytes_ist_ff(self):
        body = bytes([0x01, 47, 0, 0, 2, 0, 0xFF])
        self.assertEqual(sum(body) + protocol.checksum(body) & 0xFF, 0xFF)

    def test_falsche_laenge(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.checksum(b"\x00" * 6)


class Reports(unittest.TestCase):
    def test_luefterbericht(self):
        report = protocol.build_fan_report(50, color=2, effect=1, effect_speed=3,
                                           brightness=200)
        self.assertEqual(len(report), protocol.BUFFER_LEN)
        self.assertEqual(report[0], 0x00)               # Report-ID-Prafix
        self.assertEqual(report[1], protocol.CMD_FAN)
        self.assertEqual(report[2], 50)
        self.assertEqual(report[3], 0x00)               # Hauptschalter: an
        self.assertEqual(protocol.checksum(report[1:8]), report[8])

    def test_luefterbericht_fuehrt_beleuchtung_mit(self):
        # Geraetetest, 2026-11-17: ein Luefterbericht mit festen Beleuchtungs-
        # bytes setzte Farbe, Effekt und Helligkeit auf Standardwerte zurueck.
        # Deshalb muss jeder Bericht die aktuelle Beleuchtung tragen.
        report = protocol.build_fan_report(50, color=3, effect=2, effect_speed=1,
                                           brightness=0x80, light_on=False)
        self.assertEqual(report[4], 0x80 | 2)   # Effekt mit Aus-Bit
        self.assertEqual(report[5], 3)          # Farbe lila
        self.assertEqual(report[6], 1)          # Effekttakt
        self.assertEqual(report[7], 0x80)       # Helligkeit

    def test_lichtbericht_fuehrt_luefterstufe_mit(self):
        # Ein Licht-Kommando ohne die aktuelle Stufe wuerde den Luefter stoppen.
        report = protocol.build_light_report(fan_speed=73, color=2, effect=1)
        self.assertEqual(report[1], protocol.CMD_LIGHT)
        self.assertEqual(report[2], 73)
        self.assertEqual(report[5], 2)   # Farbe
        self.assertEqual(report[4], 1)   # Effekt

    def test_beide_befehle_gleicher_rahmen(self):
        luefter = protocol.build_fan_report(40, color=1, effect=2, effect_speed=0,
                                            brightness=255)
        licht = protocol.build_light_report(fan_speed=40, color=1, effect=2,
                                            effect_speed=0, brightness=255)
        self.assertEqual(luefter[2:8], licht[2:8])   # nur Befehlsbyte + Pruefsumme
        self.assertEqual(luefter[1], protocol.CMD_FAN)
        self.assertEqual(licht[1], protocol.CMD_LIGHT)

    def test_luefter_wird_begrenzt(self):
        self.assertEqual(protocol.build_fan_report(0, color=0)[2], 1)
        self.assertEqual(protocol.build_fan_report(500, color=0)[2], 100)

    def test_leds_aus_oder_hoch(self):
        an = protocol.build_light_report(fan_speed=50, color=0, effect=3)
        aus = protocol.build_light_report(fan_speed=50, color=0, effect=3, light_on=False)
        self.assertLess(an[4], 0x80)
        self.assertGreaterEqual(aus[4], 0x80)

    def test_hauptschalter(self):
        an = protocol.build_light_report(fan_speed=50, color=0, powered_on=True)
        aus = protocol.build_light_report(fan_speed=50, color=0, powered_on=False)
        self.assertEqual(an[3], 0x00)
        self.assertNotEqual(aus[3], 0x00)


class Parse(unittest.TestCase):
    STATUS = bytes.fromhex("00" + "883c00030400ff" + "35")

    def test_statusbericht(self):
        state = protocol.parse_state(self.STATUS)
        self.assertEqual(state.fan_speed, 60)
        self.assertTrue(state.powered_on)
        self.assertTrue(state.light_on)
        self.assertEqual(state.effect, 3)
        self.assertEqual(state.effect_name, "lauflicht")
        self.assertEqual(state.color, 4)
        self.assertEqual(state.color_name, "orange")
        self.assertEqual(state.effect_speed, 0)
        self.assertEqual(state.brightness, 255)

    def test_rpm_anzeige(self):
        # Roh 48 = 1500 U/min, Roh 100 = 2800 U/min laut Nachmessung.
        self.assertEqual(protocol.parse_state(self.STATUS).rpm_display, 1800)
        self.assertEqual(protocol.parse_state(self._raw(48)).rpm_display, 1500)
        self.assertEqual(protocol.parse_state(self._raw(1)).rpm_display, 300)
        self.assertEqual(protocol.parse_state(self._raw(100)).rpm_display, 2800)

    @staticmethod
    def _raw(speed: int) -> bytes:
        body = bytes([0x88, speed, 0x00, 0x03, 0x04, 0x00, 0xFF])
        return bytes([0x00]) + body + bytes([protocol.checksum(body)])

    def test_leds_aus_im_status(self):
        raw = bytearray(bytes.fromhex("00" + "883c00830400ff" + "35"))
        raw[8] = protocol.checksum(raw[1:8])
        state = protocol.parse_state(bytes(raw))
        self.assertFalse(state.light_on)
        self.assertEqual(state.effect, 3)

    def test_prueftsumme_wird_kontrolliert(self):
        bad = bytearray(self.STATUS)
        bad[8] ^= 0xFF
        with self.assertRaises(protocol.ProtocolError):
            protocol.parse_state(bytes(bad))


class Curve(unittest.TestCase):
    CURVE = [[50, 20], [60, 40], [70, 80], [80, 100]]

    def test_randpunkte(self):
        self.assertEqual(interpolate(self.CURVE, 10), 20)
        self.assertEqual(interpolate(self.CURVE, 95), 100)

    def test_interpolation(self):
        self.assertEqual(interpolate(self.CURVE, 55), 30)
        self.assertEqual(interpolate(self.CURVE, 65), 60)

    def test_aufsteigend_und_ganzzahlig(self):
        previous = 0
        for temp in range(40, 91):
            speed = interpolate(self.CURVE, temp)
            self.assertGreaterEqual(speed, previous)
            self.assertGreaterEqual(speed, 1)
            self.assertLessEqual(speed, 100)
            previous = speed

    def test_unsortierte_kurve(self):
        # 60 liegt genau zwischen (50, 20) und (70, 80).
        self.assertEqual(interpolate([[70, 80], [50, 20]], 60), 50)

    def test_schneller_hinauf_langsamer_hinunter(self):
        follower = CurveFollower(self.CURVE, hysteresis=3.0)
        self.assertEqual(follower.update(50), 20)
        self.assertEqual(follower.update(80), 100)     # hoch: sofort
        self.assertEqual(follower.update(78), 100)     # erst 2 grad tiefer: bleibt oben
        self.assertEqual(follower.update(75), 90)      # 3 grad unter dem Anker: darf runter

    def test_neustart_setzt_verlauf_zurueck(self):
        follower = CurveFollower(self.CURVE, hysteresis=3.0)
        follower.update(80)
        follower.reset()
        self.assertEqual(follower.update(50), 20)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Prueft die Oberflaeche ohne angeschlusselten Kuehler.

Setzt einen Simulator anstelle des Geraets ein, fahrt die Oberflaeche im
Hintergrund, spielt Eingaben durch -- inklusive der Maus auf der Lufterkurve --
und legt ein Bild des Fensters ab. Die Konfiguration landet in einem
ortlichen Verzeichnis, die echte ~/.config/llano bleibt unberuhrt.

    QT_QPA_PLATFORM=offscreen python3 tools/gui_probe.py [ausgabe.png]
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading

os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="llano-probe-"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llanotool import device, loop, protocol
from llanotool.protocol import COLORS, EFFECTS, EFFECT_SPEEDS, DeviceState


class FakePad:
    """Verhaelt sich wie das Geraet: jeder Bericht traegt den ganzen Zustand."""

    nodes = ["/dev/hidraw9"]

    def __init__(self, node: str | None = None):
        self.node = node or self.nodes[0]
        self.other_nodes: list[str] = []
        self._lock = threading.Lock()
        self._state = {
            "fan": 24, "powered": True, "light": True,
            "effect": 3, "color": 1, "speed": 0, "brightness": 66,
        }
        self.writes = 0
        # Ein Kindprozess kann so berichten, was dem Kuehler zuletzt angetan wurde.
        # Notiert wird erst ab dem ersten Schreibvorgang: der Anfangszustand ist
        # noch keine Meldung wert, und der Test wartet sonst beim ersten
        # Einschalten, das nie passiert ist.
        self.marker = os.environ.get("LLANO_PROBE_MARKER")

    @property
    def state(self) -> dict:
        return dict(self._state)

    def _note(self) -> None:
        if self.marker:
            with open(self.marker, "w", encoding="utf-8") as handle:
                json.dump(self._state, handle)

    def close(self) -> None:
        pass

    @property
    def closed(self) -> bool:
        return False

    def request_status(self) -> None:
        pass

    def read_raw(self) -> bytes:
        with self._lock:
            s = self._state
            effect = s["effect"] if s["light"] else s["effect"] | 0x80
            body = bytes([0x80, s["fan"], 0 if s["powered"] else 1, effect,
                          s["color"], s["speed"], s["brightness"]])
        return bytes([0]) + body + bytes([protocol.checksum(body)])

    def read_state(self, refresh: bool = True) -> DeviceState:
        return protocol.parse_state(self.read_raw())

    def _write_raw(self, payload: bytes) -> None:
        with self._lock:
            self.writes += 1
            state = self._state
            state["fan"] = payload[2]
            state["powered"] = payload[3] == 0
            state["light"] = payload[4] < 0x80
            state["effect"] = payload[4] & ~0x80
            state["color"] = payload[5]
            state["speed"] = payload[6]
            state["brightness"] = payload[7]
        self._note()

    def set_fan(self, speed, confirm=True, known=None):
        self._write_raw(protocol.build_fan_report(speed, color=(known or self.read_state()).color))
        return self.read_state() if confirm else None

    def set_light(self, *, color=None, effect=None, effect_speed=None, brightness=None,
                  light_on=None, powered_on=None, fan_speed=None, confirm=True, known=None):
        current = known or self.read_state()
        report = protocol.build_light_report(
            fan_speed=current.fan_speed if fan_speed is None else fan_speed,
            color=current.color if color is None else color,
            effect=current.effect if effect is None else effect,
            effect_speed=current.effect_speed if effect_speed is None else effect_speed,
            brightness=current.brightness if brightness is None else brightness,
            light_on=current.light_on if light_on is None else light_on,
            powered_on=current.powered_on if powered_on is None else powered_on,
        )
        self._write_raw(report)
        return self.read_state() if confirm else None

    def set_power(self, on: bool):
        return self.set_light(powered_on=on)

    def version(self, timeout: float = 1.0) -> str:
        return "SIM-1"


class FakeMouseEvent:
    """Reicht der GUI gerade so viel Qt-Ereignis, wie sie selbst anfasst."""

    def __init__(self, button, x: float, y: float):
        from PyQt6.QtCore import QPointF

        self._button = button
        self._position = QPointF(x, y)

    def button(self):
        return self._button

    def position(self):
        return self._position

    def accept(self) -> None:
        pass


CHILD = """
import os, sys
root = os.environ["LLANO_PROBE_ROOT"]
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "tools"))
import gui_probe
from llanotool import cli, device, gui, loop
device.Pad = gui_probe.FakePad
loop.Pad = gui_probe.FakePad
sys.argv = ["llano"] + os.environ["LLANO_PROBE_ARGV"].split()
raise SystemExit(gui.run() if os.environ["LLANO_PROBE_ARGV"] == "gui" else cli.main())
"""


def signal_test(argv: str, name: str) -> bool:
    """Schaltet ein SIGTERM den Kuehler aus? Das ist genau das Signal, das die
    Anmeldung beim Abmelden und Herunterfahren schickt.

    Laeuft in einem eigenen Prozess, weil es auf das echte Signal ankommt und
    nicht auf einen nachgebauten Aufruf.
    """
    import signal as signals
    import subprocess
    import time

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_home = os.environ["XDG_CONFIG_HOME"]
    marker = os.path.join(config_home, f"pad-{name}.json")
    if os.path.exists(marker):
        os.remove(marker)
    env = {**os.environ,
           "LLANO_PROBE_ROOT": root,
           "LLANO_PROBE_MARKER": marker,
           "LLANO_PROBE_ARGV": argv,
           "LLANO_LOCK": os.path.join(config_home, f"lock-{name}"),
           "QT_QPA_PLATFORM": "offscreen"}
    process = subprocess.Popen([sys.executable, "-c", CHILD], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        def pad_state() -> dict:
            try:
                with open(marker, encoding="utf-8") as handle:
                    return json.load(handle)
            except (OSError, ValueError):
                return {}

        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and pad_state().get("powered") is not True:
            if process.poll() is not None:
                break
            time.sleep(0.2)
        if pad_state().get("powered") is not True:
            print(f"       ({argv} kam nicht hoch: {process.stderr.read()[-400:]})")
            return False

        process.send_signal(signals.SIGTERM)
        code = process.wait(timeout=20)
        state = pad_state()
        if code != 0 or state.get("powered") is not False:
            print(f"       (Rueckgabe {code}, letzter Zustand {state}, "
                  f"Meldung: {process.stderr.read()[-400:]})")
        return code == 0 and state.get("powered") is False
    finally:
        if process.poll() is None:
            process.kill()


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/llano-gui.png"
    device.Pad = FakePad
    loop.Pad = FakePad

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QAbstractSpinBox, QApplication

    from llanotool import config as config_mod
    from llanotool.gui import MainWindow, apply_theme

    app = QApplication(sys.argv)
    apply_theme(app)
    controller = loop.Controller(config_mod.load())
    controller.cfg["sensors"] = ["nvidia:GPU"]          # damit der Test planbar bleibt
    if not controller.sensors.read():
        # Ein Bauwagen ohne Temperaturensoren (virtuelle Maschinen haben keine)
        # kann nicht prüfen, was es nicht gibt. Zwei Standwerte setzen, damit
        # die Pruefung unten trotzdem etwas heisst. Auf einem echten Notebook
        # wird dieser Zweig nicht betreten.
        def stand_in_temps(collapse: bool = True) -> dict:
            return {"coretemp:Package id 0": 61.5, "nvidia:GPU": 57.0}

        controller.sensors.read = stand_in_temps
        print("Hinweis: dieser Rechner meldet keine Sensoren, Standwerte eingesetzt")
    window = MainWindow(controller)
    window.resize(1000, 720)
    window.show()

    def pump(seconds: float) -> None:
        import time

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()

    def saved_curve() -> list:
        return saved()["curve"]

    def saved() -> dict:
        with open(config_mod.config_path(), encoding="utf-8") as handle:
            return json.load(handle)

    failures: list[str] = []

    def expect(name: str, condition: bool, dabei: str = "") -> None:
        print(f"  {'ok  ' if condition else 'FEHLT'} {name}")
        if not condition:
            if dabei:
                # Die Pruefung ist auf einem schnellen Rechner green und auf
                # einem beladenen nicht immer: die Zahlen daneben sagen beim
                # naechsten Mal, was der Balken gerade wirklich tut.
                print(f"       dazu: {dabei}")
            failures.append(name)

    pump(1.5)
    window.set_mode("manual")
    window.set_speed(66)
    window.send_light(color=3, effect=1, brightness=128)
    pump(1.2)

    state = window._last_status.get("device") or {}
    print("Schaltflaechen und Regler:")
    expect("Modus Manuell", window._last_status.get("mode") == "manual")
    expect("Stufe 66 % geschrieben", state.get("fan_speed") == 66)
    expect("Farbe lila", state.get("color") == 3)
    expect("Effekt atmend", state.get("effect") == 1)
    expect("Helligkeit 128", state.get("brightness") == 128)
    expect("Regler aktiv", window.fan_slider.isEnabled() and window.fan_slider.value() == 66)
    expect("Sensorwerte da", len(window._last_status.get("temps", {})) > 0)
    expect("Symbol in der Taskleiste", window.tray.isVisible())

    # ------------------------------------- Kuehler beim Start an, beim Ende aus
    print("Ein beim Start, aus beim Beenden:")
    expect("Schalter beim Start an", window.power_start.isChecked())
    expect("Schalter beim Beenden an", window.power_exit.isChecked())
    window.power_exit.setChecked(False)
    pump(0.5)
    expect("Schalter wird gespeichert", saved()["power_off_on_exit"] is False)
    window.power_exit.setChecked(True)
    pump(0.5)
    expect("Schalter bleibt so gespeichert", saved()["power_off_on_exit"] is True)

    controller.finish(power_off=True)
    expect("Programmende schaltet den Kuehler aus", controller.pad.state["powered"] is False)
    controller.set_power(True)
    expect("und der Start schaltet ihn wieder an", controller.pad.state["powered"] is True)
    expect("Luefterstufe bleibt dabei erhalten", controller.pad.state["fan"] > 0)

    expect("echtes SIGTERM schaltet die Oberflaeche aus", signal_test("gui", "gui"))
    expect("echtes SIGTERM schaltet den Daemon aus", signal_test("daemon", "daemon"))

    # ------------------------------- Knöpfe "Auf Kuehler speichern" und Gegenknopf
    print("Knopf 'Auf Kuehler speichern':")
    wanted = dict(controller.cfg["light"])
    controller.pad._state.update({"color": 4, "effect": 2, "brightness": 200})
    pump(0.4)
    expect("Kuehler steht auf etwas anderem als gespeichert",
           controller.pad.state["color"] != int(wanted["color"]))
    window._apply_light_now()
    pump(0.8)
    expect("Knopf schreibt die gespeicherten LEDs zurueck",
           controller.pad.state["color"] == int(wanted["color"])
           and controller.pad.state["effect"] == int(wanted["effect"])
           and controller.pad.state["brightness"] == int(wanted["brightness"]))
    expect("Luefterstufe bleibt dabei unangetastet", controller.pad.state["fan"] == 66)

    print("Knopf 'Vom Kuehler laden':")
    controller.pad._state.update({"color": 4, "effect": 2, "brightness": 200})
    pump(0.4)
    window._load_light_from_pad()
    pump(0.8)
    stored = saved()["light"]
    expect("Das Geraet wird zur neuen Einstellung",
           stored["color"] == 4 and stored["effect"] == 2 and stored["brightness"] == 200)
    expect("Das Fenster zeigt das neue an", window.color_name.text() == "orange")
    expect("Der Kuehler muss dafuer nicht umgestellt werden",
           controller.pad.state["color"] == 4 and controller.pad.state["fan"] == 66)
    window.send_light(**wanted)          # zurueck in den Ausgangszustand
    pump(0.8)
    expect("und laesst sich zuruecknehmen", saved()["light"]["color"] == int(wanted["color"]))

    # ------------------------------------------------- Farbkreise und Ausklapplisten
    print("Farbkreise:")
    dots = window.color_dots
    dots.buttons[0].click()
    pump(0.8)
    expect("Ein Kreis schreibt seine Farbe auf den Kuehler",
           controller.pad.state["color"] == 0)
    expect("und speichert sie", saved()["light"]["color"] == 0)
    expect("Der gewaehlte Kreis ist markiert, die anderen nicht",
           dots.buttons[0].isChecked() and not dots.buttons[2].isChecked())
    expect("Der Name daneben stimmt", window.color_name.text() == "rot")
    alle = True
    for value in sorted(COLORS):
        dots.buttons[value].click()
        pump(0.5)
        alle = alle and saved()["light"]["color"] == value
        alle = alle and window.color_name.text() == COLORS[value]
    expect("Alle fuenf Kreise setzen ihre Farbe", alle)
    window.send_light(color=int(wanted["color"]))
    pump(0.8)
    expect("und lassen sich zurueckdrehen", saved()["light"]["color"] == int(wanted["color"]))

    print("Ausklapplisten:")
    expect("Es sind genau die bekannten Effekte und Tempi",
           [window.effect_box.itemData(i) for i in range(window.effect_box.count())]
           == sorted(EFFECTS)
           and [window.speed_box.itemData(i) for i in range(window.speed_box.count())]
           == sorted(EFFECT_SPEEDS))
    window.effect_box.pick(2)
    pump(0.8)
    expect("Effekt aus der Liste geht aufs Geraet",
           controller.pad.state["effect"] == 2 and saved()["light"]["effect"] == 2)
    window.speed_box.pick(3)
    pump(0.8)
    expect("Tempo aus der Liste ebenso", saved()["light"]["speed"] == 3)
    expect("die Liste zeigt auch, was gilt",
           window.effect_box.currentData() == 2 and window.speed_box.currentData() == 3)
    window.effect_box.set_active(0)          # nachziehen, was das Geraet meldet
    pump(0.5)
    expect("Nachziehen allein schreibt nichts zurueck", saved()["light"]["effect"] == 2)
    window.effect_box.pick(int(wanted["effect"]))
    window.speed_box.pick(int(wanted["speed"]))
    pump(0.8)
    expect("und zurueck in den Ausgangszustand",
           saved()["light"]["effect"] == int(wanted["effect"])
           and saved()["light"]["speed"] == int(wanted["speed"]))

    print("Plus und Minus an den Feldern:")
    expect("Die winzigen Wartepfeile sind weg",
           window.poll.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
           and window.hysteresis.buttonSymbols()
           == QAbstractSpinBox.ButtonSymbols.NoButtons)
    poll_before = window.poll.value()
    window.poll_row.plus.click()
    pump(0.8)
    expect("Plus erhoht den Abstand und speichert ihn",
           window.poll.value() == poll_before + 1
           and saved()["poll_seconds"] == poll_before + 1)
    window.poll_row.minus.click()
    pump(0.8)
    expect("Minus senkt wieder", window.poll.value() == poll_before
           and saved()["poll_seconds"] == poll_before)
    reaction_before = window.hysteresis.value()
    window.hysteresis_row.plus.click()
    pump(0.8)
    expect("Reaktion hat dieselben Knoepfe",
           abs(window.hysteresis.value() - (reaction_before + 0.5)) < 1e-6
           and abs(saved()["hysteresis"] - (reaction_before + 0.5)) < 1e-6)
    window.hysteresis_row.minus.click()
    pump(0.8)
    expect("und die Gegenrichtung", abs(saved()["hysteresis"] - reaction_before) < 1e-6)

    # ---------------------------------------------------- Luefterbalken mit der Maus
    print("Luefterbalken mit der Maus:")
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    left = Qt.MouseButton.LeftButton
    lever = window.fan_slider
    half = lever.height() / 2.0
    speed_before = controller.pad.state["fan"]
    lever.mousePressEvent(FakeMouseEvent(left, 12, half))
    pump(0.4)
    expect("links gefasst heißt niedrig", lever.value() <= 5)
    expect("die große Zahl zieht mit", window.value_label.text() == f"{lever.value()} %")
    lever.mouseMoveEvent(FakeMouseEvent(left, lever.width() * 0.75, half))
    pump(0.4)
    expect("nach rechts wird hoeher", lever.value() > 70)
    expect("waehrend des Ziehens bleibt der Kuehler in Ruhe",
           controller.pad.state["fan"] == speed_before)
    lever.mouseReleaseEvent(FakeMouseEvent(left, lever.width() - 4, half))
    pump(1.0)
    expect("nach dem Loslassen landet die Stufe auf dem Kuehler",
           controller.pad.state["fan"] == lever.value())
    expect("und wird gespeichert", saved()["manual_speed"] == lever.value())
    QApplication.sendEvent(lever, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Home,
                                            Qt.KeyboardModifier.NoModifier))
    pump(1.0)
    expect("Taste Pos1 gibt die kleinste Stufe",
           lever.value() == 1 and controller.pad.state["fan"] == 1)
    window.set_speed(66)
    pump(1.0)
    expect("und zurueck auf 66 Prozent",
           lever.value() == 66 and controller.pad.state["fan"] == 66)

    # ------------------------------------------------------ Helligkeitsbalken
    print("Helligkeitsbalken:")
    bar = window.brightness
    middle_x = bar.width() / 2.0
    # Beide Werte werden direkt nach der Mausgesture abgelesen und nicht erst
    # nach dem Pumpen: Die standige Auffrischung holt den Balken zurueck auf
    # den Wert des Kuehlers, und je nach Zeitpunkt fiel diese Pruefung auf dem
    # Bauwagen mal durch und mal nicht.
    bar.mousePressEvent(FakeMouseEvent(left, middle_x, bar.height() - 3))
    grab_at_bottom = bar.value()
    pump(0.4)
    bar.mouseMoveEvent(FakeMouseEvent(left, middle_x, bar.height() / 2.0))
    grab_in_middle = bar.value()
    pump(0.4)
    # Verglichen wird mit der Mitte desselben Balkens, nicht mit einem
    # Wunschwert: Die Pruefung soll sagen, dass unten dunkler ist als oben --
    # wie hoch der Balken gerade zufaellig ist, spielt dabei keine Rolle.
    expect("unten gefasst heißt dunkel",
           grab_at_bottom < grab_in_middle - 60,
           f"unten {grab_at_bottom}, Mitte {grab_in_middle}, "
           f"Balken {bar.width()}x{bar.height()} Pixel")
    expect("in der Mitte etwa halb", abs(grab_in_middle - 128) <= 16,
           f"Mitte {grab_in_middle} bei {bar.height()} Pixel hoehe")
    expect("und die Zahl daneben zieht mit",
           window.brightness_value.text() == str(bar.value()))
    bar.mouseReleaseEvent(FakeMouseEvent(left, middle_x, bar.height() * 0.2))
    pump(0.9)
    expect("ein Loslassen schreibt auf den Kuehler",
           controller.pad.state["brightness"] == bar.value())
    expect("und speichert die Stufe", saved()["light"]["brightness"] == bar.value())

    QApplication.sendEvent(bar, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_End,
                                          Qt.KeyboardModifier.NoModifier))
    pump(0.9)
    expect("Taste Ende macht volle Helligkeit",
           bar.value() == 255 and controller.pad.state["brightness"] == 255)
    pump(1.2)                              # der letzte Schreibvorgang soll durch sein
    stored = int(saved()["light"]["brightness"])
    bar.set_value(60)                      # so zieht die Oberflaeche einen Wert nach
    gezogen = bar.value()                  # gleich abgelesen, nicht nach dem Pumpen:
    pump(1.2)                              # die standige Auffrischung holt den Balken
                                           # zuruck auf den Wert des Kuehlers
    expect("nachziehen allein schreibt nichts",
           gezogen == 60 and int(saved()["light"]["brightness"]) == stored
           and controller.pad.state["brightness"] == 255,
           f"direkt nach dem Ziehen {gezogen}, Balken jetzt {bar.value()}, "
           f"gespeichert {saved()['light']['brightness']}, "
           f"Kuehler {controller.pad.state['brightness']}, vorher {stored}")
    window.send_light(brightness=int(wanted["brightness"]))
    pump(0.9)
    expect("und zurueck in den Ausgangszustand",
           saved()["light"]["brightness"] == int(wanted["brightness"]))

    # ------------------------------------------------- Maus auf der Kuehlkurve
    print("Lufterkurve mit der Maus:")
    window.grab().save(out)                     # Bild im Ausgangszustand
    view = window.curve_view
    left = Qt.MouseButton.LeftButton
    right = Qt.MouseButton.RightButton
    index = 1
    before = [list(point) for point in controller.cfg["curve"]]
    on_disk = saved_curve()

    view.mousePressEvent(FakeMouseEvent(left, view._x(before[index][0]),
                                       view._y(before[index][1])))
    view.mouseMoveEvent(FakeMouseEvent(left, view._x(60), view._y(80)))
    during = [list(point) for point in controller.cfg["curve"]]
    expect("Punkt folgt der Maus", during[index] == [60.0, 80])
    expect("waehrend des Ziehens keine Schreibarbeit", saved_curve() == on_disk)

    window._show_window()
    pump(0.4)
    window.grab().save(out.replace(".png", "-kurve.png"))   # Punkt in der Hand

    view.mouseReleaseEvent(FakeMouseEvent(left, view._x(60), view._y(80)))
    pump(0.6)
    expect("nach dem Loslassen gespeichert", saved_curve()[index][1] == 80)
    expect("Tabelle zieht mit", window.curve_table.item(index, 1).text() == "80")

    count = len(controller.cfg["curve"])
    view.mouseDoubleClickEvent(FakeMouseEvent(left, view._x(50), view._y(50)))
    pump(0.3)
    expect("Doppelklick fuegt einen Punkt ein", len(controller.cfg["curve"]) == count + 1)

    added = min(range(len(controller.cfg["curve"])),
                key=lambda i: abs(controller.cfg["curve"][i][0] - 50))
    view.mousePressEvent(FakeMouseEvent(right, view._x(controller.cfg["curve"][added][0]),
                                       view._y(controller.cfg["curve"][added][1])))
    pump(0.3)
    expect("Rechtsklick entfernt ihn wieder", len(controller.cfg["curve"]) == count)

    view.remove_point(0)
    view.remove_point(0)
    pump(0.3)
    expect("zwei Punkte bleiben immer uebrig", len(controller.cfg["curve"]) >= 2)
    print(f"Bilder: {out} und {out.replace('.png', '-kurve.png')}")

    # ---- Warum Temperaturen fehlen ----------------------------------------
    # Ein Rechner ohne Messhilfe kennt keine Prozesstemperatur. Das war bisher
    # nur in der Kommandozeile nachzulesen, und die liest niemand, der klickt.
    window.controller.sensors.note = lambda: ("Ohne Messhilfe fehlt die "
                                              "Prozesstemperatur.")
    window._zeige_sensorgrund()
    pump(0.2)
    expect("die Oberflaeche erklaert fehlende Temperaturen",
           not window.sensor_note.isHidden() and "Messhilfe" in window.sensor_note.text())
    expect("und der Satz ist ein Weg zur Messhilfe",
           'href="https://github.com/LibreHardwareMonitor' in window.sensor_note.text())
    window.controller.sensors.note = lambda: None
    window._zeige_sensorgrund()
    expect("und schweigt, wenn nichts fehlt", window.sensor_note.isHidden())

    # ---- Die Einstellungsdatei von frueher --------------------------------
    # Ein Deinstallieren laesst die Datei mit Absicht zurueck, und genau so eine
    # alte oder fremde Datei hat die Oberflaeche schon sterben lassen, nachdem
    # sie den Kuehler eingeschaltet hatte: kein Fenster, keine Meldung, und nach
    # einer Neuinstallation immer noch kein Fenster. Deshalb wird das Fenster
    # hier noch einmal mit zerstoerten Werten gebaut - es muss aufgehen.
    FEINDE = [
        {}, {"mode": None}, {"mode": "kurve"}, {"mode": "web"},
        {"manual_speed": None}, {"sensors": None}, {"sensors": []},
        {"hysteresis": None}, {"poll_seconds": 0}, {"write_interval": "drei"},
        {"light": None}, {"light": {"color": 99}}, {"light": {"speed": None}},
        {"curve": {"45": 20}}, {"curve": [[60, 50]]}, {"power_on_start": "nein"},
    ]
    aufgehen = 0
    for zusatz in FEINDE:
        cfg = config_mod.sauber(zusatz)
        cfg["sensors"] = ["nvidia:GPU"]
        fremd = loop.Controller(cfg)
        fremd.sensors.read = controller.sensors.read
        try:
            fenster = MainWindow(fremd)
        except Exception as ausnahme:                             # noqa: BLE001
            expect(f"Fenster bei {zusatz}", False)
            print(f"        {type(ausnahme).__name__}: {ausnahme}")
            continue
        fenster.worker.stop()
        fenster.deleteLater()
        aufgehen += 1
    expect(f"{len(FEINDE)} zerstoerte Einstellungsdateien lassen ein Fenster zu",
           aufgehen == len(FEINDE))

    # ---- Wenn eine andere Fassung schon am Kuehler sitzt -------------------
    # Der Fall kommt aus dem Autostart: Das Symbol im Hintergrund haelt das
    # Geraet, und der Doppelklick danach darf nicht still stehen bleiben, nur
    # weil niemand eine Frage wegklickt. "Still stehen" sieht naemlich genauso
    # aus wie "gar nicht gestartet" - und das ist hier schon einmal ein ganzer
    # Tag Raten gewesen.
    from llanotool import gui as oberflaeche
    from llanotool.loop import AlreadyRunning

    class Schirm:
        """Ein Bildschirm, der weiss, ob er einer ist."""

        def __init__(self, echt: bool) -> None:
            self.zeilen: list[str] = []
            self._echt = echt

        def isatty(self) -> bool:
            return self._echt

        def write(self, text: str) -> int:
            self.zeilen.append(text)
            return len(text)

    urspruenglich = oberflaeche.config_and_controller
    urspruengliche_frage = oberflaeche.QMessageBox.warning

    def sitzend() -> None:
        raise AlreadyRunning("PID 4711 ist schon da")

    gefragt: list = []
    oberflaeche.config_and_controller = sitzend
    oberflaeche.QMessageBox.warning = staticmethod(
        lambda *arg, **kwargs: gefragt.append(" ".join(map(str, arg))))
    ausgaenge = {}
    try:
        for echt in (True, False):
            schirm = Schirm(echt)
            wirklich = sys.stdout
            sys.stdout = schirm
            gefragt.clear()
            try:
                ausgaenge[echt] = (oberflaeche._run_window(app, None, None, False, False),
                                   "".join(schirm.zeilen), list(gefragt))
            finally:
                sys.stdout = wirklich
    finally:
        oberflaeche.config_and_controller = urspruenglich
        oberflaeche.QMessageBox.warning = urspruengliche_frage

    expect("ein zweites Programm am Kuehler haelt die Oberflaeche nicht an",
           [ende for ende, _, _ in ausgaenge.values()] == [0, 0])
    expect("am Terminal steht der Grund, ohne Frage",
           "4711" in ausgaenge[True][1] and not ausgaenge[True][2])
    expect("ohne Bildschirm wird stattdessen gefragt",
           "4711" in ausgaenge[False][2][0] and not ausgaenge[False][1])

    window.worker.stop()
    if failures:
        print(f"\n{len(failures)} Punkt(e) fehlgeschlagen: {', '.join(failures)}")
        return 1
    print("\nAlle Punkte der Oberflaeche funktionieren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

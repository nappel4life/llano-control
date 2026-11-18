"""Command line interface for the llano V12 Ultra."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time

from . import config as config_mod
from . import protocol
from .curve import interpolate
from .device import IS_WINDOWS, Pad, backend, describe_nodes
from .device_common import DeviceNotFound, usb_id
from .loop import Controller, daemon_running
from .protocol import COLORS, EFFECTS, EFFECT_SPEEDS
from .sensors import Sensors


def _lookup(text: str, table: dict[str], kind: str) -> int:
    """Accept "2", "gruen" or "regenbogen" for a numbered setting."""
    try:
        value = int(text)
    except ValueError:
        lowered = text.lower().replace("-", "_")
        for number, name in table.items():
            if name.lower().replace("_", "-") == lowered or name.lower() == lowered:
                return number
        options = ", ".join(f"{n}={name}" for n, name in table.items())
        raise SystemExit(f"unbekannter {kind} '{text}'. Moeglich: {options}")
    if value not in table:
        options = ", ".join(f"{n}={name}" for n, name in table.items())
        raise SystemExit(f"{kind} {value} gibt es nicht. Moeglich: {options}")
    return value


def _fan_arg(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise SystemExit(f"Lueftergeschwindigkeit muss eine Zahl sein, nicht '{text}'")
    if not protocol.FAN_MIN <= value <= protocol.FAN_MAX:
        raise SystemExit(f"Bitte eine Zahl zwischen {protocol.FAN_MIN} und {protocol.FAN_MAX}")
    return value


def _print_state(state) -> None:
    print(f"  Luefter    : {state.fan_speed}%  (Anzeige ~{state.rpm_display} U/min)")
    print(f"  An/Aus     : {'an' if state.powered_on else 'aus'}")
    print(f"  LEDs       : {'an' if state.light_on else 'aus'}")
    print(f"  Effekt     : {state.effect} = {state.effect_name}")
    print(f"  Farbe      : {state.color} = {state.color_name}")
    print(f"  Effekttakt : {state.effect_speed} = {EFFECT_SPEEDS.get(state.effect_speed, '?')}")
    print(f"  Helligkeit : {state.brightness}")
    print(f"  Rohdaten   : {state.raw.hex(' ')}")


def _open(args) -> Pad:
    if daemon_running():
        print(
            "Hinweis: Es laeuft ein llano-Daemon. Der Daemon wuerde die Aenderung "
            "binnen weniger Sekunden zuruecksetzen.\n"
            "           Fuer dauerhafte Einstellungen besser die Oberflaeche nutzen: llano gui\n",
            file=sys.stderr,
        )
    try:
        return Pad(getattr(args, "node", None))
    except DeviceNotFound as exc:
        raise SystemExit(f"Fehler: {exc}")


def cmd_status(args) -> int:
    nodes = describe_nodes()
    if not nodes:
        print("Kein llano V12 Ultra gefunden (USB 374a:b101).")
        return 1
    blocked = [n["node"] for n in nodes if not n["readable"]]
    if blocked and not any(n["readable"] for n in nodes):
        print("Geraet gefunden, aber dieser Benutzer kommt nicht daran vorbei:")
        for node in blocked:
            print(f"  {node}")
        if IS_WINDOWS:
            print(f"\n{backend.PERMISSION_HINT}")
        else:
            print("\nEinmalig als Root installieren:")
            print("  sudo cp contrib/70-llano.rules /etc/udev/rules.d/")
            print("  sudo udevadm control --reload-rules && sudo udevadm trigger")
            print("Danach den Stecker einmal ziehen und wieder stecken.")
        return 1
    with _open(args) as pad:
        print(f"Geraet: {pad.node}" + (f" (+{len(pad.other_nodes)} weitere)" if pad.other_nodes else ""))
        _print_state(pad.read_state())
        if getattr(args, "firmware", False):
            try:
                version = pad.version()
            except Exception:
                version = None
            print(f"Firmware : {version or 'keine Antwort'}")
    return 0


def cmd_fan(args) -> int:
    with _open(args) as pad:
        state = pad.set_fan(args.speed)
        print(f"Luefter auf {args.speed}% gesetzt")
        if state and state.fan_speed != args.speed:
            print(f"  gemeldet zurueck: {state.fan_speed}% (Hochlauf abwarten)")
    return 0


def cmd_light(args) -> int:
    with _open(args) as pad:
        state = pad.read_state()
        keep_fan = state.fan_speed
        changes: dict = {}
        if args.color is not None:
            changes["color"] = _lookup(args.color, COLORS, "Farbe")
        if args.effect is not None:
            changes["effect"] = _lookup(args.effect, EFFECTS, "Effekt")
        if args.speed is not None:
            changes["effect_speed"] = _lookup(args.speed, EFFECT_SPEEDS, "Effekttakt")
        if args.brightness is not None:
            changes["brightness"] = max(0, min(255, args.brightness))
        if args.on is not None:
            changes["light_on"] = args.on
        if not changes:
            _print_state(state)
            return 0
        state = pad.set_light(fan_speed=keep_fan, **changes)
        print("LEDs aktualisiert (Luefter blieb bei {}%)".format(keep_fan))
        _print_state(state)
        if args.save:
            cfg = config_mod.load()
            cfg["light"] = {
                "on": state.light_on,
                "color": state.color,
                "effect": state.effect,
                "speed": state.effect_speed,
                "brightness": state.brightness,
            }
            print("Konfiguration gespeichert:", config_mod.save(cfg))
    return 0


def _power_target(args) -> bool:
    """Both "llano power an" and "llano power --off" mean the same thing."""
    value = args.zustand
    if isinstance(value, bool):
        return value
    if value is None:
        raise SystemExit("Bitte dazuschreiben: llano power an  oder  llano power aus")
    word = value.lower()
    if word in ("an", "ein", "on", "1", "true", "yes", "ja"):
        return True
    if word in ("aus", "off", "0", "false", "no", "nein"):
        return False
    raise SystemExit(f"Moeglich ist 'an' oder 'aus', nicht '{value}'")


def cmd_power(args) -> int:
    """The pad's master switch.

    Also what the boot and shutdown service calls, so it has to cope with a pad
    that has not been enumerated yet (`--wait`) and with a daemon that already
    owns it (`--if-free`).
    """
    target = _power_target(args)
    if args.if_free and daemon_running():
        print("Ein anderer llano-Prozess hat den Kuehler uebernommen - der schaltet selbst.")
        return 0
    deadline = time.monotonic() + max(0.0, args.wait)
    while True:
        try:
            with _open(args) as pad:
                state = pad.set_power(target)
                print("Kuehler " + ("eingeschaltet" if target else "ausgeschaltet"))
                _print_state(state)
            return 0
        except DeviceNotFound:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1.0)


def cmd_sensors(args) -> int:
    source = Sensors()
    temps = source.read(collapse=not args.all)
    if not temps:
        print("Keine Temperatursensoren gefunden.")
        note = source.note()
        if note:
            print(f"\n{note}")
        return 1
    width = max(len(key) for key in temps)
    for key in sorted(temps):
        print(f"{key:<{width}}  {temps[key]:6.1f} degC")
    cfg = config_mod.load()
    print("\nIn der Luefterkurve aktiv:")
    for name in cfg["sensors"]:
        mark = "+" if name in temps else "-"
        value = temps.get(name)
        print(f"  {mark} {name}" + (f"  {value:.1f} degC" if value is not None else "  (fehlt)"))
    if not any(name in temps for name in cfg["sensors"]):
        example = sorted(temps)[0]
        print(
            "\nKeiner der eingestellten Sensoren existiert auf diesem Rechner, die "
            "Kurve haelt dann die letzte Stufe.\n"
            "Ander so:   llano config --set 'sensors=[\"%s\"]'" % example
        )
    note = source.note()
    if note:
        print(f"\nHinweis: {note}")
    return 0


def cmd_curve(args) -> int:
    cfg = config_mod.load()
    for temp in args.temps:
        print(f"{temp:>5.1f} degC -> {interpolate(cfg['curve'], temp):>3d}%")
    return 0


def cmd_daemon(args) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = config_mod.load()
    controller = Controller(cfg)
    if args.dry_run:
        print("Trockenlauf: es werden keine Kommandos an den Kuehler geschickt.")
        while True:
            temps = controller.read_temps()
            temp = controller.reference_temp
            want = interpolate(cfg["curve"], temp) if temp is not None else None
            print(
                f"{_now()}  Referenz {temp if temp is None else round(temp, 1)} degC"
                f"  ->  {want}%   ({cfg['mode']})"
            )
            _sleep(cfg["poll_seconds"])
        return 0
    _install_signals(controller)
    controller.run()
    return 0


def cmd_gui(args) -> int:
    try:
        from .gui import run
    except ImportError as exc:
        raise SystemExit(
            "Fuer die Oberflaeche wird PyQt6 benoetigt:\n"
            "  sudo pacman -S --needed python-pyqt6\n"
            f"(Einzelheit: {exc})\n"
            "Ohne Oberflaeche gehen weiterhin: llano daemon, llano status, llano fan, llano light"
        )
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    return run(start_minimized=args.minimized, tray_only=args.tray)


def cmd_rules(args) -> int:
    if IS_WINDOWS:
        print(
            "Unter Windows braucht der Kuehler keine Regel: jedes angemeldete "
            "Programm darf auf ihn zugreifen.\n"
            "Nur wenn die Hersteller-Oberflaeche (MythCool) laeuft, haelt die "
            "das Geraet manchmal fuer sich."
        )
        return 0
    print(
        'SUBSYSTEM=="usb", ATTR{idVendor}=="374a", ATTR{idProduct}=="b101", '
        'MODE="0666", TAG+="uaccess"\n'
        'KERNEL=="hidraw*", ATTRS{idVendor}=="374a", ATTRS{idProduct}=="b101", '
        'MODE="0666", TAG+="uaccess"'
    )
    return 0


def cmd_selftest(args) -> int:
    """Was dieses Gerat auf diesem Rechner kann - Schritt fuer Schritt.

    Besonders auf dem Windows-Weg hilfreich, wo noch niemand das Geraet in der
    Hand hatte: jeder Schritt steht fuer sich da, mit dem Grund, warum er nicht
    ging.
    """
    import os
    import platform

    from . import config as _cfg
    from .loop import DeviceLock, lock_path, read_locked_pid

    print(f"Betriebssystem : {platform.system()} {platform.release()} "
          f"({platform.machine()})")
    print(f"Python         : {platform.python_version()}")
    print(f"Gerateweg      : {backend.__name__.split('.')[-1]}")
    print(f"Konfiguration  : {_cfg.config_path()}")
    print(f"Sperrdatei     : {lock_path()}")

    # Dieselbe Datei wie bei der Rust-Fassung, und nur sie verhindert, dass zwei
    # Steuerungen dem Kuehler gleichzeitig ihre Statusanfrage schicken. Laeuft
    # schon eine, sind ihre Meldungen die nuetzlicheren als jede Geraetezeit.
    versuch = DeviceLock()
    if versuch.acquire(exclusive_request=False):
        print("Andere Fassung : keine - dieses Programm ist allein am Geraet")
        versuch.release()
    else:
        print(f"Andere Fassung : laeuft schon (PID {read_locked_pid(lock_path()) or '?'})"
              " - ihm gehoert das Geraet")

    ok = True
    try:
        import PyQt6.QtCore  # noqa: F401
        print("Oberflaeche    : PyQt6 gefunden")
    except Exception as exc:                          # pragma: no cover
        ok = False
        print(f"Oberflaeche    : PyQt6 fehlt ({exc.__class__.__name__}) - "
              "Kommandozeile geht trotzdem")

    nodes = describe_nodes()
    zaehlen = getattr(backend, "interface_count", None)
    if zaehlen is not None:
        # Die Zahl trennt die beiden Faelle: der Kuehler taucht in keiner
        # Aufzaehlung auf, oder er taucht auf und laesst sich nicht oeffnen.
        print(f"Schnittstellen : {zaehlen()} am Rechner, davon {len(nodes)} mit der "
              f"Kennung {usb_id()}")
    if not nodes:
        ok = False
        print(f"Kuehler        : keiner gefunden (USB {usb_id()})")
    else:
        for node in nodes:
            if not node["readable"]:
                ok = False
            print(f"Kuehler        : {node['node']}"
                  f"{' - zugaenglich' if node['readable'] else ' - KEIN ZUGRIFF'}")
            if node.get("grund"):
                print(f"                 : {node['grund']}")

    bericht = getattr(backend, "scan_report", None)
    if bericht is not None and (not nodes or (zaehlen is not None
                                              and zaehlen() == 0)):
        # "0 am Rechner" auf einem Rechner mit Tastatur heisst nicht "kein
        # Kuehler", sondern "die Suche selbst kam nicht los". Wo sie festfaellt
        # steht dann hier, statt dass darueber geraten wird.
        for zeile in bericht():
            print(f"                 {zeile}")

    if any(node["readable"] for node in nodes):
        try:
            with Pad() as pad:
                # Absichtlich ohne Statusanfrage: die ist ein Schreibvorgang,
                # und dieses Programm hier will nichts verandern, schon gar
                # nicht, wenn gerade die Oberflaeche am Geraet hangt.
                state = pad.read_state(refresh=False)
            print(f"Gelesen        : {state.fan_speed}% Stufe, "
                  f"{'an' if state.powered_on else 'aus'}")
        except Exception as exc:
            ok = False
            print(f"Gelesen        : fehlgeschlagen - {exc}")
        if daemon_running():
            print("                 (es laeuft bereits eine Steuerung; die schreibt auch)")

    source = Sensors()
    temps = source.read()
    if temps:
        warmest = max(temps, key=temps.get)
        print(f"Temperaturen   : {len(temps)} gefunden, "
              f"waermste {temps[warmest]:.0f} degC an {warmest}")
    else:
        ok = False
        print("Temperaturen   : keine gefunden")
    note = source.note()
    if note:
        print(f"                 {note}")

    print()
    print("Alles da, was zum Kuehlen noetig ist." if ok
          else "Siehe die Punkte oben - mindestens einer fehlt noch.")
    return 0 if ok else 1


def cmd_config(args) -> int:
    cfg = config_mod.load()
    if args.set:
        for pair in args.set:
            try:
                key, raw = pair.split("=", 1)
            except ValueError:
                raise SystemExit(f"Erwartet schluessel=wert, bekommen: {pair}")
            if key == "curve":
                cfg["curve"] = json.loads(raw)
            elif key == "sensors":
                cfg["sensors"] = json.loads(raw)
            else:
                try:
                    cfg[key] = json.loads(raw)
                except ValueError:
                    cfg[key] = raw
        print("Gespeichert:", config_mod.save(cfg))
    print(json.dumps(cfg, indent=2, ensure_ascii=False))
    return 0


def _now() -> str:
    import datetime

    return datetime.datetime.now().strftime("%H:%M:%S")


def _sleep(seconds: float) -> None:
    import time

    time.sleep(max(0.5, float(seconds)))


def _install_signals(controller: Controller) -> None:
    def stop(_signum, _frame):
        print("\nBeende Steuerung ...", file=sys.stderr)
        controller.disconnect()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llano",
        description="llano V12 Ultra Notebookkuehler unter Linux und Windows steuern "
                    "(Luefter in Abhaengigkeit von Temperaturensoren, LEDs und Effekte).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--node",
                        help="Geraetepfad, falls mehrere Kuehler haengen "
                             "(/dev/hidrawX beziehungsweise der Windows-Pfad)")
    parser.add_argument("--json", action="store_true", help="Maschinenlesbar ausgeben")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("status", help="Geraetestatus anzeigen (Standard)")
    p.add_argument("--firmware", action="store_true",
                   help="ausserdem die Firmware abfragen (stoert kurz den Bericht)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("fan", help="Lueftergeschwindigkeit setzen")
    p.add_argument("speed", type=_fan_arg, help="1-100 Prozent")
    p.set_defaults(func=cmd_fan)

    p = sub.add_parser("light", help="Farbe, Effekt, Takt und Helligkeit der LEDs")
    p.add_argument("--color", help="0-4 | rot, hellblau, gruen, lila, orange")
    p.add_argument("--effect", help="0-4 | durchgehend, atmend, regenbogen, lauflicht, zonen")
    p.add_argument("--speed", help="0-3 (0 = schnellster Wechsel)")
    p.add_argument("--brightness", type=int, help="0-255")
    p.add_argument("--on", action="store_true", default=None, help="LEDs an")
    p.add_argument("--off", action="store_false", dest="on", help="LEDs aus (Luefter laeuft weiter)")
    p.add_argument("--save", action="store_true", help="als neue Standard-LEDs speichern")
    p.set_defaults(func=cmd_light)

    p = sub.add_parser("power", help="Kuehler ganz ein- oder ausschalten")
    p.add_argument("zustand", nargs="?", default=None,
                   help="an oder aus (auch: ein, aus, on, off)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--on", action="store_const", const=True, dest="zustand",
                       help="ein, in Kurzform")
    group.add_argument("--off", action="store_const", const=False, dest="zustand",
                       help="aus, in Kurzform")
    p.add_argument("--wait", type=float, default=0.0, metavar="SEKUNDEN",
                   help="so lange auf den Kuehler warten, weil der beim Start "
                        "manchmal erst eine Sekunde spaeter da ist")
    p.add_argument("--if-free", action="store_true",
                   help="nichts tun, wenn Oberflaeche oder Daemon den Kuehler "
                        "schon besitzen (fuer den systemd-Dienst)")
    p.set_defaults(func=cmd_power)

    p = sub.add_parser("sensors", help="verfuegbare Temperaturen anzeigen")
    p.add_argument("--all", action="store_true",
                   help="auch jeden einzelnen CPU-Kern anzeigen")
    p.set_defaults(func=cmd_sensors)

    p = sub.add_parser("curve", help="Luefterkurve fuer Temperaturen auswerten")
    p.add_argument("temps", type=float, nargs="+", help="Temperaturen in Grad Celsius")
    p.set_defaults(func=cmd_curve)

    p = sub.add_parser("daemon", help="Luefterkurve dauerhaft anwenden")
    p.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts schreiben")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_daemon)

    p = sub.add_parser("gui", help="Oberflaeche mit Taskleisten-Symbol starten")
    p.add_argument("--minimized", action="store_true", help="minimiert starten")
    p.add_argument("--tray", action="store_true",
                   help="nur als Taskleisten-Symbol starten, ohne Fenster")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="im Terminal mitprotokollieren, was an den Kuehler geht")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("config", help="Konfiguration anzeigen oder aendern")
    p.add_argument("--set", nargs="*", metavar="schluessel=wert",
                   help='z.B. --set mode=manual manual_speed=70')
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("rules", help="udev-Regel ausgeben (nur Linux)")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("selftest",
                       help="pruefen, was Rechner und Kuehler zusammen koennen")
    p.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args.command = "status"
        args.func = cmd_status
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

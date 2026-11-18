"""Reading and writing the settings file.

Linux and macOS keep it at ``~/.config/llano/config.json`` (or wherever
``XDG_CONFIG_HOME`` points), Windows at ``%APPDATA%\\llano\\config.json``, which
is where a Windows user looks for it and which survives an uninstall of the
program itself.

Surviving is the point: the file holds the curve somebody worked out. But it
also comes back from another program, an older version, or a hand in a text
editor, so everything read from it is brought into shape before it is handed
on. See :func:`sauber`.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile

from . import __version__, protocol

APP_NAME = "llano"

DEFAULTS: dict = {
    # "auto" follows the curve, "manual" keeps manual_speed.
    "mode": "auto",
    "manual_speed": 60,
    # Sensors the curve reacts to. The hottest of them wins.
    "sensors": ["coretemp:Package id 0", "nvidia:GPU"],
    # [degrees, percent]
    "curve": [[45, 20], [55, 35], [65, 50], [75, 70], [85, 90], [92, 100]],
    "hysteresis": 3.0,
    "poll_seconds": 3.0,
    # Never rewrite the pad more often than this many seconds.
    "write_interval": 5.0,
    # Only touch the pad when the speed moved by at least this much.
    "min_speed_step": 2,
    "light": {
        "on": True,
        "color": 2,
        "effect": 0,
        "speed": 0,
        "brightness": 255,
    },
    # The pad has a mainswitch of its own. Turn it on when this program starts
    # and off again when it ends -- "ends" includes logging out and shutting
    # the machine down, because the session stops this program then.
    "power_on_start": True,
    "power_off_on_exit": True,
}


def config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(base, APP_NAME)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


def config_path() -> str:
    return os.environ.get("LLANO_CONFIG") or os.path.join(config_dir(), "config.json")


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def sauber(aus_datei) -> dict:
    """Aus einer beliebigen Datei eine brauchbare Einstellungsdatei machen.

    Die Datei ueberlebt eine Deinstallation mit Absicht - sie enthaelt die
    Kurve, die sich jemand erarbeitet hat. Was aber drinstehen kann, wenn eine
    andere Fassung, die Rust-Seite oder eine Hand im Texteditor mitgeschrieben
    hat, ist alles moegliche: fehlende Schluessel, null, Texte statt Zahlen,
    Zahlen ausserhalb des Bereichs, ein Modus, den es so nicht mehr gibt.

    Jeder dieser Werte wurde bisher ungeprueft weitergereicht, und einer genugt,
    um das Fenster beim Bauen umzubringen: Der Kuehler ist dann eingeschaltet,
    die Oberflaeche kommt nicht mehr - und weil die Datei ein Deinstallieren
    uebersteht, hilft auch ein neues Programm nicht. Also wird hier alles auf
    eine Form gebracht, bevor irgendwo ein ``int()`` oder ``float()`` darauf
    loslaeuft.
    """
    cfg = _merge(DEFAULTS, aus_datei if isinstance(aus_datei, dict) else {})
    licht = cfg.get("light") if isinstance(cfg.get("light"), dict) else {}
    out = {
        # Die Fassung, die die Datei zuletzt geschrieben hat. Leer, wenn das
        # eine unbekannte war - die Selbstdiagnose nennt sie dann als uebernommen.
        "version": str(cfg.get("version") or "").strip(),
        "mode": _modus(cfg.get("mode")),
        "manual_speed": _zahl(cfg.get("manual_speed"), DEFAULTS["manual_speed"],
                              0, 100, glatt=True),
        "sensors": _messstellen(cfg.get("sensors")),
        "curve": _normalise_curve(cfg.get("curve")),
        "hysteresis": _zahl(cfg.get("hysteresis"), DEFAULTS["hysteresis"], 0.0, 25.0),
        "poll_seconds": _zahl(cfg.get("poll_seconds"), DEFAULTS["poll_seconds"],
                              0.5, 3600.0),
        "write_interval": _zahl(cfg.get("write_interval"), DEFAULTS["write_interval"],
                                0.2, 3600.0),
        "min_speed_step": _zahl(cfg.get("min_speed_step"), DEFAULTS["min_speed_step"],
                                0, 50, glatt=True),
        "light": {
            "on": _schalter(licht.get("on"), DEFAULTS["light"]["on"]),
            "color": _zahl(licht.get("color"), DEFAULTS["light"]["color"],
                           0, len(protocol.COLORS) - 1, glatt=True),
            "effect": _zahl(licht.get("effect"), DEFAULTS["light"]["effect"],
                            0, len(protocol.EFFECTS) - 1, glatt=True),
            "speed": _zahl(licht.get("speed"), DEFAULTS["light"]["speed"],
                           0, len(protocol.EFFECT_SPEEDS) - 1, glatt=True),
            "brightness": _zahl(licht.get("brightness"), DEFAULTS["light"]["brightness"],
                                0, 255, glatt=True),
        },
        "power_on_start": _schalter(cfg.get("power_on_start"),
                                    DEFAULTS["power_on_start"]),
        "power_off_on_exit": _schalter(cfg.get("power_off_on_exit"),
                                       DEFAULTS["power_off_on_exit"]),
    }
    return out


# Wege, auf denen ein Modus geschrieben werden kann. "kurve" kommt von der
# Rust-Fassung, "automatisch" und "manuell" von der Oberflaeche selbst.
_MODUS_WEGE = {
    "auto": "auto", "automatisch": "auto", "kurve": "auto", "curve": "auto",
    "manual": "manual", "manuell": "manual", "manuelle stufe": "manual",
    "stufe": "manual", "direkt": "manual",
}


def _modus(wert) -> str:
    text = str(wert if wert is not None else "").strip().lower()
    text = _MODUS_WEGE.get(text, text)
    return text if text in ("auto", "manual") else DEFAULTS["mode"]


def _modus_verstanden(wert) -> bool:
    """Ist dieser Modus eine der Schreibweisen, die jemand meinen kann?

    "kurve" stammt von der Rust-Fassung, "automatisch" von der Oberflaeche.
    Beides ist geradeso recht - nur worueber niemand etwas weiss, darauf wird
    unten aufmerksam gemacht.
    """
    text = str(wert if wert is not None else "").strip().lower()
    return text in _MODUS_WEGE


def _zahl(wert, standard, unten=None, oben=None, glatt: bool = False):
    """Eine Zahl aus der Datei, oder die Vorgabe, wenn dort Unsinn steht."""
    try:
        if isinstance(wert, bool):
            raise ValueError("wahr ist keine Stufe")
        zahl = float(wert)
    except (TypeError, ValueError):
        zahl = float(standard)
    if unten is not None:
        zahl = max(float(unten), zahl)
    if oben is not None:
        zahl = min(float(oben), zahl)
    return int(round(zahl)) if glatt else zahl


def _schalter(wert, standard: bool) -> bool:
    """Ein An/Aus, auch wenn in der Datei "nein" steht."""
    if isinstance(wert, bool):
        return wert
    if isinstance(wert, (int, float)):
        return bool(wert)
    if isinstance(wert, str):
        return wert.strip().lower() in ("1", "ja", "an", "on", "true", "wahr")
    return standard


def _messstellen(wert) -> list[str]:
    """Die markierten Messstellen, auch wenn die Datei einen Text statt einer Liste hat.

    Eine leere Liste ist keine Beschadigung, sondern eine Entscheidung: niemand
    hat die Kurve an eine Messstelle gehangen. Was fehlt oder null ist, ist
    dagegen nichts gesagt - dann gelten die Vorgabemessstellen.
    """
    if wert is None:
        return copy.deepcopy(DEFAULTS["sensors"])
    if isinstance(wert, str):
        wert = [wert]
    out: list[str] = []
    for eintrag in (wert or []):
        text = str(eintrag).strip()
        if text and text not in out:
            out.append(text)
    return out


def load(sammel: list | None = None) -> dict:
    """Return the configuration, usable whatever the file happened to hold.

    Was nicht zu gebrauchen war, wird laut gesagt - ausser der Anrufer haelt
    ein Sammelglas hin, in das die Meldungen gefuellt werden. Die
    Selbstdiagnose tut das, damit ihre Antwort nicht mitten drin zerrissen
    wird.
    """
    path = config_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return sauber({})
    except (OSError, ValueError) as exc:
        meldung = (f"{path} ist beschadigt ({exc}), Standardwerte werden benutzt")
        if sammel is None:
            print(f"warn: {meldung}", flush=True)
        else:
            sammel.append(meldung)
        return sauber({})
    cfg = sauber(data)
    warne_ueber(data, cfg, path, sammel)
    return cfg


_WARN_SCHLUESSEL = ("mode", "manual_speed", "hysteresis", "poll_seconds",
                    "write_interval", "min_speed_step", "power_on_start",
                    "power_off_on_exit")


def warne_ueber(aus_datei, cfg: dict, ort: str | None = None,
                sammel: list | None = None) -> None:
    """Sag laut, was aus der Datei nicht zu gebrauchen war.

    Still schweigen waere die schlechteste Loesung: Jemand hat sich eine Kurve
    und eine Beleuchtung erarbeitet, und ohne diesen Satz waere der einzige
    Eindruck, dass irgendetwas anders ist als fruher.
    """
    if not isinstance(aus_datei, dict):
        return
    pfad = ort or config_path()

    def melde(text: str) -> None:
        if sammel is None:
            print(f"warn: {text}", flush=True)
        else:
            sammel.append(text)

    for schluessel in _WARN_SCHLUESSEL:
        if schluessel not in aus_datei:
            continue
        if schluessel == "mode" and _modus_verstanden(aus_datei["mode"]):
            continue              # "kurve" und "automatisch" sind keine Schaden
        if aus_datei[schluessel] != cfg[schluessel]:
            melde(f"{schluessel} in {pfad} war nicht zu gebrauchen "
                  f"({aus_datei[schluessel]!r}); benutzt wird {cfg[schluessel]!r}")
    licht = aus_datei.get("light")
    if isinstance(licht, dict):
        for schluessel, wert in cfg["light"].items():
            if schluessel in licht and licht[schluessel] != wert:
                melde(f"Licht/{schluessel} in {pfad} war nicht zu gebrauchen "
                      f"({licht[schluessel]!r}); benutzt wird {wert!r}")


def save(cfg: dict) -> str:
    """Write the configuration atomically and return its path."""
    path = config_path()
    daten = dict(cfg)
    # Dazu gehoert die Datei jetzt: Die naechste Fassung sieht, wann sie
    # geschrieben wurde, und die Selbstdiagnose kann sagen, wenn etwas aus
    # einer alten uebernommen werden musste.
    daten["version"] = __version__
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".cfg", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(daten, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _normalise_curve(raw) -> list[list[float]]:
    """Keep only usable breakpoints, sorted by temperature.

    Only pairs of a list or a tuple count as points. A mapping in the file is
    worth nothing here -- and taking its keys apart would invent points: from
    ``{"45": 20}`` becomes "45"[0], "45"[1], a perfectly readable pair 4 and 5.
    """
    points = []
    for item in raw or []:
        if not isinstance(item, (list, tuple)):
            continue
        try:
            temp = float(item[0])
            speed = int(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        points.append([temp, max(1, min(100, speed))])
    points.sort(key=lambda p: p[0])
    return points or copy.deepcopy(DEFAULTS["curve"])

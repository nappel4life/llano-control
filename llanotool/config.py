"""Reading and writing the settings file.

Linux and macOS keep it at ``~/.config/llano/config.json`` (or wherever
``XDG_CONFIG_HOME`` points), Windows at ``%APPDATA%\\llano\\config.json``, which
is where a Windows user looks for it and which survives an uninstall of the
program itself.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile

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


def load() -> dict:
    """Return the configuration, falling back to defaults if absent."""
    path = config_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return copy.deepcopy(DEFAULTS)
    except (OSError, ValueError) as exc:
        print(f"warn: {path} ist beschadigt ({exc}), Standardwerte werden benutzt", flush=True)
        return copy.deepcopy(DEFAULTS)
    cfg = _merge(DEFAULTS, data if isinstance(data, dict) else {})
    cfg["curve"] = _normalise_curve(cfg.get("curve"))
    return cfg


def save(cfg: dict) -> str:
    """Write the configuration atomically and return its path."""
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".cfg", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, indent=2, ensure_ascii=False)
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
    """Keep only usable breakpoints, sorted by temperature."""
    points = []
    for item in raw or []:
        try:
            temp = float(item[0])
            speed = int(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        points.append([temp, max(1, min(100, speed))])
    points.sort(key=lambda p: p[0])
    return points or copy.deepcopy(DEFAULTS["curve"])

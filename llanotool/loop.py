"""The control loop, and the lock that keeps a single process on the device.

The pad has no acknowledgement and no arbitration: a second process writing a
light report also writes the fan byte, which silently changes the speed. So
one process owns the device (guarded by a lock on a lock file) and anything
else goes through it - the interface is served by the same process that runs
the loop.
"""

from __future__ import annotations

import errno
import logging
import os
import threading
import time

from . import config as config_mod
from .curve import CurveFollower, interpolate
from .device import DeviceNotFound, Pad
from .sensors import Sensors

log = logging.getLogger("llano")

_LIGHT_FIELDS = ("on", "color", "effect", "speed", "brightness")

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:                                    # Windows has no flock
    import msvcrt
else:
    import fcntl


def runtime_dir() -> str:
    """Where the lock file lives: a directory only this user may write."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "llano")
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, "llano")


def lock_path() -> str:
    return os.environ.get("LLANO_LOCK") or os.path.join(runtime_dir(), "daemon.lock")


class AlreadyRunning(RuntimeError):
    def __init__(self, other_pid: int | None):
        super().__init__(
            f"Es laeuft bereits ein llano-Daemon (PID {other_pid}). "
            "Er ist der einzige Besitzer des Geraets - bitte ueber ihn steuern: "
            "llano gui"
        )
        self.other_pid = other_pid


class DeviceLock:
    """Operating-system ownership of the cooling pad: one process, one lock."""

    def __init__(self):
        self._fh = None
        self.path = lock_path()

    def acquire(self, exclusive_request: bool = True) -> bool:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            _lock(handle)
        except OSError as exc:
            handle.close()
            # Windows reports a taken byte-range lock without an errno worth
            # testing, so there the exception itself is the whole answer.
            if (exc.errno in (errno.EACCES, errno.EAGAIN) or IS_WINDOWS) and exclusive_request:
                raise AlreadyRunning(read_locked_pid(self.path)) from exc
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._fh = handle
        return True

    def release(self) -> None:
        if self._fh is not None:
            try:
                _unlock(self._fh)
            finally:
                self._fh.close()
                self._fh = None


def _lock(handle) -> None:
    """Take the whole-file lock without waiting. OSError when it is taken."""
    if IS_WINDOWS:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle) -> None:
    if IS_WINDOWS:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_locked_pid(path: str) -> int | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return int(handle.read().strip() or 0) or None
    except (OSError, ValueError):
        return None


def daemon_running() -> bool:
    """True when another process currently owns the pad."""
    path = lock_path()
    if not os.path.exists(path):
        return False
    pid = read_locked_pid(path)
    if pid is None or pid == os.getpid():
        return False
    probe = DeviceLock()
    handle = open(path, "a+", encoding="utf-8")
    try:
        _lock(handle)
    except OSError:
        return True
    finally:
        try:
            _unlock(handle)
        except OSError:
            pass
        handle.close()
    return False


class Controller:
    """Owns the pad, the sensors and the configuration."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg if cfg is not None else config_mod.load()
        self.sensors = Sensors()
        self.pad: Pad | None = None
        self.follower = CurveFollower(self.cfg["curve"], self.cfg["hysteresis"])
        self.lock = DeviceLock()
        # The GUI polls in its own thread while the window writes on clicks;
        # only one of us may talk to the pad at a time.
        self.io = threading.RLock()
        self.last_write = 0.0
        self.last_state = None
        self.last_temps: dict[str, float] = {}
        self.target: int | None = None
        self.last_error: str | None = None
        self.reconnect_after = 0.0
        self._light_signature = None

    # ---------------------------------------------------------------- device

    def connect(self) -> Pad:
        if self.pad is None or self.pad.closed:
            self.pad = Pad()
            self.follower.reset()
            self._light_signature = None
            log.info("gekoppelt an %s", self.pad.node)
        return self.pad

    def disconnect(self) -> None:
        if self.pad is not None:
            self.pad.close()
            self.pad = None

    def ensure_connected(self) -> Pad | None:
        now = time.monotonic()
        if self.pad is not None and not self.pad.closed:
            return self.pad
        if now < self.reconnect_after:
            return None
        try:
            return self.connect()
        except DeviceNotFound as exc:
            if self.last_error != str(exc):
                log.warning("%s", exc)
            self.last_error = str(exc)
            self.disconnect()
            self.reconnect_after = now + 5.0
            return None

    # ------------------------------------------------------------ measurement

    def read_temps(self) -> dict[str, float]:
        try:
            self.last_temps = self.sensors.read()
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("sensor error: %s", exc)
        return self.last_temps

    @property
    def reference_temp(self) -> float | None:
        chosen = Sensors.aggregate(self.last_temps, self.cfg["sensors"])
        if chosen is not None:
            return chosen
        # The configured sensor vanished (different notebook, module not
        # loaded). Rather than freezing the fan, react to the hottest reading
        # that is available at all.
        return max(self.last_temps.values()) if self.last_temps else None

    def desired_speed(self, fresh: bool = True) -> int:
        """Fan speed the configuration currently asks for."""
        if self.cfg["mode"] != "auto":
            speed = max(1, min(100, int(self.cfg["manual_speed"])))
            self.target = speed
            return speed
        temp = self.reference_temp
        if temp is None:
            # No sensor available: keep whatever the pad is doing.
            return self.target or self.cfg["manual_speed"]
        if fresh:
            speed = self.follower.update(temp)
        else:
            speed = interpolate(self.cfg["curve"], temp)
        self.target = speed
        return speed

    # ---------------------------------------------------------------- writing

    def apply_fan(self, force: bool = False) -> int | None:
        """Push the computed speed to the pad if it actually changed."""
        with self.io:
            return self._apply_fan(force)

    def _apply_fan(self, force: bool = False) -> int | None:
        pad = self.ensure_connected()
        if pad is None:
            return None
        want = self.desired_speed()
        state = self.last_state
        current = state.fan_speed if state else None
        now = time.monotonic()
        moved = current is None or abs(want - current) >= self.cfg["min_speed_step"]
        cooled = now - self.last_write >= self.cfg["write_interval"]
        if not (force or moved) or not (force or cooled):
            return want
        try:
            self.last_state = pad.set_fan(want)
            self.last_write = time.monotonic()
            self.last_error = None
            log.info("Luefter %d%% (Temperatur %.1f degC)", want, self.reference_temp or -1)
        except DeviceNotFound as exc:
            self.last_error = str(exc)
            log.warning("%s", exc)
            self.disconnect()
            self.reconnect_after = time.monotonic() + 5.0
        except OSError as exc:
            self.last_error = str(exc)
            log.warning("Schreiben fehlgeschlagen: %s", exc)
        return want

    def light_signature(self) -> tuple:
        light = self.cfg["light"]
        return tuple(light.get(field) for field in _LIGHT_FIELDS)

    def apply_light(self, force: bool = False) -> dict | None:
        """Keep the LEDs in sync with the configuration."""
        with self.io:
            return self._apply_light(force)

    def _apply_light(self, force: bool = False) -> dict | None:
        signature = self.light_signature()
        if not force and signature == self._light_signature:
            return None
        pad = self.ensure_connected()
        if pad is None:
            return None
        light = self.cfg["light"]
        try:
            self.last_state = pad.set_light(
                color=int(light["color"]),
                effect=int(light["effect"]),
                effect_speed=int(light["speed"]),
                brightness=int(light["brightness"]),
                light_on=bool(light["on"]),
            )
            self._light_signature = signature
            self.last_error = None
            log.info(
                "LEDs: %s / %s / Helligkeit %d",
                light["color"], light["effect"], int(light["brightness"]),
            )
            return dict(light)
        except DeviceNotFound as exc:
            self.last_error = str(exc)
            self.disconnect()
            self.reconnect_after = time.monotonic() + 5.0
        except OSError as exc:
            self.last_error = str(exc)
            log.warning("LED-Kommando fehlgeschlagen: %s", exc)
        return None

    def apply_all(self) -> None:
        self.read_temps()
        self.apply_light()
        self.apply_fan(force=True)

    def set_power(self, on: bool, quiet: bool = False) -> bool:
        """The pad's master switch, keeping colours and fan speed intact.

        `quiet` is for the automatic moments -- a cooling pad that happens to be
        unplugged should not turn a program start into an error.
        """
        with self.io:
            pad = self.ensure_connected()
            if pad is None:
                if not quiet:
                    log.warning("Kuehler nicht erreichbar, Schalten uebersprungen")
                return False
            try:
                self.last_state = pad.set_power(on)
                self.last_write = time.monotonic()
                self.last_error = None
                log.info("Kuehler %sgeschaltet", "ein" if on else "aus")
                return True
            except OSError as exc:
                self.last_error = str(exc)
                log.warning("Schalten fehlgeschlagen: %s", exc)
                return False

    def finish(self, power_off: bool | None = None) -> None:
        """Hand the pad back: switch it off, then let go of it."""
        if power_off is None:
            power_off = bool(self.cfg.get("power_off_on_exit", True))
        if power_off:
            self.set_power(False, quiet=True)

    # ---------------------------------------------------------------- polling

    def poll(self) -> dict:
        """One control cycle; also what the web UI shows as its status."""
        with self.io:
            return self._poll()

    def _poll(self) -> dict:
        pad = self.ensure_connected()
        temps = self.read_temps()
        temp = self.reference_temp
        if pad is not None:
            try:
                self.last_state = pad.read_state()
                self.last_error = None
            except DeviceNotFound as exc:
                self.last_error = str(exc)
                self.disconnect()
                pad = None
                self.reconnect_after = time.monotonic() + 5.0
            except OSError as exc:
                self.last_error = str(exc)
        self.apply_light()
        want = self.desired_speed()
        if pad is not None and want is not None:
            self.apply_fan()
        return {
            "connected": pad is not None,
            "node": pad.node if pad else None,
            "temp": temp,
            "temps": temps,
            "target": want,
            "device": self.last_state.as_dict() if self.last_state else None,
            "mode": self.cfg["mode"],
            "error": self.last_error,
        }

    def run(self, on_cycle=None, should_stop=lambda: True, acquire: bool = True) -> None:
        """Blocking loop used by `llano daemon` and `llano gui`."""
        if acquire:
            self.lock.acquire()
        try:
            if self.cfg.get("power_on_start", True):
                # A pad that was switched off at the last shutdown stays off
                # until somebody opens it again -- might as well be us.
                self.set_power(True, quiet=True)
            self.apply_light(force=True)
            while should_stop():
                try:
                    status = self.poll()
                except Exception as exc:  # pragma: no cover - keep the loop alive
                    log.exception("Zyklus fehlgeschlagen: %s", exc)
                    status = {"error": str(exc)}
                if on_cycle is not None:
                    on_cycle(status)
                deadline = time.monotonic() + max(1.0, float(self.cfg["poll_seconds"]))
                while time.monotonic() < deadline:
                    time.sleep(0.2)
        finally:
            self.finish()
            self.disconnect()
            self.sensors.schliessen()
            if acquire:
                self.lock.release()

    # ------------------------------------------------------------- live edits

    def update_config(self, patch: dict) -> dict:
        """Merge a partial update, re-arm the follower and persist."""
        for key, value in patch.items():
            if key == "light" and isinstance(value, dict):
                self.cfg["light"].update(value)
            else:
                self.cfg[key] = value
        self.cfg["curve"] = config_mod._normalise_curve(self.cfg.get("curve"))
        self.follower.curve = self.cfg["curve"]
        self.follower.hysteresis = float(self.cfg.get("hysteresis", 3.0))
        self.follower.reset()
        config_mod.save(self.cfg)
        return self.cfg

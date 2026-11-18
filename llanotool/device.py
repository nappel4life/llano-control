"""Talk to the llano V12 Ultra - under Linux and under Windows alike.

The pad is an ordinary HID device whose entire control surface is one feature
report, and it never acknowledges a write. Everything that follows from that is
the same on every system and lives here. Where systems differ is the last few
centimetres to the USB plug, and that is a transport module:

===================  ==========================================  ==========================
system               module                                      how it reaches the pad
===================  ==========================================  ==========================
Linux                :mod:`llanotool.device_linux`               ``/dev/hidrawN`` + 2 ioctls
Windows              :mod:`llanotool.device_windows`             setupapi + ``HidD_SetFeature``
===================  ==========================================  ==========================

Both transports look alike (see :mod:`llanotool.device_common`), so the
read-modify-write dance the pad forces on us - every report carries the fan
byte *and* the lighting - is written exactly once.
"""

from __future__ import annotations

import sys

from . import protocol
from .device_common import (
    STATUS_REQUEST,
    STATUS_VERSION,
    DeviceNotFound,
    not_found,
    usb_id,
)

IS_WINDOWS = sys.platform == "win32"

if sys.platform.startswith("linux"):
    from . import device_linux as backend
elif IS_WINDOWS:
    from . import device_windows as backend
else:  # pragma: no cover - only reached on systems we do not support
    class _NoTransport:
        PERMISSION_HINT = ""

        @staticmethod
        def find_paths():
            return []

        @staticmethod
        def open_path(path):
            raise DeviceNotFound(
                f"Die Steuerung des llano V12 Ultra gibt es fuer Linux und "
                f"Windows, nicht fuer {sys.platform}."
            )

    backend = _NoTransport()

__all__ = [
    "DeviceNotFound", "Pad", "backend", "describe_nodes", "find_paths",
    "IS_WINDOWS", "usb_id",
]


def find_paths() -> list[str]:
    """Every connected pad this system can reach."""
    return backend.find_paths()


def describe_nodes() -> list[dict]:
    """Cheap listing used by the CLI."""
    return backend.describe_nodes()


class Pad:
    """A connected cooling pad.

    Writes are not acknowledged by the protocol, so every setter reads the
    feature report back to confirm the pad took the new value.
    """

    def __init__(self, node: str | None = None):
        if node:
            paths = [node]
        else:
            paths = backend.find_paths()
            if not paths:
                raise not_found(backend.PERMISSION_HINT)
        self.node = paths[0]
        self.other_nodes = paths[1:] if not node else []
        self._handle = backend.open_path(self.node)

    def __enter__(self) -> "Pad":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle is not None:
            self._handle = None
            backend.close(handle)

    @property
    def closed(self) -> bool:
        return getattr(self, "_handle", None) is None

    def _raw(self):
        if self._handle is None:
            raise DeviceNotFound("Der Kuehler ist bereits geschlossen.")
        return self._handle

    def request_status(self) -> None:
        """Ask the pad to refresh the report that a read will return.

        Measured on the device: a bare GET_FEATURE hands back whatever the
        last request was. After a version request (0x81) it kept returning
        that request with zeroed fields, which is useless as state - and
        actively harmful, because code that carries "the current state"
        forward would write those zeros to the pad.
        """
        self._write_raw(bytes([0x00]) + STATUS_REQUEST + bytes([protocol.checksum(STATUS_REQUEST)]))

    def read_raw(self) -> bytes:
        return backend.read_feature(self._raw())

    def read_state(self, refresh: bool = True) -> protocol.DeviceState:
        """Read current state; a short retry covers a racy first access."""
        last: Exception | None = None
        for _attempt in range(3):
            try:
                if refresh:
                    self.request_status()
                state = protocol.parse_state(self.read_raw())
            except protocol.ProtocolError as exc:
                last = exc
                continue
            if state.mode == STATUS_VERSION:
                # A pending version request; ask again for real state.
                last = protocol.ProtocolError("Gerat meldet eine Versionsanfrage")
                continue
            return state
        raise last  # type: ignore[misc]

    def _write_raw(self, payload: bytes) -> None:
        assert len(payload) == protocol.BUFFER_LEN
        backend.write_feature(self._raw(), payload)

    def set_fan(self, speed: int, confirm: bool = True,
                known: protocol.DeviceState | None = None) -> protocol.DeviceState | None:
        """Set the fan speed and re-send the lighting unchanged.

        The pad reads bytes 3-6 of every report as its lighting, so a fan
        change has to carry the current colour, effect, tempo and brightness
        or they reset to the pad's defaults. Measured on the device; the fixed
        tail that the vendor application sends does exactly that.
        """
        speed = protocol.clamp_fan(speed)
        state = known or self.read_state()
        self._write_raw(protocol.build_fan_report(
            speed,
            color=state.color,
            effect=state.effect,
            effect_speed=state.effect_speed,
            brightness=state.brightness,
            light_on=state.light_on,
            powered_on=state.powered_on,
        ))
        return self.read_state() if confirm else None

    def set_light(
        self,
        *,
        color: int | None = None,
        effect: int | None = None,
        effect_speed: int | None = None,
        brightness: int | None = None,
        light_on: bool | None = None,
        powered_on: bool | None = None,
        fan_speed: int | None = None,
        confirm: bool = True,
        known: protocol.DeviceState | None = None,
    ) -> protocol.DeviceState | None:
        """Change the lighting, keeping any field the caller left as None.

        The light report also carries the fan speed byte, so the current speed
        is read first when the caller did not supply one. Sending zero there
        would stop the fan.
        """
        current = known or self.read_state()
        payload = protocol.build_light_report(
            fan_speed=current.fan_speed if fan_speed is None else protocol.clamp_fan(fan_speed),
            color=current.color if color is None else color,
            effect=current.effect if effect is None else effect,
            effect_speed=current.effect_speed if effect_speed is None else effect_speed,
            brightness=current.brightness if brightness is None else brightness,
            light_on=current.light_on if light_on is None else light_on,
            powered_on=current.powered_on if powered_on is None else powered_on,
        )
        self._write_raw(payload)
        return self.read_state() if confirm else None

    def set_power(self, on: bool) -> protocol.DeviceState | None:
        """Master switch: off stops the fan and the LEDs."""
        return self.set_light(powered_on=on)

    def version(self, timeout: float = 1.0) -> str | None:
        """Ask for the firmware string; it arrives on interrupt IN, not in a
        feature report, so this is best effort. Afterwards the status request
        is re-issued, because the version request otherwise shadows the
        report that a later read would return."""
        body = bytes([STATUS_VERSION, 0, 0, 0, 0, 0, 0])
        self._write_raw(bytes([0x00]) + body + bytes([protocol.checksum(body)]))
        try:
            data = backend.read_input(self._raw(), timeout)
        except Exception:  # pragma: no cover - best effort by design
            data = None
        text = None
        if data:
            printable = bytes(b for b in data if 32 <= b < 127)
            text = printable.decode("ascii", "ignore") or None
        try:
            self.request_status()
        except DeviceNotFound:
            raise
        except OSError:
            pass
        return text

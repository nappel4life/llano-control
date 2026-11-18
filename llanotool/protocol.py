"""Packet layout for the llano V12 Ultra cooling pad (USB 374a:b101).

The device exposes a single vendor HID interface with three reports and no
report IDs: an 8-byte feature report that carries all control and telemetry,
plus a 64-byte input and a 64-byte output report that carry nothing known.

All control therefore goes through the feature report. Because the device has
no report IDs, the kernel expects a leading 0x00 byte in the hidraw buffers,
so every buffer handled here is 9 bytes long.

This module is pure arithmetic: no I/O, no dependencies, safe to unit test.
"""

from __future__ import annotations

VENDOR_ID = 0x374A
PRODUCT_ID = 0xB101

BODY_LEN = 7
BUFFER_LEN = BODY_LEN + 2  # report id + body + checksum

# First byte of a report. The pad answers a read with 0x80 while software set
# the speed and 0x88 while its own wheel does.
CMD_LIGHT = 0x00
CMD_FAN = 0x01

FAN_MIN = 1
FAN_MAX = 100

# Names as the vendor application labels them.
COLORS = {
    0: "rot",
    1: "hellblau",
    2: "gruen",
    3: "lila",
    4: "orange",
}

EFFECTS = {
    0: "durchgehend",
    1: "atmend",
    2: "regenbogen",
    3: "lauflicht",
    4: "zonen",
}

# Effect speed: the pad counts down, 0 is the fastest step.
EFFECT_SPEEDS = {0: "schnell", 1: "mittel-schnell", 2: "mittel-langsam", 3: "langsam"}

LIGHT_OFF_FLAG = 0x80


class ProtocolError(ValueError):
    """Raised when a report is malformed or fails its checksum."""


def checksum(body: bytes | bytearray) -> int:
    """Return the checksum byte for the seven body bytes of a report."""
    if len(body) != BODY_LEN:
        raise ProtocolError(f"body must be {BODY_LEN} bytes, got {len(body)}")
    return (0xFF - (sum(body) & 0xFF)) & 0xFF


def _frame(body: bytes | bytearray) -> bytes:
    """Prefix the report id and append the checksum over the body."""
    return bytes([0x00]) + bytes(body) + bytes([checksum(body)])


def clamp_fan(value: int) -> int:
    """Bring a requested speed into the range the pad actually honours."""
    value = int(round(value))
    if not FAN_MIN <= value <= FAN_MAX:
        return max(FAN_MIN, min(FAN_MAX, value))
    return value


def build_state_report(
    *,
    mode: int,
    fan_speed: int,
    color: int,
    effect: int = 0,
    effect_speed: int = 0,
    brightness: int = 0xFF,
    light_on: bool = True,
    powered_on: bool = True,
) -> bytes:
    """Build a 9-byte report.

    The pad treats every report as the complete state: bytes 3-6 are always
    the lighting and writing them re-applies them. Measured on the device, a
    report carrying fixed lighting bytes overwrote whatever colour and effect
    the pad was showing. A caller that only wants to change the fan must
    therefore still pass the lighting it wants to keep.
    """
    effect_byte = effect if light_on else (effect | LIGHT_OFF_FLAG)
    body = bytes(
        [
            mode & 0xFF,
            max(0, min(FAN_MAX, int(round(fan_speed)))),
            0x00 if powered_on else 0x01,
            effect_byte & 0xFF,
            color & 0xFF,
            effect_speed & 0xFF,
            brightness & 0xFF,
        ]
    )
    return _frame(body)


def build_fan_report(
    speed: int,
    *,
    color: int,
    effect: int = 0,
    effect_speed: int = 0,
    brightness: int = 0xFF,
    light_on: bool = True,
    powered_on: bool = True,
) -> bytes:
    """Set the fan speed while repeating the lighting that should stay."""
    return build_state_report(
        mode=CMD_FAN, fan_speed=clamp_fan(speed), color=color, effect=effect,
        effect_speed=effect_speed, brightness=brightness, light_on=light_on,
        powered_on=powered_on,
    )


def build_light_report(
    *,
    fan_speed: int,
    color: int,
    effect: int = 0,
    effect_speed: int = 0,
    brightness: int = 0xFF,
    light_on: bool = True,
    powered_on: bool = True,
) -> bytes:
    """Build the 9-byte report that sets the lighting.

    ``fan_speed`` is mandatory on purpose: the light command also carries the
    fan speed byte, and a zero there stops the fan. Callers must pass the
    speed they want to keep in effect.
    """
    return build_state_report(
        mode=CMD_LIGHT, fan_speed=fan_speed, color=color, effect=effect,
        effect_speed=effect_speed, brightness=brightness, light_on=light_on,
        powered_on=powered_on,
    )


class DeviceState:
    """Decoded contents of a feature report read from the pad."""

    __slots__ = ("raw", "mode", "fan_speed", "powered_on", "light_on", "effect",
                 "color", "effect_speed", "brightness")

    def __init__(self, raw: bytes):
        if len(raw) < BUFFER_LEN:
            raise ProtocolError(f"expected {BUFFER_LEN} bytes, got {len(raw)}")
        body = raw[1:1 + BODY_LEN]
        if checksum(body) != raw[BUFFER_LEN - 1]:
            raise ProtocolError(
                "checksum mismatch: "
                f"expected 0x{checksum(body):02x}, got 0x{raw[BUFFER_LEN - 1]:02x}"
            )
        self.raw = bytes(raw)
        self.mode = body[0]
        self.fan_speed = body[1]
        self.powered_on = body[2] == 0x00
        self.light_on = body[3] < LIGHT_OFF_FLAG
        self.effect = body[3] & ~LIGHT_OFF_FLAG
        self.color = body[4]
        self.effect_speed = body[5]
        self.brightness = body[6]

    @property
    def color_name(self) -> str:
        return COLORS.get(self.color, f"unbekannt({self.color})")

    @property
    def effect_name(self) -> str:
        return EFFECTS.get(self.effect, f"unbekannt({self.effect})")

    @property
    def rpm_display(self) -> int:
        """Reproduce the number printed on the pad's own display."""
        level = round((min(self.fan_speed, FAN_MAX) - 1) * 25 / 99)
        return 300 + max(0, level) * 100

    def as_dict(self) -> dict:
        return {
            "fan_speed": self.fan_speed,
            "rpm_display": self.rpm_display,
            "powered_on": self.powered_on,
            "light_on": self.light_on,
            "effect": self.effect,
            "effect_name": self.effect_name,
            "color": self.color,
            "color_name": self.color_name,
            "effect_speed": self.effect_speed,
            "brightness": self.brightness,
            "raw": self.raw.hex(" "),
        }

    def __repr__(self) -> str:
        return (
            f"DeviceState(fan={self.fan_speed}% rpm~{self.rpm_display} "
            f"power={self.powered_on} light={self.light_on} "
            f"effect={self.effect_name} color={self.color_name} "
            f"speed={self.effect_speed} brightness={self.brightness})"
        )


def parse_state(raw: bytes) -> DeviceState:
    return DeviceState(raw)

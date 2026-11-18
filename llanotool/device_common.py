"""Shared ground for the two device transports.

The pad speaks one protocol (see ``protocol.py``) over two very different
buses: on Linux it is a ``/dev/hidrawN`` node driven by two ioctls, on Windows
it is a device interface driven by the ``HidD_`` calls of ``hid.dll``. Both
implement the small contract documented below so that ``device.py`` can hold
the protocol logic exactly once.

A transport module provides:

``find_paths() -> list[str]``
    Every connected pad, most convenient first. Empty list when none.
``open_path(path) -> handle``
    Open one entry of that list. Raise ``DeviceNotFound`` with a message that
    says what to do about it (permissions on Linux, "not plugged in" on
    Windows). The handle is an opaque value: a file descriptor on Linux, a
    ``HANDLE`` on Windows.
``close(handle) -> None``
    Idempotent.
``read_feature(handle) -> bytes``
    The feature report, as ``protocol.BUFFER_LEN`` bytes including the
    leading report-id byte.
``write_feature(handle, payload) -> None``
    Write ``protocol.BUFFER_LEN`` bytes back to the pad.
``read_input(handle, timeout) -> bytes | None``
    One interrupt-IN report, or ``None`` when nothing arrived in time. Only
    the firmware query needs this, so ``None`` is a fine answer.
``describe_nodes() -> list[dict]``
    Listing for the CLI: ``{"node": str, "readable": bool}``.
``PERMISSION_HINT``
    Shown when the pad is visible but cannot be opened.
"""

from __future__ import annotations

import os

from . import protocol


def _id_from_env(name: str, default: int) -> int:
    """Environment override for a usb id, hex or decimal, ignored when broken."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw, 0)
    except ValueError:
        return default


# Tests and the occasional second pad override the ids through the environment.
VENDOR_ID = _id_from_env("LLANO_VENDOR_ID", protocol.VENDOR_ID)
PRODUCT_ID = _id_from_env("LLANO_PRODUCT_ID", protocol.PRODUCT_ID)

PERMISSION_HINT = ""

# Reports the pad understands besides the two state commands: 0x80 asks it to
# publish its current state, 0x81 asks for the firmware string.
STATUS_REQUEST = bytes([0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
STATUS_VERSION = 0x81


class DeviceNotFound(OSError):
    """No accessible pad is plugged in (or permissions are missing)."""


def usb_id(vendor: int | None = None, product: int | None = None) -> str:
    """The id pair as it is written on the box: 374a:b101."""
    vendor = VENDOR_ID if vendor is None else vendor
    product = PRODUCT_ID if product is None else product
    return f"{vendor:04x}:{product:04x}"


def not_found(what: str) -> DeviceNotFound:
    return DeviceNotFound(
        f"llano V12 Ultra nicht gefunden. Ist er eingesteckt (USB {usb_id()})?"
        + (f" {what}" if what else "")
    )

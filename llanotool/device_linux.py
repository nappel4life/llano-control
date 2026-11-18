"""Linux transport: the hidraw node and its two feature ioctls.

Only the standard library is used: the two feature-report ioctls are built by
hand, so there is no hidapi dependency. hidapi is in fact a poor fit here
because opening a device through it triggers a full USB rebind on Linux.

On Windows the same job is done by ``device_windows.py``; both follow the
contract described in ``device_common.py``.
"""

from __future__ import annotations

import errno
import fcntl
import glob
import os
import re
import select

from . import protocol
from .device_common import PRODUCT_ID, VENDOR_ID, DeviceNotFound, not_found

PERMISSION_HINT = (
    "Bitte die udev-Regel aus contrib/ installieren und den Stecker erneut "
    "ziehen und wieder stecken."
)


def _ioc(direction: int, kind: int, number: int, size: int) -> int:
    return (direction << 30) | (kind << 8) | number | (size << 16)


HIDIOCSFEATURE = _ioc(3, ord("H"), 0x06, protocol.BUFFER_LEN)
HIDIOCGFEATURE = _ioc(3, ord("H"), 0x07, protocol.BUFFER_LEN)

_HIDRAW_UEVENTS = "/sys/class/hidraw/hidraw*/device/uevent"


def find_device_nodes(vendor: int | None = None, product: int | None = None) -> list[str]:
    """Return every /dev/hidraw* belonging to the pad, sorted."""
    vendor = VENDOR_ID if vendor is None else vendor
    product = PRODUCT_ID if product is None else product
    want = re.compile(rf"VID_{vendor:04X}.*PID_{product:04X}|{vendor:08X}:{product:08X}")
    found: list[str] = []
    for uevent in sorted(glob.glob(_HIDRAW_UEVENTS)):
        try:
            with open(uevent, encoding="utf-8") as handle:
                text = handle.read().upper()
        except OSError:
            continue
        if want.search(text):
            node = "/dev/" + uevent.split("/")[4]
            if node not in found:
                found.append(node)
    return found


def find_paths() -> list[str]:
    return find_device_nodes()


def _detached(exc: OSError) -> DeviceNotFound | None:
    """Turn the two errnos a pulled plug can show up as into DeviceNotFound."""
    if exc.errno == errno.ENODEV:
        return DeviceNotFound("Der Kuehler ist verschwunden (getrennt?).")
    if exc.errno == errno.EPIPE:
        # Some kernels report a detached device as a broken pipe.
        return DeviceNotFound("Der Kuehler antwortet nicht (getrennt?).")
    return None


def open_path(node: str) -> int:
    try:
        return os.open(node, os.O_RDWR)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise not_found("") from exc
        if exc.errno in (errno.EACCES, errno.EPERM):
            raise DeviceNotFound(
                f"Keine Berechtigung fuer {node}. {PERMISSION_HINT}"
            ) from exc
        raise


def close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def read_feature(fd: int) -> bytes:
    buf = bytearray(protocol.BUFFER_LEN)
    try:
        fcntl.ioctl(fd, HIDIOCGFEATURE, buf, True)
    except OSError as exc:
        raise _detached(exc) or exc from exc
    return bytes(buf)


def write_feature(fd: int, payload: bytes) -> None:
    assert len(payload) == protocol.BUFFER_LEN
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE, bytearray(payload), True)
    except OSError as exc:
        raise _detached(exc) or exc from exc


def read_input(fd: int, timeout: float) -> bytes | None:
    """One interrupt-IN report, or None when the pad did not say anything."""
    try:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        return os.read(fd, 64)
    except OSError:
        return None


def describe_nodes() -> list[dict]:
    """Cheap listing used by the CLI.

    ``grund`` is the sentence to show when a node is there but cannot be
    opened; an empty string means nothing to explain.
    """
    listing = []
    for node in find_device_nodes():
        kann = os.access(node, os.R_OK | os.W_OK)
        listing.append({
            "node": node,
            "readable": kann,
            "grund": "" if kann else PERMISSION_HINT.strip() or "Keine Rechte an der Datei.",
        })
    return listing


def interface_count() -> int:
    """Alle hidraw-Knoten des Rechners, auch die von Tastatur und Maus."""
    return len(glob.glob("/sys/class/hidraw/hidraw*"))

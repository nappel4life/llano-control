"""Windows transport: device interfaces from setupapi, feature reports from hid.dll.

Same contract as ``device_linux.py``, only a different bus. Everything here is
ctypes against libraries that ship with Windows, so the program still has no
third-party dependency:

* ``setupapi.dll`` lists the HID device interfaces and gives their paths,
* ``kernel32.dll`` opens them and reads interrupt reports from them,
* ``hid.dll`` does the feature reports - the only thing this pad listens to -
  and says how long such a report has to be.

Unlike the Linux path this one has not been measured against the device, it
was written against the documented calls. ``llano selftest`` therefore prints
step by step what it could do, so a failing step is at least named.
"""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes

from . import protocol
from .device_common import PRODUCT_ID, VENDOR_ID, DeviceNotFound, usb_id

PERMISSION_HINT = (
    "Die Windows-Oberflaeche des Herstellers (MythCool) haelt das Geraet "
    "manchmal exklusiv - bitte dort beenden und neu versuchen."
)

kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
hid = ctypes.WinDLL("hid.dll", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi.dll", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_MORE_ITEMS = 259
ERROR_ACCESS_DENIED = 5
ERROR_IO_PENDING = 997
ERROR_FILE_NOT_FOUND = 2
ERROR_GEN_FAILURE = 31
ERROR_DEVICE_NOT_AVAILABLE = 433

DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010

# cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W is the size the *header*
# declares, which differs between 32 and 64 bit; getting it wrong is the
# classic ERROR_INVALID_USER_BUFFER at this call.
_DETAIL_CB_SIZE = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
_DETAIL_BUFFER_BYTES = 4096

# An interface path carries the ids as "vid_374a&pid_b101".
_PATH_ID = re.compile(rf"vid_{VENDOR_ID:04x}.*?pid_{PRODUCT_ID:04x}", re.IGNORECASE)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.DWORD),
        ("VendorID", wintypes.WORD),
        ("ProductID", wintypes.WORD),
        ("VersionNumber", wintypes.WORD),
    ]


class HIDP_CAPS(ctypes.Structure):
    """The leading fields we read; the rest of the struct is left alone."""

    _fields_ = [
        ("UsagePage", wintypes.WORD),
        ("Usage", wintypes.WORD),
        ("InputReportByteLength", wintypes.WORD),
        ("OutputReportByteLength", wintypes.WORD),
        ("FeatureReportByteLength", wintypes.WORD),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.POINTER(ctypes.c_ulong)),
        ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("Pointer", ctypes.c_void_p),
        ("hEvent", wintypes.HANDLE),
    ]


class Handle:
    """An open device interface, with what was learned about it while opening."""

    __slots__ = ("raw", "path", "feature_length", "input_length")

    def __init__(self, raw, path, feature_length, input_length):
        self.raw = raw
        self.path = path
        self.feature_length = feature_length
        self.input_length = input_length

    def __bool__(self) -> bool:
        return bool(self.raw) and self.raw != INVALID_HANDLE_VALUE


for _dll, _name, _restype, _argtypes in (
    (kernel32, "CreateFileW", wintypes.HANDLE,
     [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]),
    (kernel32, "CloseHandle", wintypes.BOOL, [wintypes.HANDLE]),
    (kernel32, "ReadFile", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
      ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]),
    (kernel32, "CancelIo", wintypes.BOOL, [wintypes.HANDLE]),
    (kernel32, "GetOverlappedResult", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
      ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]),
    (kernel32, "CreateEventW", wintypes.HANDLE,
     [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]),
    (kernel32, "WaitForSingleObject", wintypes.DWORD,
     [wintypes.HANDLE, wintypes.DWORD]),
    (hid, "HidD_GetHidGuid", None, [ctypes.POINTER(GUID)]),
    (hid, "HidD_GetAttributes", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]),
    (hid, "HidD_GetFeature", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]),
    (hid, "HidD_SetFeature", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]),
    (hid, "HidD_GetProductString", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]),
    (hid, "HidD_GetPreparsedData", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]),
    (hid, "HidD_FreePreparsedData", wintypes.BOOL, [ctypes.c_void_p]),
    (hid, "HidP_GetCaps", wintypes.BOOL,
     [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]),
    (setupapi, "SetupDiGetClassDevsW", wintypes.HANDLE,
     [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]),
    (setupapi, "SetupDiEnumDeviceInterfaces", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
      ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]),
    (setupapi, "SetupDiGetDeviceInterfaceDetailW", wintypes.BOOL,
     [wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
      ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
      ctypes.c_void_p]),
    (setupapi, "SetupDiDestroyDeviceInfoList", wintypes.BOOL,
     [wintypes.HANDLE]),
):
    _func = getattr(_dll, _name)
    _func.restype = _restype
    _func.argtypes = _argtypes
del _dll, _name, _restype, _argtypes, _func


def _last_error() -> int:
    return ctypes.get_last_error()


def _interface_paths() -> list[str]:
    """Every present HID device interface path, in enumeration order."""
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if not info or info == INVALID_HANDLE_VALUE:
        return []
    paths: list[str] = []
    try:
        index = 0
        while True:
            data = SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                info, None, ctypes.byref(guid), index, ctypes.byref(data)
            ):
                break  # ERROR_NO_MORE_ITEMS, or a driver that will not talk
            path = _interface_detail(info, ctypes.byref(data))
            if path:
                paths.append(path)
            index += 1
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)
    return paths


def _interface_detail(info, interface_data) -> str | None:
    needed = wintypes.DWORD(0)
    setupapi.SetupDiGetDeviceInterfaceDetailW(
        info, interface_data, None, 0, ctypes.byref(needed), None
    )
    size = max(needed.value or 0, _DETAIL_BUFFER_BYTES)
    buf = ctypes.create_string_buffer(size)
    ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = _DETAIL_CB_SIZE
    if not setupapi.SetupDiGetDeviceInterfaceDetailW(
        info, interface_data, buf, size, ctypes.byref(needed), None
    ):
        return None
    raw = buf.raw[4:size]
    end = raw.find(b"\x00\x00")
    if end < 0:
        end = len(raw)
    try:
        return raw[:end].decode("utf-16-le") or None
    except UnicodeDecodeError:
        return None


def find_paths() -> list[str]:
    """Interface paths of every connected pad."""
    seen: list[str] = []
    for path in _interface_paths():
        if _PATH_ID.search(path.lower()) and path not in seen:
            seen.append(path)
    return seen


def _raw_open(path: str, overlapped: bool = False):
    handle = kernel32.CreateFileW(
        path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING,
        FILE_FLAG_OVERLAPPED if overlapped else 0, None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        err = _last_error()
        if err == ERROR_FILE_NOT_FOUND:
            # Der Pfad stand eben noch in der Aufzaehlung. Entweder ist der
            # Kuehler gerade weg, oder ein anderes Programm haelt die
            # Schnittstelle so, dass Windows sie nicht mehr hergibt. Beides
            # sieht gleich aus, deshalb steht die Zahl dabei.
            raise DeviceNotFound(
                f"Die Schnittstelle ist nicht mehr da (Windows-Fehler {err}). "
                f"{PERMISSION_HINT}"
            )
        if err == ERROR_ACCESS_DENIED:
            raise DeviceNotFound(f"Kein Zugriff auf den Kuehler. {PERMISSION_HINT}")
        raise DeviceNotFound(
            f"Kuehler kann nicht geoeffnet werden (Fehler {err}). {PERMISSION_HINT}"
        )
    return handle


def _report_lengths(handle) -> tuple[int, int]:
    """(feature, input) report lengths in bytes, report-id byte included."""
    parsed = ctypes.c_void_p()
    if not hid.HidD_GetPreparsedData(handle, ctypes.byref(parsed)):
        return protocol.BUFFER_LEN, 65
    try:
        caps = HIDP_CAPS()
        if not hid.HidP_GetCaps(parsed, ctypes.byref(caps)):
            return protocol.BUFFER_LEN, 65
        return (caps.FeatureReportByteLength or protocol.BUFFER_LEN,
                caps.InputReportByteLength or 65)
    finally:
        hid.HidD_FreePreparsedData(parsed)


def _check_ids(handle) -> None:
    attrs = HIDD_ATTRIBUTES()
    attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
    if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
        return  # nothing learned, but the path already asked for these ids
    if (attrs.VendorID, attrs.ProductID) != (VENDOR_ID, PRODUCT_ID):
        raise DeviceNotFound(
            f"{attrs.VendorID:04x}:{attrs.ProductID:04x} ist kein llano V12 Ultra "
            f"({usb_id()})."
        )


def open_path(path: str) -> Handle:
    raw = _raw_open(path)
    try:
        _check_ids(raw)
        feature_length, input_length = _report_lengths(raw)
    except BaseException:
        kernel32.CloseHandle(raw)
        raise
    return Handle(raw, path, feature_length, input_length)


def close(handle: Handle) -> None:
    if handle and handle.raw:
        kernel32.CloseHandle(handle.raw)


def _failure(operation: str) -> DeviceNotFound:
    err = _last_error()
    if err in (ERROR_GEN_FAILURE, ERROR_DEVICE_NOT_AVAILABLE, ERROR_FILE_NOT_FOUND):
        return DeviceNotFound("Der Kuehler ist verschwunden (getrennt?).")
    if err == ERROR_ACCESS_DENIED:
        return DeviceNotFound(f"{operation} nicht moeglich, kein Zugriff. {PERMISSION_HINT}")
    return DeviceNotFound(f"{operation} fehlgeschlagen (Fehler {err}).")


def read_feature(handle: Handle) -> bytes:
    length = max(handle.feature_length, protocol.BUFFER_LEN)
    buf = ctypes.create_string_buffer(length)  # zeroed: report id 0 first
    if not hid.HidD_GetFeature(handle.raw, buf, length):
        raise _failure("Lesen des Statusberichts")
    return buf.raw[: protocol.BUFFER_LEN]


def write_feature(handle: Handle, payload: bytes) -> None:
    assert len(payload) == protocol.BUFFER_LEN
    length = handle.feature_length
    if length < protocol.BUFFER_LEN:
        raise DeviceNotFound(
            f"Der Kuehler meldet nur {length} Byte Berichtslaenge, noetig sind "
            f"{protocol.BUFFER_LEN}."
        )
    buf = ctypes.create_string_buffer(payload + bytes(length - protocol.BUFFER_LEN),
                                       length)
    if not hid.HidD_SetFeature(handle.raw, buf, length):
        raise _failure("Schreiben auf den Kuehler")


def read_input(handle: Handle, timeout: float) -> bytes | None:
    """One interrupt-IN report.

    The handle we work with is synchronous, and a synchronous ReadFile would
    sit there until the plug comes out, so this reads through a second handle
    of its own with overlapped I/O and a wait. Best effort like on Linux:
    nothing arrived means None, not an error.
    """
    size = max(65, handle.input_length)
    reader = event = None
    try:
        reader = _raw_open(handle.path, overlapped=True)
        event = kernel32.CreateEventW(None, False, False, None)
        if not event:
            return None
        overlapped = OVERLAPPED()
        overlapped.hEvent = event
        buf = ctypes.create_string_buffer(size)
        done = wintypes.DWORD(0)
        started = kernel32.ReadFile(reader, buf, size, ctypes.byref(done),
                                    ctypes.byref(overlapped))
        if not started and _last_error() not in (ERROR_IO_PENDING, 0):
            return None
        if kernel32.WaitForSingleObject(event, int(max(0.05, float(timeout)) * 1000)) \
                != WAIT_OBJECT_0:
            kernel32.CancelIo(reader)
            return None
        if not kernel32.GetOverlappedResult(reader, ctypes.byref(overlapped),
                                            ctypes.byref(done), True):
            return None
        return buf.raw[: done.value]
    except (OSError, ValueError):
        return None
    finally:
        if event:
            kernel32.CloseHandle(event)
        if reader:
            kernel32.CloseHandle(reader)


def product_name(handle: Handle) -> str | None:
    """The product string the pad reports, for nicer listings."""
    buf = ctypes.create_string_buffer(256)
    if not hid.HidD_GetProductString(handle.raw, buf, 256):
        return None
    try:
        return buf.raw.decode("utf-16-le").split("\x00")[0].strip() or None
    except UnicodeDecodeError:
        return None


def describe_nodes() -> list[dict]:
    """Listing for the CLI: a path is "readable" when it can be opened.

    ``grund`` carries the sentence that explains a failed open. On Windows the
    same path can fail three different ways -- another program holds the
    interface, the pad was unplugged a second ago, or the ids turned out to be
    someone else's -- and the three want three different answers. Without the
    reason a selftest can only say "no access" and everyone guesses.
    """
    out = []
    for path in find_paths():
        grund = ""
        try:
            handle = open_path(path)
        except DeviceNotFound as exc:
            handle = None
            grund = str(exc)
        if handle:
            grund = ""
            close(handle)
        out.append({"node": path, "readable": bool(handle), "grund": grund})
    return out


def interface_count() -> int:
    """Every HID interface of this machine, keyboard and mouse included.

    Splits "the pad is not in the list at all" from "it is in the list but
    cannot be opened", which is the question a Windows report has to answer.
    """
    return len(_interface_paths())

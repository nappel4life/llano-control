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
from .device_common import (PRODUCT_ID, VENDOR_ID, DeviceNotFound, usb_id,
                            wide_text)

PERMISSION_HINT = (
    "Die Windows-Oberflaeche des Herstellers (MythCool) haelt das Geraet "
    "manchmal exklusiv - bitte dort beenden und neu versuchen."
)

kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
hid = ctypes.WinDLL("hid.dll", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi.dll", use_last_error=True)
user32 = ctypes.WinDLL("user32.dll", use_last_error=True)

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

# Raw input (user32) is the second, independent way to the very same interface
# paths: it never touches setupapi but asks the input stack, so the two walks
# can be compared against each other.
RIM_TYPEHID = 0x00000002
RID_ID_DEVICE = 0x00000000
UINT_FAILURE = 0xFFFFFFFF

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
    """Die ganze Struktur, nicht bloess ihre Anfangsfelder.

    ``HidP_GetCaps`` schreibt die *vollstaendige* Struktur - 64 Byte, in
    neueren Windows-Fassungen 66 - und fragt nicht, wie gross das Gegenueber
    ist. Eine Fassung, die nur die fuenf gelesenen Felder fuehrt, liess den
    Aufruf deshalb weit hinter das Ende unseres Objekts schreiben. So ein
    Fehler zeigt sich nicht am Ort, an dem er entsteht: Er zerstoert den
    Nachbarn im Speicher, und der Interpreter merkt es erst, wenn er spaeter
    von sich aus aufraeumt. Genau das war der Absturz beim Fensterbauen.
    """

    _fields_ = [
        ("UsagePage", wintypes.WORD),
        ("Usage", wintypes.WORD),
        ("InputReportByteLength", wintypes.WORD),
        ("OutputReportByteLength", wintypes.WORD),
        ("FeatureReportByteLength", wintypes.WORD),
        # Der Rest sind Kapazitaetszahlen, die wir nicht lesen. Der Platz muss
        # trotzdem da sein, und zwar mehr, als jede Windows-Fassung schreibt.
        ("Reserve", wintypes.WORD * 48),
    ]


class OVERLAPPED(ctypes.Structure):
    """Der Begleiter einer Anzeige, die noch läuft.

    In der echten Struktur liegen die Felder direkt beieinander: nach den
    beiden Zählern kommt *ein* gemeinsamer Platz für Zeiger und Versatz, danach
    erst die Ereigniskennung. Wer an die Stelle des gemeinsamen Platzes einen
    eigenen Zeiger setzt, den Windows nicht kennt, schiebt die Kennung eine
    Stufe höher — und wartet dann auf ein Ereignis, das nie gesetzt wird, weil
    Windows an der richtigen Stelle eine leere Kennung vorfand.
    """

    _fields_ = [
        ("Internal", ctypes.POINTER(ctypes.c_ulong)),
        ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class RAWINPUTDEVICELIST(ctypes.Structure):
    """One entry of the raw input table: a handle and what kind it is."""

    _fields_ = [
        ("hDevice", wintypes.HANDLE),
        ("dwType", wintypes.DWORD),
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
    (user32, "GetRawInputDeviceList", wintypes.UINT,
     [ctypes.c_void_p, ctypes.POINTER(wintypes.UINT), wintypes.UINT]),
    (user32, "GetRawInputDeviceInfoW", wintypes.UINT,
     [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
      ctypes.POINTER(wintypes.UINT)]),
):
    _func = getattr(_dll, _name)
    _func.restype = _restype
    _func.argtypes = _argtypes
del _dll, _name, _restype, _argtypes, _func


def _last_error() -> int:
    return ctypes.get_last_error()


def _enumerate_interfaces() -> tuple[list[str], dict]:
    """Every present HID device interface path, plus what the search went through.

    The report is the point of this function. "The pad is not here" and "the
    search itself was refused" look exactly alike from the outside -- both
    leave an empty list -- and they want completely different answers.
    """
    report = {"klasse": "ok", "gesichtet": 0, "unlesbar": 0, "anfangs_code": 0,
              "detail": {}}
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if not info or info == INVALID_HANDLE_VALUE:
        report["klasse"] = f"abgelehnt (Windows-Fehler {_last_error()})"
        return [], report
    paths: list[str] = []
    try:
        index = 0
        while True:
            data = SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                info, None, ctypes.byref(guid), index, ctypes.byref(data)
            ):
                if index == 0:
                    # Nothing at all, not even a keyboard: that is a driver
                    # question, not a missing pad, and the code says which.
                    report["anfangs_code"] = _last_error()
                break  # ERROR_NO_MORE_ITEMS, or a driver that will not talk
            report["gesichtet"] += 1
            detail = {}
            path = _interface_detail(info, ctypes.byref(data), detail)
            if path:
                paths.append(path)
            elif not report["detail"]:
                report["unlesbar"] += 1
                report["detail"] = detail
            else:
                report["unlesbar"] += 1
            index += 1
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)
    return paths, report


def _interface_paths() -> list[str]:
    """Every present HID device interface path, in enumeration order."""
    return _enumerate_interfaces()[0]


def _interface_detail(info, interface_data, fehler=None) -> str | None:
    """The path to one interface.

    ``fehler`` is an optional dict that learns why a path could not be read.
    Asked for by the selftest only: on a real machine the numbers in it are the
    difference between "Windows had nothing to say" and "Windows said it and we
    did not understand it", which is a difference nobody should have to guess
    at from a photograph.
    """
    needed = wintypes.DWORD(0)
    setupapi.SetupDiGetDeviceInterfaceDetailW(
        info, interface_data, None, 0, ctypes.byref(needed), None
    )
    erwartet = needed.value or 0
    size = max(erwartet, _DETAIL_BUFFER_BYTES)
    buf = ctypes.create_string_buffer(size)
    ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = _DETAIL_CB_SIZE
    bekommen = setupapi.SetupDiGetDeviceInterfaceDetailW(
        info, interface_data, buf, size, ctypes.byref(needed), None
    )
    pfad = None
    if bekommen:
        # The text ends in a wide NUL, and only a wide one. Looking for two
        # zero bytes instead lands one byte early on every plain ASCII path: a
        # character's own zero high byte sits right next to the terminator's
        # low byte, so the slice came out odd-sized and undecodable -- which
        # looked exactly like "this machine has no HID devices at all".
        # Deciding on whole characters cannot misalign.
        pfad = wide_text(buf.raw) or None
    if pfad is None and fehler is not None:
        fehler.update({
            "aufgerufen": "ok" if bekommen else f"abgelehnt (Fehler {_last_error()})",
            "erwartet": erwartet,
            "puffer": size,
            "anfang": buf.raw[:24].hex(" "),
        })
    return pfad


def _raw_device_name(handle) -> str | None:
    """The ``\\\\?\\hid#...`` path behind one raw input handle."""
    needed = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(handle, RID_ID_DEVICE, None, ctypes.byref(needed))
    if not needed.value:
        return None
    buf = ctypes.create_string_buffer(needed.value)
    got = user32.GetRawInputDeviceInfoW(handle, RID_ID_DEVICE,
                                        ctypes.cast(buf, ctypes.c_void_p),
                                        ctypes.byref(needed))
    if got in (0, UINT_FAILURE):
        return None
    taken = min(got, needed.value) or got
    return wide_text(buf.raw[:taken], 0) or None


def raw_input_scan() -> tuple[int, int, list[str]]:
    """(all raw input devices, HID ones, paths of ours) from the input stack.

    Deliberately a different road than ``_enumerate_interfaces``: when one
    road says "nothing here" and the other says otherwise, that difference is
    the whole diagnosis. Nothing here can raise -- a machine without a raw
    input stack should still answer with numbers.
    """
    count = wintypes.UINT(0)
    size = ctypes.sizeof(RAWINPUTDEVICELIST)
    user32.GetRawInputDeviceList(None, ctypes.byref(count), size)
    total = count.value
    if not total:
        return 0, 0, []
    table = (RAWINPUTDEVICELIST * total)()
    if user32.GetRawInputDeviceList(ctypes.cast(table, ctypes.c_void_p),
                                    ctypes.byref(count), size) == UINT_FAILURE:
        return total, 0, []
    hid_devices = 0
    ours: list[str] = []
    for entry in table[: count.value]:
        if entry.dwType != RIM_TYPEHID:
            continue
        hid_devices += 1
        path = _raw_device_name(entry.hDevice)
        if path and _PATH_ID.search(path.lower()) and path not in ours:
            ours.append(path)
    return total, hid_devices, ours


def find_paths() -> list[str]:
    """Interface paths of every connected pad."""
    seen: list[str] = []
    for path in _interface_paths():
        if _PATH_ID.search(path.lower()) and path not in seen:
            seen.append(path)
    if seen:
        return seen
    # The setupapi walk is the documented one, but not the only one: the input
    # stack hands out these very paths too. An empty walk here has meant two
    # different things in the field -- no pad, and a search that could not
    # start -- and a second look costs one call and settles both.
    #
    # This runs again every few seconds from the control loop, so a second
    # road that cannot be walked must not be allowed to raise: an empty list
    # keeps saying "kein Geraet", which is what it means.
    try:
        return raw_input_scan()[2]
    except (OSError, ValueError):
        return []


def scan_report() -> list[str]:
    """Lines for ``llano selftest``: why a search came back empty.

    One line per question, so the answer survives being photographed.
    """
    _, report = _enumerate_interfaces()
    total, hid_share, ours = raw_input_scan()
    lines = [
        f"Klassensuche   : {report['klasse']}; {report['gesichtet']} "
        f"Schnittstellen gelesen, {report['unlesbar']} ohne verwertbaren Pfad"
    ]
    detail = report.get("detail") or {}
    if detail:
        lines.append(
            f"                 : Pfadlesung {detail['aufgerufen']}, Windows "
            f"nannte {detail['erwartet']} Byte, gelesen in {detail['puffer']}")
        lines.append(f"                 : Anfang des Puffers {detail['anfang']}")
    if report["anfangs_code"]:
        lines.append(f"                 : die Aufzaehlung brach schon beim "
                     f"ersten Geraet ab (Fehler {report['anfangs_code']})")
    lines.append(
        f"Roheingabe     : {total} Geraete, davon {hid_share} Eingabegeraete, "
        f"{len(ours)} mit der Kennung {usb_id()}"
    )
    if not total:
        lines.append("                 : die Roheingabe kennt kein einziges "
                     "Geraet - hier laeuft die Eingabe nicht ueber Hid-Treiber")
    return lines


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
    return wide_text(buf.raw, 0).strip() or None


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

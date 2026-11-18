"""Read notebook temperatures without extra dependencies.

Under Linux:

* ``/sys/class/hwmon``  - CPU (coretemp / k10temp), NVMe, chipset, WiFi, GPU on
  amdgpu and nouveau. This is free and fast.
* ``nvidia-smi``        - the NVIDIA GPU temperature, because Optimus laptops
  usually do not expose it through hwmon. The call costs a few tens of
  milliseconds, so results are cached.

Under Windows the picture is thinner: there is no hwmon, and reading a CPU
temperature needs a driver. What the operating system offers on its own is

* the ACPI thermal zones (``MSAcpi_ThermalZoneTemperature`` through WMI),
* ``nvidia-smi`` again for the NVIDIA GPU,
* the shared memory of HWiNFO, if HWiNFO happens to be running - that is the
  only driverless way to a real CPU temperature on Windows, see
  :mod:`llanotool.sensors_hwiinfo`.

A thermal zone is not a core: it is a point on the board chosen by the
firmware, it reacts more slowly, and on some laptops it can only be read by an
elevated process. Which of those happened is in :attr:`Sensors.note`, so the
CLI can say it instead of showing an empty table.
"""

from __future__ import annotations

import os
import re
import subprocess
import time

from .sensors_hwiinfo import HWiNFO
from .sensors_lhm import LHM

IS_WINDOWS = os.name == "nt"

HWMON_GLOB = "/sys/class/hwmon/hwmon*"

# Chips that are not a temperature worth reacting to.
_SKIP_CHIPS = {"ucsi_source_psy", "iwlwifi_1", "r8169", "gpp", "ACAD"}

_NVIDIA_CMD = [
    "nvidia-smi",
    "--query-gpu=temperature.gpu",
    "--format=csv,noheader,nounits",
]

# Windows would open a console window for every one of these calls, and the
# interface polls them. 0x08000000 is CREATE_NO_WINDOW.
_NO_WINDOW = 0x08000000
_CREATE_FLAGS = {"creationflags": _NO_WINDOW} if IS_WINDOWS else {}

# The one temperature source Windows offers without a driver: the ACPI thermal
# zones. Values arrive in tenths of a Kelvin.
_THERMAL_ZONE_PS = (
    "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature"
    " | ForEach-Object { '{0};{1}' -f $_.InstanceName, $_.CurrentTemperature }"
)
_THERMAL_ZONE_CMD = [
    "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _THERMAL_ZONE_PS,
]


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False,
        **_CREATE_FLAGS,
    )


def _read_int(path: str) -> int | None:
    try:
        with open(path, encoding="ascii") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def _chip_is_interesting(name: str) -> bool:
    return not any(name.startswith(skip) for skip in _SKIP_CHIPS)


def read_hwmon() -> dict[str, float]:
    """Map "chip:label" to degrees Celsius for every hwmon sensor."""
    import glob

    out: dict[str, float] = {}
    for chip in sorted(glob.glob(HWMON_GLOB)):
        name = _read_str(os.path.join(chip, "name")) or "chip"
        if not _chip_is_interesting(name):
            continue
        for input_path in sorted(glob.glob(os.path.join(chip, "temp*_input"))):
            base = input_path[: -len("_input")]
            raw = _read_int(input_path)
            if raw is None:
                continue
            label = _read_str(base + "_label")
            if not label:
                label = os.path.basename(base)
                label = label.replace("temp", "")
                label = {"": "total", "1": "1", "2": "2"}.get(label, label)
            value = raw / 1000.0
            # A reading of 0 or a negative value means "not present".
            if value <= 0:
                continue
            key = f"{name}:{label}"
            if key not in out or value > out[key]:
                out[key] = value
    return out


_CORE_LABEL = re.compile(r"^Core \d+$", re.IGNORECASE)
_PACKAGE_LABELS = ("package", "tsen", "tctl", "composite")


def collapse_per_core(temps: dict[str, float]) -> dict[str, float]:
    """Drop the per-core readings of a CPU that also reports a package value.

    A modern CPU exposes one entry per core plus a package total; for a fan
    curve the package number is the only one that matters, and 40 identical
    rows make the picker unusable.
    """
    chips_with_package = {
        key.split(":", 1)[0]
        for key in temps
        if any(hint in key.lower() for hint in _PACKAGE_LABELS)
    }
    return {
        key: value
        for key, value in temps.items()
        if not (
            key.split(":", 1)[0] in chips_with_package
            and _CORE_LABEL.match(key.split(":", 1)[1] if ":" in key else "")
        )
    }


def _read_str(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


class NvidiaGpu:
    """Cached nvidia-smi temperature reader."""

    def __init__(self, ttl: float = 1.0):
        self.ttl = ttl
        self._value: float | None = None
        self._at = 0.0
        self._missing = False

    @property
    def available(self) -> bool:
        self.read()
        return not self._missing

    def read(self) -> float | None:
        now = time.monotonic()
        if self._missing and now - self._at < 30:
            return None
        if self._value is not None and now - self._at < self.ttl:
            return self._value
        self._at = now
        try:
            proc = _run(_NVIDIA_CMD, 2.0)
        except (OSError, subprocess.TimeoutExpired):
            self._missing = True
            self._value = None
            return None
        if proc.returncode != 0:
            self._missing = True
            self._value = None
            return None
        try:
            self._value = float(proc.stdout.strip().splitlines()[0])
            self._missing = False
        except (ValueError, IndexError):
            self._value = None
        return self._value


class WindowsThermalZones:
    """Cached reader for the ACPI thermal zones of a Windows notebook.

    Reading a CPU temperature on Windows means a kernel driver; this is what
    the operating system publishes by itself. Three outcomes are possible and
    the last two are common, which is why :attr:`reason` exists:

    * the zones are published and readable,
    * the machine has no ``MSAcpi_ThermalZoneTemperature`` class at all,
    * it has the class but only an elevated process may read it.

    Calling PowerShell costs a few hundred milliseconds, so results are cached
    like the NVIDIA reading.
    """

    CHIP = "thermalzone"

    def __init__(self, ttl: float = 2.0):
        self.ttl = ttl
        self._temps: dict[str, float] = {}
        self._at = 0.0
        self.reason: str | None = None

    def read(self) -> dict[str, float]:
        now = time.monotonic()
        if (self._temps or self.reason) and now - self._at < self.ttl:
            return dict(self._temps)
        self._at = now
        try:
            proc = _run(_THERMAL_ZONE_CMD, 20.0)
        except OSError as exc:
            self._temps, self.reason = {}, f"PowerShell ist nicht erreichbar: {exc.strerror or exc}"
            return {}
        except subprocess.TimeoutExpired:
            # Keep the last numbers rather than leaving the curve without input.
            self.reason = "Die Windows-Wartungsschnittstelle hat nicht geantwortet."
            return dict(self._temps)
        if proc.returncode != 0:
            self._temps = {}
            self.reason = _zone_failure_text(proc.stderr)
            return {}
        temps: dict[str, float] = {}
        for line in proc.stdout.splitlines():
            name, _, raw = line.partition(";")
            try:
                celsius = (float(raw.strip()) - 2731.5) / 10.0
            except ValueError:
                continue
            if not 0.0 < celsius < 125.0:
                continue          # a zone that is not really there
            temps[f"{self.CHIP}:{name.strip() or 'zone'}"] = celsius
        self._temps = temps
        self.reason = None if temps else (
            "Windows meldet keine brauchbare Wärmezone. Bei manchen Notebooks "
            "liest man sie nur mit erhöhten Rechten: das Programm als "
            "Administrator starten."
        )
        return dict(temps)


def _zone_failure_text(stderr: str) -> str:
    """Turn a WMI complaint into one line that says what to do about it."""
    text = " ".join((stderr or "").split())
    lowered = text.lower()
    if "access" in lowered or "verweigert" in lowered or "denied" in lowered:
        return ("Die Windows-Wärmezone ist geschützt. Bitte das Programm ein "
                "Mal als Administrator starten.")
    if "invalid class" in lowered or "not found" in lowered or "unknown" in lowered:
        return ("Dieser Rechner meldet keine Windows-Wärmezone. Die Kurve kann "
                "sich dann nur an der GPU orientieren.")
    if not text:
        return "Die Windows-Wartungsschnittstelle hat nichts zurückgegeben."
    return f"Die Windows-Wartungsschnittstelle meldete: {text[:180]}"


# Beide Messhilfen sind kostenlos und beide tun dem Kuehler keinen Weh: Es geht
# nur darum, an die Prozesstemperaturen zu kommen, die Windows ohne Treiber nicht
# herausgibt. Deshalb einer Satz fuer beide Faelle statt zweier Hinweise.
# Die Messhilfe antwortet, aber der Prozessor fehlt in ihrer Liste. Der Fall
# ist haeufiger als jede Erklaerung: ohne Administratorrechte darf keine
# Benutzermessung die Fuehler im Prozessor lesen.
TEXT_OHNE_PROZESSOR = (
    "Die Messhilfe antwortet, nennt die Prozessortemperatur aber nicht. Meist "
    "laeuft sie ohne Administratorrechte - die Fuehler im Prozessor haelt "
    "Windows zurueck. Messhilfe beenden und als Administrator neu starten.")

TEXT_HILFE_FEHLT = (
    "Ohne Messhilfe fehlt die Prozessortemperatur: HWiNFO laufen lassen "
    "(Einstellungen 'Shared Memory Support') oder LibreHardwareMonitor "
    "(Optionen 'Remote Web Server'). Ohne eine von beiden gibt Windows die "
    "Prozesstemperaturen nicht her. Laeuft die Messhilfe als Administrator, muss "
    "auch dieses Programm als Administrator laufen.")


class Sensors:
    """Collects every temperature the fan curve may use."""

    def __init__(self):
        self._nvidia = NvidiaGpu()
        self._zones = WindowsThermalZones() if IS_WINDOWS else None
        self._hwiinfo = HWiNFO() if IS_WINDOWS else None
        self._lhm = LHM() if IS_WINDOWS else None

    def read(self, collapse: bool = True) -> dict[str, float]:
        if IS_WINDOWS:
            temps = dict(self._zones.read())      # type: ignore[union-attr]
            temps.update(self._hwiinfo.lesen())   # type: ignore[union-attr]
            temps.update(self._lhm.lesen())       # type: ignore[union-attr]
        else:
            temps = read_hwmon()
        gpu = self._nvidia.read()
        if gpu is not None:
            temps["nvidia:GPU"] = gpu
        return collapse_per_core(temps) if collapse else temps

    def note(self) -> str | None:
        """What a missing temperature list means, if anything.

        Unter Windows sind dafuer drei Wege im Kopf: die Waermezonen des
        Betriebssystems, der Speicherblock von HWiNFO und die Anfrage an
        LibreHardwareMonitor. Was fehlt, wird gesagt - jeder Grund hat seine
        eigene Antwort, und zwei Hinweise auf einmal waeren laestig.
        """
        meldungen = []
        if self._zones is not None and not self._zones.read():
            meldungen.append(self._zones.reason)

        hilfen = [hilfe for hilfe in (self._hwiinfo, self._lhm) if hilfe is not None]
        stillstand = [hilfe.stillstand for hilfe in hilfen if hilfe.stillstand]
        if stillstand:
            # Eine Messhilfe laeuft, traegt aber nichts mehr bei. Das ist die
            # Nachricht, die zaehlt - egal, was ausserdem fehlt.
            meldungen += stillstand
        elif hilfen and not self._hat_cpu_temperatur():
            stille = [hilfe for hilfe in hilfen if not hilfe.lesen()]
            if len(stille) == len(hilfen):
                meldungen.append(TEXT_HILFE_FEHLT)
            elif stille:
                grund = stille[0].hinweis()     # die andere Seite liefert ja
                if grund:
                    meldungen.append(grund)
            else:
                # Beide Helfer antworten, keiner nennt den Prozessor. Ohne
                # diese Zeile haette die Oberflaeche geschwiegen, und
                # "schweigen" war noch immer die schlechteste Auskunft.
                meldungen.append(TEXT_OHNE_PROZESSOR)
        return "  ".join(m for m in meldungen if m) or None

    def _hat_cpu_temperatur(self) -> bool:
        """Meldet eine der Quellen schon eine Temperatur der CPU selbst?"""
        andeutungen = ("cpu", "coretemp", "k10temp", "package", "core ", "tsen")
        return any(hinweis in schluessel.lower()
                   for schluessel in self.read(collapse=False)
                   for hinweis in andeutungen)

    def list(self, collapse: bool = True) -> list[dict]:
        """Stable, human friendly list for pickers in the UI."""
        temps = self.read(collapse)
        out = []
        for key in sorted(temps):
            out.append({"id": key, "name": _pretty(key), "temp": temps[key]})
        return out

    @staticmethod
    def aggregate(temps: dict[str, float], ids: list[str]) -> float | None:
        """The value the curve works from: the hottest selected sensor."""
        values = [temps[s] for s in ids if s in temps]
        return max(values) if values else None


def _pretty(key: str) -> str:
    chip, _, label = key.partition(":")
    chip_names = {
        "coretemp": "CPU",
        "k10temp": "CPU",
        "acpitz": "Mainboard",
        "nvme": "SSD",
        "nvidia": "GPU (NVIDIA)",
        "spd5118": "RAM",
        "iwlwifi_1": "WLAN",
        "amdgpu": "GPU (AMD)",
        "nouveau": "GPU (NVIDIA)",
        "thermalzone": "Wärmezone (Windows)",
        "hwiinfo": "HWiNFO",
        "lhm": "LibreHardwareMonitor",
    }
    base = chip_names.get(chip, chip)
    if not label or label == "total":
        return base
    if label in ("1", "2") and chip == "nvme":
        return f"{base} {label}"
    return f"{base} · {label}"

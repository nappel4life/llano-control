"""CPU-Temperaturen unter Windows - aus dem Speicher, den HWiNFO offen hält.

Windows gibt eine Prozessortemperatur ohne Kernel-Treiber nicht heraus. Die
ACPI-Wärmezonen (``sensors.WindowsThermalZones``) reicht fast kein Notebook an
ein normales Programm weiter, und ein eigener Treiber wäre für ein kleines
Kühlprogramm nicht zu vertreten.

HWiNFO ist als kostenloses Programm verbreitet und hält alle seine Messwerte in
einem benannten Speicherblock, den jedes andere Programm mitlesen darf, solange
HWiNFO läuft („Shared Memory Support“ in den Einstellungen). Das ist hier der
Weg zur CPU-Temperatur: kein Treiber, keine Administration, keine
Zusatzprogramme ausser HWiNFO selbst.

Der Block (Schnittstelle „SM2“) fängt mit der Signatur ``SiWH`` an; danach
stehen Abschnittsangaben, Gruppen und Messwerte. Die Schrittweiten der
Einträge stehen im Block selbst, denn die Größe der Strukturen hängt davon ab,
wie HWiNFO gerade gepuffert hat. Alles hier arbeitet deshalb mit diesen
Schrittweiten und nie mit eingebauten Annahmen.

Zwei Eigenheiten sind bekannt und werden unten behandelt:

* Läuft HWiNFO als Administrator, kann ein normales Programm den Block nicht
  öffnen. Der Hinweis sagt das.
* Die kostenlose Fassung hört nach etwa zwölf Stunden auf, neue Werte
  einzutragen. Der Block bleibt dann lesbar, aber alt - deshalb merkt sich der
  Leser die letzte Messzeit und meldet einen Stillstand.
"""

from __future__ import annotations

import mmap
import os
import re
import struct
import time
from dataclasses import dataclass

IS_WINDOWS = os.name == "nt"

SIGNATUR = b"SiWH"
NAMEN = ("Global\\HWiNFO_SENS_SM2", "Local\\HWiNFO_SENS_SM2", "HWiNFO_SENS_SM2")

# Die Messart steht am Anfang jedes Messwerts. Fuer die Kuehlerkurve kommen nur
# Temperaturen in Frage; das sind die Werte mit der Zahl 1.
ART_TEMPERATUR = 1
ARTEN = {0: "keine", 1: "Temperatur", 2: "Spannung", 3: "Luefter", 4: "Strom",
         5: "Leistung", 6: "Takt", 7: "Auslastung", 8: "sonstiges"}

# Ab hier ist ein Messwert Unsinn: 0 heisst "nicht vorhanden", und ueber 150
# Grad geht kein Chip, den dieses Programm kuehlen soll.
UNTERE_SCHWELLE = 0.0
OBERE_SCHWELLE = 150.0

# Nach so vielen ungebrauchten Abfragen ohne neue Messzeit gilt der Block als
# stehengeblieben. Bei drei Sekunden nachlesen sind das eine halbe Minute.
STEHEN_NACH = 10

TEXT_START = ("Ohne HWiNFO fehlt die Prozessortemperatur: HWiNFO starten und in "
              "den Einstellungen 'Shared Memory Support' anlassen. Laeuft "
              "HWiNFO als Administrator, muss auch dieses Programm als "
              "Administrator laufen.")
TEXT_STILLSTAND = ("HWiNFO meldet seit einer halben Minute keinen neuen Stand - "
                   "die kostenlose Fassung hoert nach etwa zwolf Stunden auf, "
                   "neue Werte einzutragen. Ein Neustart von HWiNFO hilft.")

_KOPF_AB = 12          # fruehe Bausaetze: Zeitstempel ohne Ausrichtung
_KOPF_AB_AUSGERICHTET = 16


@dataclass
class Messwert:
    """Ein Temperaturwert, so wie HWiNFO ihn anbietet."""

    gruppe: str
    marke: str
    wert: float

    @property
    def kennung(self) -> str:
        """Der Schluessel, unter dem die Kurve diesen Wert findet."""
        return f"hwiinfo:{self.marke}"


def text(puffer: bytes, ab: int, laenge: int) -> str:
    """Ein ANSI-Textfeld aus dem Block, ohne das abschliessende Nullzeichen."""
    roh = puffer[ab:ab + laenge]
    ende = roh.find(b"\x00")
    if ende != -1:
        roh = roh[:ende]
    # HWiNFO schreibt im aktuellen Codeblatt; cp1252 ist dessen sichere
    # Obermenge und geht wenigstens gut, wenn Umlaute dabei sind.
    return roh.decode("cp1252", "replace").strip()


def kopf(puffer: bytes) -> dict | None:
    """Die Abschnittsangaben aus dem Vorspann, oder nichts bei fremdem Inhalt.

    Der Zeitstempel ist ein ``__time64_t`` und liegt je nach Bausatz entweder
    unmittelbar hinter den beiden Versionszahlen oder an einer Achtgrenze.
    Statt zu raten, werden beide Lagen probiert und die genommen, deren
    Abschnittsgroessen sich waschen koennen.
    """
    if len(puffer) < 8 or puffer[:4] != SIGNATUR:
        return None
    version, ausgabe = struct.unpack_from("<II", puffer, 4)
    for zeit_ab in (_KOPF_AB_AUSGERICHTET, _KOPF_AB):
        try:
            messzeit = struct.unpack_from("<q", puffer, zeit_ab)[0]
            ab = zeit_ab + 8
            (ab_gruppen, groesse_gruppe, anzahl_gruppen,
             ab_werte, groesse_wert, anzahl_werte) = struct.unpack_from("<IIIIII", puffer, ab)
        except struct.error:
            return None
        tragbar = (ab_gruppen >= ab + 24 and ab_werte >= ab + 24
                   and 8 <= groesse_gruppe <= 4096
                   and 32 <= groesse_wert <= 8192
                   and 0 <= anzahl_gruppen <= 50_000
                   and 0 <= anzahl_werte <= 500_000)
        if tragbar:
            return {"version": version, "ausgabe": ausgabe, "messzeit": messzeit,
                    "ab_gruppen": ab_gruppen, "groesse_gruppe": groesse_gruppe,
                    "anzahl_gruppen": anzahl_gruppen, "ab_werte": ab_werte,
                    "groesse_wert": groesse_wert, "anzahl_werte": anzahl_werte}
    return None


def gruppen(puffer: bytes, angaben: dict) -> list[str]:
    """Die Namen der Messgruppen, der Reihe nach - Gruppennummer ist Index."""
    out = []
    for laufend in range(angaben["anzahl_gruppen"]):
        boden = angaben["ab_gruppen"] + laufend * angaben["groesse_gruppe"]
        # DWORD, DWORD, danach zwei Textfelder mit je 128 Bytes. Das zweite ist
        # der Name, den sich jemand in HWiNFO selbst ausdenken durfte.
        eigener = text(puffer, boden + 8 + 128, 128)
        out.append(eigener or text(puffer, boden + 8, 128))
    return out


def messwerte(puffer: bytes, kerne: bool | None = None) -> list[Messwert]:
    """Alle brauchbaren Temperaturen aus einem Speicherblock.

    Die vier Zahlen (Wert, kleinste, groesste, mittlere) belegten die letzten
    32 Bytes eines Eintrags, ganz gleich, wie der Rest gepuffert ist - deshalb
    wird von hinten gerechnet.

    ``kerne`` steht fuer die einzelnen Prozessorkerne. Standard ist „weg,
    sobald es auch einen Gesamtwert gibt“, genau wie bei den Kernwerten unter
    Linux: vierzig Zeilen machen die Auswahl unbrauchbar, und fuer die Kurve
    zaehlt der Gesamtwert.
    """
    angaben = kopf(puffer)
    if angaben is None:
        return []
    namen = gruppen(puffer, angaben)
    out: list[Messwert] = []
    for laufend in range(angaben["anzahl_werte"]):
        boden = angaben["ab_werte"] + laufend * angaben["groesse_wert"]
        try:
            art, gruppen_nr, _kennung = struct.unpack_from("<III", puffer, boden)
            wert = struct.unpack_from("<d", puffer,
                                      boden + angaben["groesse_wert"] - 32)[0]
        except struct.error:
            break
        if art != ART_TEMPERATUR or not UNTERE_SCHWELLE < wert < OBERE_SCHWELLE:
            continue
        gruppe = namen[gruppen_nr] if gruppen_nr < len(namen) else ""
        marke = text(puffer, boden + 140, 128) or text(puffer, boden + 12, 128)
        if not marke:
            continue
        out.append(Messwert(gruppe=gruppe, marke=_marke(gruppe, marke), wert=wert))

    if kerne is None:
        kerne = not any(_GESAMT_WERT.search(wert.marke) for wert in out)
    if not kerne:
        out = [wert for wert in out if not _KERN_WERT.search(wert.marke)] or out
    return out


# „CPU Core #4“ ist ein Einzelkern, „CPU (Package)“ der Wert, den eine Kurve
# braucht.
_KERN_WERT = re.compile(r"core\s*#?\d+", re.IGNORECASE)
_GESAMT_WERT = re.compile(r"\b(package|average|avg|total|die)\b", re.IGNORECASE)


def _marke(gruppe: str, marke: str) -> str:
    """Ein Name, der fuer sich steht - „CPU“ und „Package“ zusammen ergibt mehr.

    HWiNFO benennt Gruppen und Werte je nach Mainboard unterschiedlich gut.
    Steht die Gruppe schon im Wert, wird sie nicht zweimal hintereinander
    gezeigt.
    """
    marke = " ".join(marke.split())
    gruppe = " ".join(gruppe.split())
    if not gruppe or gruppe.lower() in marke.lower():
        return marke[:60]
    zusammen = f"{gruppe} {marke}"
    return zusammen if len(zusammen) <= 60 else marke[:60]


class HWiNFO:
    """Der Leser des Speicherblocks; ohne HWiNFO meldet er schlicht nichts."""

    CHIP = "hwiinfo"

    def __init__(self, ttl: float = 2.0):
        self.ttl = ttl
        self._zeit = 0.0
        self._werte: dict[str, float] = {}
        self._grund: str | None = None
        self._letzte_messzeit: int | None = None
        self._unveraendert = 0

    def lesen(self) -> dict[str, float]:
        """Die Temperaturen als ``hwiinfo:Name`` -> Grad, leer ohne HWiNFO."""
        jetzt = time.monotonic()
        if jetzt - self._zeit < self.ttl:
            return dict(self._werte)
        self._zeit = jetzt
        puffer = _puffer()
        if puffer is None:
            self._werte = {}
            return {}
        angaben = kopf(puffer)
        if angaben is None:
            self._werte = {}
            self._grund = ("Der Speicherblock von HWiNFO sieht fremd aus - "
                           "vielleicht ist es eine andere Fassung als erwartet.")
            return {}
        self._merke_stillstand(angaben["messzeit"])
        self._grund = None            # ein Block, der sich lesen laesst, hat keinen Grund
        self._werte = {}
        for wert in messwerte(puffer):
            self._werte.setdefault(wert.kennung, round(wert.wert, 1))
        return dict(self._werte)

    def _merke_stillstand(self, messzeit: int) -> None:
        if messzeit == self._letzte_messzeit:
            self._unveraendert += 1
        else:
            self._letzte_messzeit = messzeit
            self._unveraendert = 0

    @property
    def steht(self) -> bool:
        """Bringt HWiNFO noch neue Zahlen? Die kostenlose Fassung hört nach
        etwa zwölf Stunden auf und muss neu gestartet werden."""
        return self._unveraendert >= STEHEN_NACH

    @property
    def grund(self) -> str | None:
        """Warum es keine Temperaturen gibt, falls überhaupt etwas fehlt."""
        return self._grund

    @property
    def stillstand(self) -> str | None:
        """Der Satz dafuer, dass HWiNFO zwar da ist, aber nicht mehr misst."""
        return TEXT_STILLSTAND if self.steht else None

    def hinweis(self) -> str | None:
        """Was zu HWiNFO zu sagen ist, wenn es gar keine Temperaturen gibt.

        Nicht verwechselt werden: Ein Stillstand hat seinen eigenen Satz
        (:attr:`stillstand`), und wenn alles in Ordnung ist, sagt diese
        Methode nichts.
        """
        if self._werte or self._grund:
            return None
        return TEXT_START


def _puffer() -> bytes | None:
    """Den Block oeffnen und ganz lesen - zweimal, weil die Groesse erst spaeter feststeht."""
    if not IS_WINDOWS:
        return None
    for name in NAMEN:
        try:
            mitnahme = _karte(name, 64)
        except OSError:
            continue
        try:
            angaben = kopf(mitnahme[:])
        finally:
            mitnahme.close()
        if angaben is None:
            return None
        noetig = max(angaben["ab_werte"] + angaben["anzahl_werte"] * angaben["groesse_wert"],
                     angaben["ab_gruppen"] + angaben["anzahl_gruppen"] * angaben["groesse_gruppe"],
                     64)
        try:
            mitnahme = _karte(name, noetig)
        except OSError:
            return None
        try:
            return mitnahme[:]
        finally:
            mitnahme.close()
    return None


def _karte(name: str, laenge: int) -> mmap.mmap:
    """Ein Lesezeichen auf den bereits bestehenden Speicherblock.

    Ein anonymes ``mmap`` mit ``tagname`` öffnet die vorhandene Markierung des
    anderen Programms - genau so, wie es die Windows-API mit
    ``OpenFileMapping`` auch macht.
    """
    return mmap.mmap(-1, laenge, tagname=name, access=mmap.ACCESS_READ)

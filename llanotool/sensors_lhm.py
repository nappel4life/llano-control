"""CPU-Temperaturen unter Windows - von LibreHardwareMonitor erfragt.

Zweite Quelle neben HWiNFO, und fuer manche Rechner die bessere:
LibreHardwareMonitor ist kostenlos, bringt seinen eigenen signierten Treiber
mit und kann auf Wunsch einen kleinen Web-Server auf dem eigenen Rechner
anlaufen lassen (Optionen → „Remote Web Server“, standardmaessig Port 8085).
Der liefert alle Messwerte als Baum in einer einzigen Datei.

Der Weg hat zwei Vorteile gegenueber dem Speicherblock von HWiNFO: Er
funktioniert auch dann, wenn LibreHardwareMonitor als Administrator laeuft (bei
HWiNFO ist fuer ein normales Programm dann nichts mehr zu lesen), und es ist
eine Anfrage an eine Adresse statt ein gemeinsamer Speicher, dessen Aufbau sich
mit jeder Fassung aendern kann. Dafur muss der Web-Server erst eingeschaltet
werden.

Der Baum kommt so, wie ihn das Programm auf dem Bildschirm zeigt: Knoten mit
Kindern, und die Blaetter sind die Messwerte. Ein Blatt erkennt man an „Type“;
Temperaturen tragen dort das Wort „Temperature“. Fuer die Zahl gibt es zwei
Angebote - „RawValue“ als nackte Zahl und „Value“ als formatierter Text mit
Einheit, je nach Sprach- und Ländereinstellung mit Komma statt Punkt. Beides
wird gelesen, der nackten Zahl gehoert der Vorrang.

Nur lokal und ohne Vermittlung: Die Anfrage geht an 127.0.0.1, und jeder ueber
die Umgebung eingetragene Vermittler wird uebersprungen - ein Blick in die
eigene Werkstatt wird dadurch nicht besser, nur langsamer.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .sensors_hwiinfo import (OBERE_SCHWELLE, UNTERE_SCHWELLE, Messwert,
                            marke, ohne_einzelkerne)

ADRESSE = "http://127.0.0.1:8085/data.json"
_UMGEBUNG = "LLANO_LHM"

# Wie lange die Anfrage auf eine Antwort wartet, in Sekunden.
FRIST = 2.0

# Temperaturen heissen in dem Baum auf jeder Sprache gleich; danach wird
# gefiltert, nicht nach dem deutschen Wort fuer die Messart.
ART_TEMPERATUR = "Temperature"

TEXT_START = ("Ohne Messhilfe fehlt die Prozessortemperatur: LibreHardwareMonitor "
              "starten und in den Optionen den „Remote Web Server“ anlassen "
              "(Port 8085). Eine andere Adresse? Dann LLANO_LHM auf die eigene "
              "stellen, zum Beispiel http://127.0.0.1:8085/data.json.")


def temperaturen(aus_json, tiefe: list[str] | None = None) -> list[Messwert]:
    """Alle Temperaturblaetter aus dem Baum, mit dem Namen des Geraets davor.

    Die Gruppe ist der Grobvater des Blatts: ueber einem Messwert steht die
    Art („Temperatures“), darueber das Geraet („Intel Core i7 8700K“). Nach der
    Art zu fragen waere naemlich sprachabhaengig, nach der Ebene nicht.
    """
    out: list[Messwert] = []
    stapel = list(tiefe or [])
    if not isinstance(aus_json, dict):
        return out

    gruppe = stapel[-2] if len(stapel) >= 2 else (stapel[-1] if stapel else "")
    if str(aus_json.get("Type") or "") == ART_TEMPERATUR:
        wert = _zahl(aus_json)
        angeschrieben = str(aus_json.get("Text") or "").strip()
        if wert is not None and angeschrieben:
            out.append(Messwert(gruppe=gruppe, marke=marke(gruppe, angeschrieben),
                                wert=wert, quelle="lhm"))

    for kind in aus_json.get("Children") or []:
        out.extend(temperaturen(kind, stapel + [str(aus_json.get("Text") or "")]))
    return out


def _zahl(knoten: dict) -> float | None:
    """Die Temperatur als Zahl, aus dem nackten Wert oder dem formatierten Text.

    „NaN“ kommt in diesem Baum tatsaechlich vor - als Wort. Ein leerer Wert
    heisst, dass das Geraet gerade nichts meldet, und ist kein Grund fuer eine
    Zeile in der Auswahl.
    """
    nackt = knoten.get("RawValue")
    if isinstance(nackt, (int, float)) and not isinstance(nackt, bool):
        nackt = float(nackt)
        return nackt if UNTERE_SCHWELLE < nackt < OBERE_SCHWELLE else None
    text = str(knoten.get("Value") or "").strip()
    if not text:
        return None
    zahlen = ""
    for zeichen in text:
        if zeichen.isdigit() or zeichen in ",.-+":
            zahlen += zeichen.replace(",", ".")
        elif zahlen:
            break
    try:
        wert = float(zahlen)
    except ValueError:
        return None
    return wert if UNTERE_SCHWELLE < wert < OBERE_SCHWELLE else None


class LHM:
    """Der kleine Kunde des Web-Servers; laeuft der nicht, sagt er nichts."""

    CHIP = "lhm"

    def __init__(self, ttl: float = 2.0, adresse: str | None = None):
        self.ttl = ttl
        self.adresse = adresse or os.environ.get(_UMGEBUNG) or ADRESSE
        self._zeit = 0.0
        self._werte: dict[str, float] = {}
        self._grund: str | None = None

    def lesen(self) -> dict[str, float]:
        """Die Temperaturen als ``lhm:Name`` -> Grad, leer ohne LibreHardwareMonitor."""
        jetzt = time.monotonic()
        if jetzt - self._zeit < self.ttl:
            return dict(self._werte)
        self._zeit = jetzt
        antwort = _abruf(self.adresse)
        if antwort is None:
            self._werte = {}
            return {}
        self._werte = {}
        for wert in ohne_einzelkerne(temperaturen(antwort)):
            self._werte.setdefault(wert.kennung, round(wert.wert, 1))
        return dict(self._werte)

    @property
    def stillstand(self) -> str | None:
        """Diese Quelle hat keinen bekannten Aufhoerzeitpunkt wie die kostenlose
        HWiNFO-Fassung; still wird sie hoechstens zusammen mit dem Programm."""
        return None

    @property
    def grund(self) -> str | None:
        """Warum diese Quelle nichts sagt, falls ueberhaupt etwas zu sagen ist."""
        return self._grund

    def hinweis(self) -> str | None:
        """Der Satz dafuer, dass diese Quelle nichts beisteuert."""
        if self._werte:
            return None
        return TEXT_START


def _abruf(adresse: str) -> dict | None:
    """Die eine Datei holen. Ohne Antwort, ohne Vermittler, ohne Aufhebens.

    Die Frist ist grosszuegig, weil LibreHardwareMonitor seine Datei erst beim
    Fragen zusammenbaut: gleich nach dem Start kann die erste Antwort eine
    Weile brauchen. Ist ueberhaupt nichts erreichbar, antwortet Windows sofort
    mit "abgelehnt" - die Frist kostet also nur dort Zeit, wo wirklich etwas
    antworten will.
    """
    vermittler = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with vermittler.open(adresse, timeout=FRIST) as antwort:
            return json.load(antwort)
    except (urllib.error.URLError, OSError, ValueError):
        return None

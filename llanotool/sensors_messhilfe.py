"""Die Messhilfe im eigenen Auftrag: LibreHardwareMonitor als Zusatzdatei.

Windows gibt die Prozesstemperatur nur an ein Programm mit Kernel-Treiber
heraus. Der bisherige Weg war deshalb ein zweites Programm: LibreHardware-
Monitor mit eingeschaltetem Web-Server (:mod:`llanotool.sensors_lhm`). Diese
Datei ist der kuerzere Weg - dieselbe Bibliothek, aber von einem zwei und
zwanzig Kilobyte kleinen Helfer (:file:`packaging/messhilfe/messhilfe.cs`) im
Auftrag dieses Programms gestartet. Kein Symbolbereich, kein Port, keine
Einstellungsdatei und kein Programm, das weiterlaeuft, wenn dieses hier
laengst zu ist.

Warum ein eigener Prozess und nicht die Bibliothek direkt im Python?

* Das Steuerprogramm haelt sich an den Grundsatz, ausser der
  Standardbibliothek nichts mitzubringen. Eine .NET-Bruecke (pythonnet) waere
  die dritte Paketsammlung im Haus - und die erste, die beim Verpacken
  mitredet.
* Die Bibliothek liest durch einen Kernel-Treiber. Faellt sie um, faellt mit
  ihr das Fenster; die Erfahrung heisst hier "Zugriffsverletzung beim
  Aufraeumen". Ein Helfer, der umfaellt, kostet eine fehlende Zahl.
* Und weil der Helfer ein eigener Prozess ist, kann er spaeter fuer sich
  allein erhoht laufen, ohne dass das ganze Programm erhoht laufen muss.

Der Helfer haengt an diesem Prozess wie eine Pflanze an ihrer Rankhilfe: er
liest die Standardeingabe und wartet. Stirbt dieses Programm, schliesst die
Leitung, und der Helfer geht aus. Ein zurueckbleibender Helfer waere genau
das zweite Programm, das wir gerade abschaffen.

Was er zurueckgibt, sind dieselben Namen wie beim Web-Server (``lhm:Name``).
Eine einmal getroffene Auswahl an Messstellen bleibt also erhalten, egal
welche der beiden Quellen gerade liefert. Und wer beide Quellen hat, bekommt
die Vereinigung: den Prozessor von der einen, die Grafikkarte von der anderen.

Alles an ihr laeuft in einem einzigen Faden, der an der Ausgabe des Helfers
sitzt. Kein Aufruf von hier wartet auf ein anderes Programm - die Oberflaeche
sieht die letzte Antwort des Helfers, so frisch oder so alt sie ist.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from .sensors_hwiinfo import (OBERE_SCHWELLE, UNTERE_SCHWELLE, Messwert, marke,
                              ohne_einzelkerne)

__all__ = ["Messhilfe", "BRUECKE", "ORDNER", "fundstelle", "datei",
           "temperaturen", "meldung"]

BRUECKE = "llano-messhilfe.exe"

# Der Ordner unter dem Programmordner, nicht in ``_internal``: der Helfer ist
# ein eigenes Programm und keine Python-Bibliothek.
ORDNER = "messhilfe"

# Wer die Messhilfe woanders hinlegt (Entwicklung, tragbarer Ordner), nennt
# diesen Ordner oder die Datei in dieser Variable.
_UMGEBUNG = "LLANO_MESSHILFE"

# Wie oft der Helfer zaehlen soll, und wie alt die letzte Antwort sein darf.
TAKT = 1000
VERFALL = 6.0

# Nach drei Fehlstarts ist Ruhe. Ein Helfer, der bei jeder Abfrage neu anlaeuft,
# ist ein zweiter Grund fuer dieselbe Beschwerde.
_NEUSTARTS = 3
_FRIST = 3.0            # fruehestens so viele Sekunden nach dem letzten Versuch

# Windows wuerde fuer den Helfer ein Konsolenfenster aufmachen.
_NO_WINDOW = 0x08000000

TEXT_OHNE_TREIBER = (
    "Die mitgelieferte Messhilfe arbeitet, aber dieser Rechner hat keinen "
    "Treiber fuer die Prozessorfuehler (PawnIO). Den legt LibreHardwareMonitor "
    "beim ersten Start dazu - oder die Kurve folgt der Grafikkarte.")

TEXT_OHNE_RECHTE = (
    "Die mitgelieferte Messhilfe arbeitet, aber die Prozessorfuehler darf nur "
    "lesen, wer erhoht arbeitet: dieses Programm als Administrator starten - "
    "oder die Messhilfe mit eigenem Web-Server laufen lassen.")

TEXT_OHNE_ANTWORT = (
    "Die mitgelieferte Messhilfe antwortet nicht. Sie liegt im Programmordner, "
    "sagt aber nichts - die Sicherheitssoftware des Rechners haelt den Treiber "
    "zurueck, oder die .NET-Fassung fehlt.")

TEXT_KEINE_WERTE = (
    "Die mitgelieferte Messhilfe meldet keine Temperatur. Treiber und Rechte "
    "sind da, die Fuehler schweigen - die Kurve kann sich dann nur an der "
    "Grafikkarte oder einer Waermezone orientieren.")


def _kandidaten() -> list[str]:
    """Die Ordner, in denen der Helfer liegen kann, die naechsten zuerst."""
    aus_umgebung = os.environ.get(_UMGEBUNG)
    wenn = [aus_umgebung] if aus_umgebung else []
    erst = sys.argv[0] if sys.argv and sys.argv[0] else ""
    grund = os.path.dirname(os.path.abspath(erst)) if erst else ""
    if getattr(sys, "frozen", False):
        grund = os.path.dirname(os.path.abspath(sys.executable))
    gepackt = getattr(sys, "_MEIPASS", None)
    hier = os.path.dirname(os.path.abspath(__file__))
    return [w for w in wenn + [
        os.path.join(grund, ORDNER) if grund else "",
        os.path.join(gepackt, ORDNER) if gepackt else "",
        grund,
        os.path.join(hier, "..", "..", "paket", ORDNER),   # Bauwagen, vor dem Verpacken
    ] if w]


def fundstelle() -> str | None:
    """Der Ordner mit dem Helfer, oder nichts."""
    for ordner in _kandidaten():
        try:
            if os.path.exists(os.path.join(ordner, BRUECKE)):
                return os.path.abspath(ordner)
        except (OSError, ValueError):
            continue
    return None


def datei() -> str | None:
    """Der volle Pfad zum Helfer, oder nichts."""
    ordner = fundstelle()
    return os.path.join(ordner, BRUECKE) if ordner else None


# ------------------------------------------------------------------- Die Zeilen

def _grad(wert) -> float | None:
    """Die Zahl aus der Meldung, nur wenn sie eine Temperatur sein kann."""
    try:
        grad = float(wert)
    except (TypeError, ValueError):
        return None
    if grad != grad or grad in (float("inf"), float("-inf")):
        return None
    return grad if UNTERE_SCHWELLE < grad < OBERE_SCHWELLE else None


def temperaturen(nachricht: dict) -> list[Messwert]:
    """Eine ``werte``-Zeile des Helfers in Messwerte ueberetzen.

    Gruppe ist das Geraet, Marke ist dessen Messstelle - dieselbe Regel wie
    beim Web-Server, damit beide Quellen auf dieselben Namen kommen.
    """
    out: list[Messwert] = []
    eintrag = nachricht.get("temperaturen")
    if not isinstance(eintrag, list):
        return out
    for blatt in eintrag:
        if not isinstance(blatt, dict):
            continue
        grad = _grad(blatt.get("wert"))
        gruppe = str(blatt.get("geraet") or "").strip()
        messstelle = str(blatt.get("messstelle") or "").strip()
        if grad is None or not messstelle:
            continue
        out.append(Messwert(gruppe=gruppe, marke=marke(gruppe, messstelle),
                            wert=grad, quelle="lhm"))
    return out


def meldung(nachricht: dict) -> dict:
    """Eine ``start``- oder ``fehler``-Zeile in eine Auskunft umformen.

    Die Auskunft ist der Grund fuer diese ganze Datei: woher das Schweigen
    kommt, weiss die Bibliothek selbst, und nur sie.raten koennte der Nutzer.
    """
    zahl = nachricht.get("geraete")
    gerate = int(zahl) if isinstance(zahl, (int, float)) and not isinstance(zahl, bool) else 0
    return {
        "art": str(nachricht.get("art") or ""),
        "erhoeht": bool(nachricht.get("erhoeht")),
        "treiber": bool(nachricht.get("treiber")),
        "treiber_fassung": str(nachricht.get("treiber_fassung") or ""),
        "bibliothek": str(nachricht.get("bibliothek") or ""),
        "geraete": gerate,
        "text": str(nachricht.get("text") or ""),
    }


def _deuten(zeile: str) -> dict | None:
    """Eine Zeile des Helfers in ein Woerterbuch, oder nichts bei Unsinn."""
    zeile = zeile.strip()
    if not zeile.startswith("{"):
        return None
    try:
        daten = json.loads(zeile)
    except ValueError:
        return None
    return daten if isinstance(daten, dict) else None


# --------------------------------------------------------------------- Die Quelle

class Messhilfe:
    """Der eigene Helfer als Temperaturquelle; schweigt statt zu werfen."""

    CHIP = "lhm"

    def __init__(self, befehl: list[str] | None = None, takt: int = TAKT,
                 verfall: float = VERFALL, neustarts: int = _NEUSTARTS,
                 frist: float = _FRIST):
        self.befehl = befehl
        self.takt = takt
        self.verfall = verfall
        self.neustarts = neustarts
        self.frist = frist
        self._prozess = None
        self._schloss = threading.Lock()
        self._werte: dict[str, float] = {}
        self._zeit = 0.0
        self._bericht: dict | None = None
        self._grund: str | None = None
        self._rauschen: list[str] = []
        self._versuche = 0
        self._zuletzt = 0.0
        self._fertig = False              # bewusst geschlossen, nicht abgestuerzt

    # -------------------------------------------------------------- Bereitschaft

    @property
    def anwesend(self) -> bool:
        """Liegt der Helfer hier? Ob er danach etwas meldet, ist eine andere Frage."""
        return bool(self.befehl) or datei() is not None

    @property
    def bericht(self) -> dict | None:
        """Was der Helfer ueber sich selbst gesagt hat, falls er schon sprach."""
        return self._bericht

    @property
    def grund(self) -> str | None:
        return self._grund

    @property
    def stillstand(self) -> str | None:
        """Diese Quelle hat keinen bekannten Aufhoerzeitpunkt."""
        return None

    def hinweis(self) -> str | None:
        """Warum die mitgebrachte Messhilfe nichts fuer die Kurve tut.

        Sie liefert etwas? Dann gibt es nichts zu erklaeren. Ein Hinweis nur
        fuer den Fall, dass sie schweigt - zwei Saelen unter der Auswahl waeren
        laestiger als eine fehlende Zahl.
        """
        if not self.anwesend:
            return None
        if self._werte and time.monotonic() - self._zeit <= self.verfall:
            return None                     # sie liefert gerade etwas
        if self._grund:
            return f"Die mitgelieferte Messhilfe meldet: {self._grund}"
        bericht = self._bericht
        if bericht is None:
            if self._rauschen:
                return (TEXT_OHNE_ANTWORT + " Letzter meldeter Satz des Helfers: \""
                        + self._rauschen[-1][:160] + "\"")
            return TEXT_OHNE_ANTWORT if self._versuche else None
        if not bericht["treiber"]:
            return TEXT_OHNE_TREIBER
        if not bericht["erhoeht"]:
            return TEXT_OHNE_RECHTE
        return TEXT_KEINE_WERTE

    def selbstbericht(self) -> list[str]:
        """Zeilen fuer ``llano selftest``: was da liegt, und was es meldet.

        Ohne diese Zeilen waere die Messhilfe ein Punkt im Installer, ueber dem
        man raten muesste. Der Bericht fragt sie kurz ab und sagt, was sie von
        sich weiss - Treiber, Rechte, Bibliotheksfassung.
        """
        pfad = self.befehl[0] if self.befehl else datei()
        if not pfad:
            return [f"Messhilfe     : keine gefunden ({ORDNER}/{BRUECKE}) - "
                    "Prozessortemperatur bleibt ohne eigene Quelle"]
        zeilen = [f"Messhilfe     : {pfad}"]
        self.lesen()
        zeit = time.monotonic()
        while self._bericht is None and time.monotonic() - zeit < 4.0:
            self.lesen()
            time.sleep(0.1)
        bericht = self._bericht
        if bericht is None:
            grund = self.grund or self.hinweis() or TEXT_OHNE_ANTWORT
            return zeilen + [f"                : meldet sich nicht - {grund.strip()}"]
        treiber = (f"da ({bericht['treiber_fassung']})" if bericht["treiber"]
                   else "fehlt")
        rechte = "erhoeht" if bericht["erhoeht"] else "normal"
        zeilen.append(f"                : Bibliothek {bericht['bibliothek'] or '?'}, "
                      f"Treiber {treiber}, Rechte {rechte}, "
                      f"{bericht['geraete']} Geraete")
        werte = self.lesen()
        if not werte:
            # Die Meldung ueber sich selbst kommt vor der ersten Zaehlung; ein
            # kurzer Moment noch, dann weiss der Bericht auch, ob Werte kommen.
            zeit = time.monotonic()
            while not werte and time.monotonic() - zeit < 1.5:
                time.sleep(0.1)
                werte = self.lesen()
        zeilen.append(f"                : {len(werte)} Messstellen"
                      if werte else "                : keine Messstelle gemeldet")
        return zeilen

    # -------------------------------------------------------------------- Start

    def _anlegen(self) -> bool:
        """Den Helfer anlaufen lassen. Ohne Warten, ohne Werfen."""
        pfad = self.befehl or ([datei()] if datei() else [])
        if not pfad:
            return False
        befehl = list(pfad)
        if not self.befehl:                 # der echte Helfer will seinen Takt hoeren
            befehl += ["--takt", str(self.takt)]
        self._versuche += 1
        self._zuletzt = time.monotonic()
        zusatz = {"creationflags": _NO_WINDOW} if os.name == "nt" else {}
        try:
            prozess = subprocess.Popen(
                befehl,
                stdin=subprocess.PIPE,      # der Kanarienvogel; es wird nie geschrieben
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,   # Fehlermeldungen laufen ins selbe Tonband
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                **zusatz)
        except OSError as ausnahme:
            self._grund = f"Der Helfer konnte nicht gestartet werden ({ausnahme})."
            return False
        self._prozess = prozess
        threading.Thread(target=self._lesen, args=(prozess,), daemon=True,
                         name="messhilfe-lese").start()
        return True

    def _neu(self) -> bool:
        """Der erste Start, danach bis zu drei Nachstarts - mit Abstand."""
        with self._schloss:
            if self._fertig or self._prozess is not None:
                return self._prozess is not None
            if self._versuche >= self.neustarts:
                return False
            if self._versuche and time.monotonic() - self._zuletzt < self.frist:
                return False
            return self._anlegen()

    # -------------------------------------------------------------------- Lesen

    def _lesen(self, prozess) -> None:
        """Am Ausgabekanal sitzen, bis er sich schliesst.

        Was der Faden nicht versteht, laesst er liegen - eine halbe Zeile beim
        Abschied ist kein Grund, die letzte gute Antwort wegzuwerfen. Die
        letzten dieser Zeilen bleiben als Tonband zurueck: Wenn der Helfer an
        der .NET-Laufzeit oder am Treiber scheitert, steht die Antwort des
        Betriebssystems genau dort, und nirgends sonst.
        """
        try:
            for zeile in prozess.stdout or ():
                daten = _deuten(zeile)
                if daten is None:
                    text = zeile.strip()
                    if text:
                        self._rauschen = (self._rauschen + [text])[-3:]
                    continue
                art = daten.get("art")
                if art == "werte":
                    werte: dict[str, float] = {}
                    for wert in ohne_einzelkerne(temperaturen(daten)):
                        werte.setdefault(wert.kennung, round(wert.wert, 1))
                    self._werte = werte
                    self._zeit = time.monotonic()
                elif art == "start":
                    self._bericht = meldung(daten)
                elif art == "fehler":
                    self._grund = meldung(daten)["text"] or self._grund
        except (OSError, ValueError):
            pass
        finally:
            try:
                if prozess.stdout:
                    prozess.stdout.close()
            except OSError:
                pass
            try:
                prozess.wait(timeout=2.0)
            except Exception:               # noqa: BLE001
                pass
            with self._schloss:
                if prozess is self._prozess:
                    # Noch immer unser Helfer: dann ist sein Ausbleiben auch
                    # unsere Nachricht. Ein spaet endender Faden des
                    # vorherigen darf einem frischen nichts loeschen.
                    self._prozess = None
                    self._werte = {}

    def lesen(self) -> dict[str, float]:
        """Die Temperaturen als ``lhm:Name`` -> Grad; leer, wenn nichts geht."""
        if self._prozess is None and not self._fertig:
            self._neu()
        if not self._werte:
            return {}
        if time.monotonic() - self._zeit > self.verfall:
            return {}                       # die letzte Antwort ist zu alt
        return dict(self._werte)

    # ----------------------------------------------------------------- Abschied

    def schliessen(self) -> None:
        """Den Helfer verabschieden: Leitung zu, und notfalls nachhelfen.

        Er haengt an dieser Leitung, also ist Zuzumachen der hoefliche Weg. Ein
        Programm, das nach dem Schliessen der Oberflaeche im Task-Manager
        steht, kostet denselben Aerger wie das zweite Programm, das wir gerade
        loswerden wollten.
        """
        with self._schloss:
            self._fertig = True
            prozess = self._prozess
            self._prozess = None
            self._werte = {}
        if prozess is None:
            return
        try:
            if prozess.stdin:
                prozess.stdin.close()
        except OSError:
            pass
        try:
            prozess.wait(timeout=2.0)
        except Exception:                   # noqa: BLE001
            try:
                prozess.terminate()
            except OSError:
                pass
        try:
            if prozess.stdout:
                prozess.stdout.close()
        except OSError:
            pass

    def zuruecksetzen(self) -> None:
        """Fuer Versuche - und fuer jemanden, der die Messhilfe nachtraeglich legt."""
        self.schliessen()
        self._fertig = False
        self._versuche = 0
        self._zuletzt = 0.0
        self._bericht = None
        self._grund = None
        self._rauschen = []

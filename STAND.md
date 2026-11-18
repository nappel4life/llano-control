# Stand — llano-control

*Aufgeschrieben am 18. November 2026, nach Fassung 1.1.11 (veröffentlicht) und
1.2.0 (im Bau). 98 Prüfungen, davon 4 nur auf Windows; rund 5.800 Zeilen
Programm über alle Module.*

---

## Wofür das Programm ist

Der **llano V12 Ultra** ist ein USB-Kühlernetzteil für Notebooks (Kennung
`374a:b101`). Dieses Programm steuert es unter **Linux und Windows**:
Lüfterstufe, Lüfterkurve nach Temperatur, LED-Farbe, Effekt, Takt und
Helligkeit — als Oberfläche mit Taskleisten-Symbol, als Kommandozeile und als
Hintergrunddienst. Eine Rust-Fassung (`llano-rs.exe`) teilt sich dieselbe
Einstellungs- und Sperrdatei.

## Was gerade gilt

| | |
|---|---|
| Fassung | 1.1.11 veröffentlicht, **1.2.0 im Bau** |
| Gerätepfad Linux | hidraw, direkt nachgemessen am Gerät |
| Gerätepfad Windows | setupapi + hid.dll, ohne dritte Bibliothek |
| Oberfläche | PyQt6, dunkles Theme, Lüfter/ Licht/ Kurve/ Temperaturen |
| Temperaturen Linux | coretemp, k10temp, acpitz, nvme, nvidia, spd5118, iwlwifi, … |
| Temperaturen Windows | NVIDIA über NVAPI, AC-Wärmezonen, HWiNFO, LibreHardwareMonitor |
| Einstellungsdatei | `%APPDATA%\llano\config.json` / `~/.config/llano/config.json` |
| Startprotokoll | `%APPDATA%\llano\oberflaeche.txt` (seit 1.1.8 jeder Schritt) |
| Pakete | Windows-Installer, `.deb`, AppImage, `.tar.gz`, `llano-rs.exe` |
| Bauen | GitHub Actions, sechs Läufe; Veröffentlichung nur, wenn alle grün sind |

Alle Befehle: `status`, `fan`, `light`, `power`, `sensors`, `curve`, `daemon`,
`gui`, `config`, `rules`, `selftest`. Der Selbsttest ist die Antwort auf fast
jede Frage — er prüft jeden Schritt einzeln und sagt, welcher fehlt.

## Die Sache mit der Prozesstemperatur

**Windows gibt sie ohne Kernel-Treiber nicht heraus.** Die Fühler hängen an
modelspezifischen Registern, und die darf nur ein Treiber in Ring 0 lesen. Eine
Bibliothek allein reicht deshalb nicht, und ein eigenes Programm bräuchte einen
von Microsoft signierten Treiber. Es bleibt: **ein fremdes Programm mit
signiertem Treiber als Quelle** — oder die Kurve folgt der Grafikkarte.

Eingebaut sind drei Wege, und sie schließen sich nicht gegenseitig aus:

1. **HWiNFO** — liest den gemeinsamen Speicherblock mit, den das Programm
   schreibt (*Shared Memory Support*). Werte erscheinen als `hwiinfo:`.
   Nachteil: läuft HWiNFO als Administrator, ist für ein normales Programm
   nichts mehr zu lesen. Die kostenlose Fassung hält ausserdem nach etwa zwölf
   Stunden mit neuen Zahlen inne; das meldet das Programm.
2. **LibreHardwareMonitor** — fragt seinen eingebauten Web-Server ab
   (*Optionen → Remote Web Server*, Port 8085). Werte erscheinen als `lhm:`.
   Vorteil: funktioniert auch über Integritätsgrenzen, also wenn die Messhilfe
   erhöht läuft.
3. **Der Haken im Installer** (neu in 1.2.0, standardmäßig an) — legt
   LibreHardwareMonitor nach `llano-control\helfer`, mit vorgefertigten
   Einstellungen (Web-Server an, minimiert im Symbolbereich) und einer
   Anmeldungsaufgabe mit höchsten Rechten, damit nicht bei jeder Anmeldung eine
   Sicherheitsabfrage kommt. Deinstallieren meldet die Aufgabe zuerst ab und
   schliesst den laufenden Helfer.

*Warum nicht die DLL aus der Software des Herstellers?* Die bringt fast immer
WinRing0 mit — einen Ring-0-Treiberlader, den Microsoft als angreifbar meldet
und dessen Liste blockierter Treiber auf aktuellem Windows standardmäßig scharf
ist. Ein Installer damit wäre bei jeder Installation ein Alarm und auf Rechnern
mit Speicherintegrität einfach taub.

Die **Bibliothek** desselben Programms (`LibreHardwareMonitorLib`) wäre der
eigentlich sauberste Weg: Werte direkt im eigenen Programm, kein zweites
Symbol. Sie ist .NET; ihr Laden aus Python (Laufzeit, Verpacken,
Treiberzugriff) ist ein eigenes Stück Arbeit. Der Haken ist die Vorstufe, bei
der sich die Quelle später darunter austauschen lässt.

## Was kaputt war und wie es gefunden wurde

Vier Fehler, vier verschiedene Lehren. Alle sind zu und geprüft.

**1. Eine kaputte Einstellungsdatei ließ die Oberfläche sterben, nachdem sie
den Kühler schon eingeschaltet hatte** (1.1.5). Grund: ungeprüfte Werte
direkt in `int()`/`float()`. Heute formt `sauber()` jeden Wert, bevor er
benutzt wird, die Datei trägt ihre Fassung, und sechzehn zerstoerte
Dateien müssen ein Fenster bauen können — die Bauautomatik probiert das durch.
Ein Deinstallieren fragt inzwischen, ob die Einstellungen mit weg sollen.

**2. Ein Update ließ alte Dateien liegen** (1.1.7). Der Installer überschreibt
nur Gleichnamiges; der `_internal`-Ordner eines verpackten Programms behielt
dann zwei Qt-Bibliotheken, und die Oberfläche starb, bevor der erste
Python-Befehl lief — ohne Fenster, ohne Meldung, ohne eine geschriebene Datei.
Seit dem macht der Installer den Ordner vorher leer, und die Bauautomatik
installiert erstmals **die fertige Datei auf einem echten Windows** und startet
sie von der Festplatte, statt nur die gebaute Mappe zu testen.

**3. Der eigentliche Absturz: `HidP_GetCaps`** (1.1.10). Der Windows-Aufruf
schreibt die *vollständige* Kapazitätsstruktur — 64 Byte, in neueren Fassungen
66 — und fragt nicht, wie groß das Gegenüber ist. Nachgebaut waren die fünf
gelesenen Felder, zehn Byte. Der Rest landete im Speicher des Interpreters und
fiel später beim Fensterbauen um, als dieser aufräumte. Drei Fassungen lang war
dafür niemand zu finden, weil nirgends im eigenen Code etwas falsch aussah: Der
Fehler zeigte sich am Opfer, nicht am Täter. Gefunden hat ihn der
Absturzfänger, der mit dem Startprotokoll in dieselbe Datei schreibt —
`Windows fatal exception: access violation, Garbage-collecting` war die
Wendung, die alles sagte. Die nackten Größen aller Windows-Strukturen stehen
jetzt in Prüfungen fest.

**4. Ein zweites Beispiel derselben Art:** der Begleiter einer unerledigten
Anzeige hatte ein Feld zu viel und schob die Ereigniskennung eine Stufe höher —
Windows hätte eine leere Kennung vorgefunden. Bisher folgenlos, weil diese
Anzeige nur der Selbsttest liest; trotzdem richtig gestellt.

## Reden statt raten

Aus dieser Serie stammt auch, was das Programm heute über sich selbst
aufschreibt — die eigentliche Lehre der letzten Stunden:

* **Jeder Startschritt steht in `oberflaeche.txt`**, von der Fassung über „die
  Anwendung ist gebaut" bis „der Abfragefaden läuft". Was fehlt, ist die Stelle,
  an der es stand.
* **Der Absturzfänger** meldet auch einen Sturz einer Bibliothek, der keinen
  einzigen Python-Fehler wirft.
* **Die Wacht** schreibt eine halbe Minute nach dem Start den Stand jedes Fadens
  in dieselbe Datei, wenn die Schleife nicht anläuft. Ein Programm, das steht,
  war vorher von einem, das nie anfing, nicht zu unterscheiden.
* **Sitzt schon eine andere Fassung am Kühler**, sagt die Oberfläche das — am
  Terminal als Text, sonst als Frage. Sie wartet bewusst nicht schweigend.
* **Fehlt eine Messhilfe, steht der Grund unter der Temperaturenauswahl**, seit
  1.1.11 als Klick auf die Seite der Messhilfe.

## Prüfen und Bauen

```
python3 -m unittest discover -s tests        # 98 Pruefungen
QT_QPA_PLATFORM=offscreen python3 tools/gui_probe.py /tmp/pruef.png
```

Die Bauautomatik (`.github/workflows/pakete.yml`) baut nach: Prüfen auf Ubuntu
und Windows, Rust, Linux-Pakete, Windows-Installer — und veröffentlicht nur,
wenn **alle** grün sind. Der Windows-Lauf startet die gebaute Oberfläche,
installiert die fertige Datei stumm, prüft, dass das installierte Programm
läuft und dass der beigelegte Helfer wirklich im Ordner liegt.

## Offene Punkte

* **1.2.0 muss durch die Bauautomatik** — inklusive dem Nachweis, dass die
  beigelegte Messhilfe im Installationsordner ankommt.
* **Nach der Installation startet die Messhilfe erst zur nächsten Anmeldung.**
  Umstellung auf sofortigen Start über die eben angelegte Aufgabe.
* **Die Messhilfe ist ein fremdes Programm** (Mozilla Public License 2.0;
  Lizenztexte liegen im Helferordner). Wer den Haken nicht setzt, bekommt den
  Führungsweg statt einer Installation.
* **Der echte Beweis für `lhm:`-Werte fehlt noch am eigenen Gerät** — auf dem
  Bauwagen gibt es weder Fühler noch erlaubte Treiber, dort ist die Antwort
  deshalb nur eine Warnung.
* **HWiNFO und LibreHardwareMonitor müssen laufen bleiben**, sonst fällt ihre
  Quelle aus; beide haben dafür einen eigenen Autostart.
* Die Rust-Fassung ist am Windows-Gerät noch nicht ausprobiert.

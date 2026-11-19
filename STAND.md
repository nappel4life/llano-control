# Stand — llano-control

*Aufgeschrieben am 19. November 2026, nach Fassung 1.1.11 (veröffentlicht) und
1.3.0 (im Bau, darin ist 1.2.0 aufgegangen). 119 Prüfungen, davon 4 nur auf
Windows; rund 5.700 Zeilen Steuerprogramm, 372 Zeilen Helfer in C#.*

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
| Fassung | 1.1.11 veröffentlicht, **1.3.0 im Bau** (1.2.0 ist darin aufgegangen) |
| Gerätepfad Linux | hidraw, direkt nachgemessen am Gerät |
| Gerätepfad Windows | setupapi + hid.dll, ohne dritte Bibliothek |
| Oberfläche | PyQt6, dunkles Theme, Lüfter/ Licht/ Kurve/ Temperaturen |
| Temperaturen Linux | coretemp, k10temp, acpitz, nvme, nvidia, spd5118, iwlwifi, … |
| Temperaturen Windows | NVIDIA über NVAPI, AC-Wärmezonen, **mitgebrachte Messhilfe** (`{app}\messhilfe`), HWiNFO, LibreHardwareMonitor |
| Einstellungsdatei | `%APPDATA%\llano\config.json` / `~/.config/llano/config.json` |
| Startprotokoll | `%APPDATA%\llano\oberflaeche.txt` (seit 1.1.8 jeder Schritt) |
| Pakete | Windows-Installer, `.deb`, AppImage, `.tar.gz`, `llano-rs.exe` |
| Messhilfe | LibreHardwareMonitorLib 0.9.6 (MPL 2.0) + eigener Helfer `llano-messhilfe.exe` (C#, 20 KB) |
| Bauen | GitHub Actions, sechs Läufe; Veröffentlichung nur, wenn alle grün sind |

Alle Befehle: `status`, `fan`, `light`, `power`, `sensors`, `curve`, `daemon`,
`gui`, `config`, `rules`, `selftest`. Der Selbsttest ist die Antwort auf fast
jede Frage — er prüft jeden Schritt einzeln und sagt, welcher fehlt.

## Die Sache mit der Prozesstemperatur

**Windows gibt sie ohne Kernel-Treiber nicht heraus.** Die Fühler hängen an
modelspezifischen Registern, und die darf nur ein Treiber in Ring 0 lesen. Eine
Bibliothek allein reicht deshalb nicht, und ein eigener Treiber bräuchte ein
Signat von Microsoft. Es bleibt: **fremder Treiber als Quelle** — oder die Kurve
folgt der Grafikkarte.

**Die Messhilfe ist seit 1.3.0 eingebaut** — die Frage war nicht, *ob* man eine
DLL dazulegen darf, sondern *welche*: Die DLL aus der Hersteller-Software bringt
fast immer WinRing0 mit, einen Ring-0-Treiberlader, den Microsoft als angreifbar
meldet und dessen Liste blockierter Treiber auf aktuellem Windows scharf ist.
LibreHardwareMonitor hat WinRing0 in Fassung 0.9.6 gegen den signierten Treiber
**PawnIO** getauscht und steht unter MPL 2.0. Genau diese Bibliothek liegt jetzt
bei — zusammen mit einem 20 Kilobyte kleinen Helfer (`llano-messhilfe.exe`, C#),
den das Steuerprogramm selbst startet, abfragt und wieder beendet.

Vier Entscheidungen darin sind nicht selbstverständlich:

* **Ein eigener Prozess, nicht pythonnet.** Das Steuerprogramm hält an
  `dependencies = []` fest; eine .NET-Brücke wäre die dritte Paketsammlung im
  Haus und die erste, die beim Verpacken mitredet. Vor allem aber: Ein Fremd-
  programm, das durch einen Kernel-Treiber liest, fällt um — fällt es im eigenen
  Prozess, fällt das Fenster mit. Genau diese Erfahrung heißt hier
  „Zugriffsverletzung beim Aufräumen“. Ein Helfer, der umfällt, kostet eine
  fehlende Zahl.
* **Der Compiler, den Windows mitbringt.** Übersetzt wird mit
  `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`, ohne SDK, ohne NuGet.
  Die Bibliothek ist eine .NET-Framework-4.7.2-Baugruppe (nachgemessen an der
  Datei, nicht am Text), und die hat jeder aktuelle Windows-Rechner an Bord.
* **Der Helfer hängt an einer Leitung.** Er liest die Standardeingabe und
  wartet; stirbt das Steuerprogramm, schließt die Leitung, und er geht aus. Ein
  zurueckbleibender Helfer wäre genau das zweite Programm, das der Einbau
  abschaffen will. Der Fall ist geprüft, nicht angenommen.
* **Er redet über sich selbst.** Die erste Zeile nennt Treiber (PawnIO,
  installiert?), Rechte (erhöht?) und Bibliotheksfassung. Die Bibliothek weiß
  das — ohne diese Zeile wäre „keine CPU-Wert“ wieder eine Raterei gewesen, und
  die Oberfläche müsste zwischen „Treiber fehlt“ und „Du bist nicht
  Administrator“ raten.

Was der Einbau *nicht* abschaffen kann: Der Prozessor braucht PawnIO auf dem
Rechner **und** erhöhte Rechte. Beides sagt das Programm beim Namen (die
Oberfläche verlinkt dann den Treiber statt der Messhilfe), und beides bekommt
man über den Haken im Installer: Das komplette Messprogramm in
`llano-control\helfer` legt den Treiber mit einem Klick dazu und liefert seine
Werte über den Web-Server auch dann, wenn dieses Programm normal arbeitet.

Daneben arbeiten unverändert weiter:

1. **HWiNFO** — liest den gemeinsamen Speicherblock mit, den das Programm
   schreibt (*Shared Memory Support*). Werte erscheinen als `hwiinfo:`.
   Nachteil: läuft HWiNFO als Administrator, ist für ein normales Programm
   nichts mehr zu lesen. Die kostenlose Fassung hält ausserdem nach etwa zwölf
   Stunden mit neuen Zahlen inne; das meldet das Programm.
2. **LibreHardwareMonitor mit Web-Server** — Port 8085, Werte als `lhm:`.
   Vorteil: funktioniert über Integritätsgrenzen hinweg.

Alle Quellen melden in dieselbe Namensmenge (`lhm:` für beide Arten der
Messhilfe), deshalb bleibt eine einmal getroffene Messstellen-Auswahl erhalten,
egal welche Quelle gerade liefert. Die Vereinigung gewinnt: Prozessor von der
einen Quelle, Grafikkarte von der anderen.

## Was kaputt war und wie es gefunden wurde

Sieben Fehler, sieben verschiedene Lehren. Alle sind zu und geprüft.

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

**5. Eine stille Quelle verschluckte die Auskunft** (1.3.0). Auf Windows wird
die mitgebrachte Messhilfe immer erzeugt; liegt sie nicht im Ordner, schweigt
sie ohne Grund, und dieses Schweigen fing den Satz ab, der fuer den Fall da war
„da antwortet jemand, aber ohne Prozessor". Die Oberflaeche stand also genau
dann ohne Satz da, wenn jemand ihn am noetigsten hat. Gefunden hat das die
Bauautomatik, kein Prueflauf hier: Linux kennt keine mitgebrachte Messhilfe,
also konnte der Fehler dort gar nicht vorkommen. Seitdem gilt in `note()`:
Grund zuerst, und ueber allen stillen Quellen.

**6. Der Uebersetzer sah `"/out:"` ohne Datei** (1.3.0). In einer
Powershell-Mappe werden aus `"/out:" + Pfad` **zwei** Felder, kein Addiertes -
der Compiler bekam ein `/out:` ohne Angabe und nannte das „Missing file
specification". Deux Bauversuche brauchte es, bis das im Protokoll stand, weil
der erste nur die Fehlermeldung zeigte und nicht, was gemeint war. Seitdem
stehen die Angaben vorher fest in einer Antwortdatei, das Skript liest seine
eigene Datei nach dem Schreiben noch einmal, und die Pruefung horzt die Mappe
auf Addieren und Kommas. Nebenbei fand der Compiler einen echten Fehler im
eigenen Helfer: Geraete kommen als Liste, nicht als Feld.

**7. Ein Aufraeumen gab das Urteil ab** (1.3.0). Alle Pruefungen waren gruen -
Uebersetzen, Installieren, installierte Selbstdiagnose, laufende Oberflaeche,
Helfer im Ordner - und der Lauf endete trotzdem rot, weil als letztes ein
`taskkill` lief, dem niemand gehoerte (Rueckgabe 128). Die Bauautomatik haelt
die Rueckgabe des letzten Befehls fuer ihr Ergebnis. Seither steht nach dem
Aufraeumen ausdruecklich eine Null, und eine Pruefung huetet das.

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
python3 -m unittest discover -s tests        # 119 Pruefungen
QT_QPA_PLATFORM=offscreen python3 tools/gui_probe.py /tmp/pruef.png
```

Die Bauautomatik (`.github/workflows/pakete.yml`) baut nach: Prüfen auf Ubuntu
und Windows, Rust, Linux-Pakete, Windows-Installer — und veröffentlicht nur,
wenn **alle** grün sind. Der Windows-Lauf startet die gebaute Oberfläche,
installiert die fertige Datei stumm, prüft, dass das installierte Programm
läuft, dass die Messhilfe im Ordner liegt und dass die installierte
Selbstdiagnose etwas über sie zu sagen weiß.

Die Zusammenarbeit mit der Messhilfe wird mit einem **nachgebauten Helfer**
geprüft (`tests/helfer_probeweise.py`): Ein Prüflauf hier hat kein .NET, aber
die Zeilenverabredung, den Tod des Helfers, die Fehlermeldung der Laufzeit und
den höflichen Abschied kann er täuschend echt spielen. Eine eigene Prüfung hält
außerdem die Schlüssel beider Sprachen zusammen — tippt die eine Seite einen
Namen um, fällt das hier auf und nicht erst am Gerät.

Was ein Prüflauf hier **nicht** kann: `packaging/messhilfe/messhilfe.cs`
übersetzen und `bauen.ps1` ausführen. Beides sieht zum ersten Mal die
Bauautomatik, und die übersetzt nicht nur, sondern startet den fertigen Helfer
auch selbst und bricht den Lauf ab, wenn er keine Zeile über sich
schreibt. Erst mit diesem Lauf steht also fest, dass der Einbau funktioniert.

## Offene Punkte

* **Der Helfer ist auf einem echten Windows uebersetzt und installiert** und
  meldet sich dort selbst: `Bibliothek 0.9.6.0, Treiber fehlt, Rechte
  erhoeht`. Bewiesen ist damit die Kette, nicht den Zahl: Ein Bauauto-Rechner
  hat keine Fuehler, deshalb steht dort „keine Messstelle gemeldet".
* **Der Beweis von echten Zahlen fehlt weiter** — gemessen am eigenen
  Rechner, mit PawnIO und erhohten Rechten.
* **Ohne erhöhte Rechte fehlen die Prozessoren.** Der Helfer erfaehrt das und
  sagt es, aber ein Klick ist das noch nicht. Der naechste Schritt ist ein
  erhoht gestarteter Helfer (die Leitung darf ein UAC-Fenster nicht
  ueberleben — Datei oder lokaler Hafen statt Pipeline) oder ein Neustart des
  Programms mit erhoehten Rechten.
* **Der echte Beweis für `lhm:`-Werte fehlt noch am eigenen Gerät** — auf dem
  Bauwagen gibt es weder Fühler noch erlaubte Treiber, dort ist die Antwort
  deshalb nur eine Warnung.
* **PawnIO liegt nicht bei.** Der Treiber kommt ueber das Messprogramm (ein
  Klick) oder von pawnio.eu; die Oberflaeche verlinkt beides an der richtigen
  Stelle. Ein eigener Installationshaken dafuer ist eine eigene Frage — es ist
  ein Kernel-Treiber.
* **Nach der Installation startet das Messprogramm erst zur nächsten
  Anmeldung.** Umstellung auf sofortigen Start über die dabei angelegte Aufgabe.
* **Die Messhilfe ist Fremdcode** (Mozilla Public License 2.0, PawnIO-Bausteine
  unter LGPL 2.1); Lizenztexte und ein `LESEAMICH.md` liegen im Ordner
  `messhilfe`.
* **HWiNFO und das Messprogramm müssen laufen bleiben**, sonst fällt ihre
  Quelle aus; beide haben dafür einen eigenen Autostart. Die mitgebrachte
  Messhilfe nicht — sie lebt mit diesem Programm.
* Die Rust-Fassung ist am Windows-Gerät noch nicht ausprobiert.

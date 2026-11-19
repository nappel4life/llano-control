# Die mitgebrachte Messhilfe

Dieser Ordner gehört zum Programm **llano Control** und enthält Fremdcode. Er
erklärt, was hier fremd ist, woher es kommt und unter welcher Lizenz es steht.

## Was hier drin ist

| Datei | Was das ist | Woher |
|---|---|---|
| `llano-messhilfe.exe` | Ein Hilfsprogramm von 20 Kilobyte: es fragt die Messstellen ab und schreibt sie Zeile für Zeile an das Steuerprogramm weiter | eigener Quelltext in [`packaging/messhilfe/messhilfe.cs`](https://github.com/nappel4life/llano-control/blob/main/packaging/messhilfe/messhilfe.cs) |
| `LibreHardwareMonitorLib.dll` | Die eigentliche Messhilfe: liest die Fühler von Prozessor, Grafikkarte, Mainboard und Arbeitsspeicher | [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor), Fassung 0.9.6 |
| `DiskInfoToolkit.dll`, `HidSharp.dll`, `RAMSPDToolkit-NDD.dll`, `System.*.dll` | Bausteine, die die Messhilfe zum Reden braucht | ebenfalls aus der obigen Veröffentlichung |
| `LICENSE` | Die Lizenz der Messhilfe: **Mozilla Public License 2.0** | dieselbe Veröffentlichung |
| `THIRD-PARTY-NOTICES.txt` | Die Hinweise der Messhilfe auf *ihren* Fremdcode, darunter die **GNU LGPL 2.1** für die PawnIO-Bausteine | dieselbe Veröffentlichung |

Der Quelltext der Messhilfe liegt bei GitHub, und zwar in genau der Fassung,
aus der diese Dateien stammen:
<https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/tree/v0.9.6>

Der Quelltext des Hilfsprogramms liegt im gleichen Repository des
Steuerprogramms, unter derselben Mozilla-Lizenz wie die Messhilfe.

## Was dieser Ordner nicht ist

Kein zweites Programm mit Fenster, Symbolbereich oder eigenem Port. Das
Steuerprogramm startet `llano-messhilfe.exe`, hört ihr zu und beendet sie
wieder. Wenn du das Steuerprogramm schließt, ist auch dieser Helfer weg –
er bleibt absichtlich nicht zurück.

## Die Prozessorfühler

Die Temperaturen eines Prozessors hängen an Registern, die nur ein
Kernel-Treiber lesen darf. Seit der Fassung 0.9.6 ist das der Treiber
**PawnIO** (<https://pawnio.eu/>), und *die Messhilfe legt ihn nicht selbst
dazu*: Ist er auf dem Rechner nicht installiert, meldet die Messhilfe
Grafikkarte und Mainboard, aber keinen Prozessor. Das Steuerprogramm sagt dir
in diesem Fall genau das, statt nur eine leere Liste zu zeigen.

Wer den Treiber haben will, installiert LibreHardwareMonitor (Haken im Setup
„CPU-Temperaturen mitinstallieren“) und beantwortet die eine Sicherheitsabfrage
beim ersten Start dieses Programms. Danach braucht es weder das Fenster noch
den Web-Server.

Wer den Ordner loswerden will: Beim Deinstallieren geht er mit, und ohne ihn
arbeitet das Steuerprogramm wie vorher – Lüfter, Licht und Kurve folgen dann
der Grafikkarte oder einer Windows-Wärmezone.

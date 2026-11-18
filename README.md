# llano-control — llano V12 Ultra Notebookkühler unter Linux und Windows

[![Bau der Dateien](https://github.com/nappel4life/llano-control/actions/workflows/pakete.yml/badge.svg)](https://github.com/nappel4life/llano-control/actions/workflows/pakete.yml)
[![Neueste Dateien](https://img.shields.io/github/v/release/nappel4life/llano-control?label=neueste%20Dateien)](https://github.com/nappel4life/llano-control/releases/latest)

Unter Windows gibt es nur die „MythCool“-Oberfläche. Dieses Programm macht
dasselbe frei und quelloffen: **Lüftergeschwindigkeit in Abhängigkeit von den
Temperaturensoren des Notebooks** und **Farben, Effekte, Takt und Helligkeit
der LEDs** — als Kommandozeile, als Hintergrunddienst und als eigene
Oberfläche mit Taskleisten-Symbol.

Keine Abhängigkeiten ausser PyQt6 für die Oberfläche, kein Dienst als Root.
Fertige Dateien bei jeder Veröffentlichung: `.deb`, AppImage, tragbarer Ordner
und ein Windows-Installationsprogramm, siehe [Einbau](#einbau).

```
./llano status          # was macht der Kühler gerade?
./llano gui             # native Oberfläche mit Taskleisten-Symbol
./llano fan 80          # Lüfter auf 80 %
./llano light --color gruen --effect regenbogen
./llano selftest        # was können Rechner und Kühler zusammen?
```

## Einbau

Fertige Dateien liegen bei jeder
[Veröffentlichung](../../releases "alle Versionen") bereit — die
[neueste](../../releases/latest "neueste Fassung") hat immer diese fünf Stücke.
`<Version>` ist dabei die Zahl im Namen, seit jeher auch die Zahl, die
`llano --version` sagt:

| Datei | für | wie |
| --- | --- | --- |
| `llano-control-<Version>-windows-amd64.exe` | Windows 10 und 11 | ausführen, danach „llano Control“ im Startmenü |
| `llano-control_<Version>_all.deb` | Debian, Ubuntu, Mint | `sudo apt install ./llano-control_<Version>_all.deb` |
| `llano-control-<Version>-x86_64.AppImage` | fast jede Distribution | `chmod +x` und doppelklicken |
| `llano-control-<Version>-linux-x86_64.tar.gz` | Distributionen ohne libfuse2 | entpacken, `./llano-gui` |
| `llano-rs.exe` | Windows, ohne etwas zu installieren | in ein Kommandofenster: `llano-rs status` |

Das `.deb` bringt `llano` nach `/usr/bin` und legt ausser Menüeintrag und
Symbol auch die udev-Regel ins System — nach dem Einstecken gehört der Kühler
dem angemeldeten Benutzer, ohne dass du etwas kopierst. AppImage und der
tragbare Ordner installieren nichts; PyQt6 ist darin schon enthalten.

Das kleine Programm ohne Qt, `llano-rs`, steckt in den meisten Stücken schon
drin: im `.deb` als `/usr/bin/llano-rs`, im tragbaren Ordner als `./llano-rs`,
im Windows-Installer neben `llano.exe`. Die einzelne `.exe` hier ist für
Windows ohne Installation; die AppImage lässt es draussen, weil ein zweites
Programm in einer einzigen Datei schwer zu erreichen ist.

Ohne Paket genügt das Auschecken, der Starter im Ordner läuft sofort:

```bash
git clone https://github.com/nappel4life/llano-control.git
cd llano-control && ./llano status
```

Wer `pip` gewohnt ist: `pip install .`, für die Oberfläche `pip install '.[gui]'`.

Unter Linux ist danach noch die [udev-Regel](#einmalige-einrichtung) nötig,
unter Windows nicht.

## Voraussetzungen

Für Kommandozeile und Hintergrunddienst genügt Python 3.10+. Die Oberfläche
braucht PyQt6:

```bash
sudo pacman -S --needed python-pyqt6     # Arch, CachyOS
sudo apt install python3-pyqt6           # Debian, Ubuntu
```

## Einmalige Einrichtung

Der Kühler ist eine USB-HID-App (`374a:b101`, „HOLTEK USB-HID AP“). Linux legt
dafür `/dev/hidraw2` an, das zunächst nur Root gehört. Diese Regel ändern:

```bash
sudo cp contrib/70-llano.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Danach den USB-Stecker **einmal abziehen und wieder stecken** (udev ändert
bestehende Knoten nicht im laufenden Betrieb). Ob es geklappt hat:

```bash
ls -l /dev/hidraw*            # es sollte eine ACL für deinen Benutzer zeigen
./llano status
```

Greift `uaccess` hier nicht (z. B. ohne Logind), steht in der Regeldatei eine
auskommentierte `MODE="0666"`-Variante als Ersatz.

## Unter Windows

Der Kühler hängt als ganz normale HID-App am Bus, deshalb ist unter Windows
nichts einzurichten: Installer ausführen, Oberfläche starten. Der Gerätezugriff
läuft über `hid.dll` und `setupapi.dll`, also über die Windows-eigenen
Funktionen — es wird nichts installiert ausser dem Programm selbst.

Zwei Unterschiede zu Linux, die man kennen sollte:

* **Temperaturen.** Windows hat kein `hwmon`. Ohne Zusatztreiber gibt es nur
  die **ACPI-Wärmezone** (`MSAcpi_ThermalZoneTemperature`) und — falls
  vorhanden — `nvidia-smi` für die GPU. Eine Wärmezone ist kein Prozessorkern:
  sie reagiert träger, ihr Wert gehört dem Mainboard, und **auf manchen
  Notebooks darf sie nur ein erhöhter Prozess lesen**; dann hilft „Als
  Administrator ausführen“. Was dein Rechner tatsächlich meldet, zeigt
  `llano selftest`, und `llano sensors` listet die ids für die Kurve.
* **Die Hersteller-Software.** MythCool hält das Gerät gelegentlich exklusiv
  belegtt. Wenn „kein Zugriff“ erscheint: MythCool beenden.

Der Windows-Geräteteil ist nach den dokumentierten Aufrufen geschrieben, aber
**noch nicht an einem echten Gerät gemessen** — die Linux-Seite dagegen ist
Zelle für Zelle nachgemessen. Wenn bei dir etwas nicht will, schick die Ausgabe
von `llano selftest` zu den [Issues](../../issues); sie benennt jeden Schritt
einzeln.

Autostart gibt es beim Installer als Haken („Beim Anmelden starten“); er landet
im Run-Schlüssel deines Kontos, nicht als Dienst.

## Oberfläche

```bash
./llano gui              # Fenster + Taskleisten-Symbol
./llano gui --tray       # nur das Symbol, ohne Fenster
./llano gui --minimized  # minimiert
```

Das Fenster zeigt Temperaturen, Lüfterstufe und Kurve live:

* **Automatik / Manuell** — im Automatikmodus hält das Programm die aus der
  Kurve errechnete Stufe, im Manuellmodus setzt der Regler direkt aufs Gerät.
  Geschrieben wird erst beim Loslassen, nicht bei jedem Pixelschritt. Der
  Regler ist wie die Helligkeit ein selbst gemalter Balken: Qt malt hinter
  jedem gestylten Schieberegler seine eigene graue Nut weiter, und die steht
  auch dann noch da, wenn man Rand, Füllung und Griff neu definiert. Zu
  bedienen sind beide mit der Maus, dem Mausrad und den Pfeiltasten (Page hoch
  und runter in größeren Schritten, Pos1 und Ende bis zum Anschlag); im
  Automatikmodus ist er grau und schaut nur zu.
* **Sensoren auswählen** — CPU, GPU, SSD, RAM, Mainboard; maßgeblich ist der
  wärmste der angehakten Sensoren.
* **Lüfterkurve mit der Maus** — Punkte im Diagramm anfassen und ziehen, der
  Wert steht dabei daneben; ein Doppelklick setzt einen Punkt hin, ein
  Rechtsklick entfernt ihn. Unten drunter dieselben Werte als Tabelle, die sich
  auch eintippen lässt. Maßgeblich ist die Temperatur, dazwischen wird linear
  interpoliert, und der aktuelle Temperaturpunkt ist eingezeichnet.
  Gespeichert und auf das Gerät geschrieben wird erst, wenn die Maustaste
  losgeläßt ist — nicht bei jedem einzelnen Pixelzug. „Reaktion“ ist die
  Hysterese: hochgedreht wird sofort, runtergedreht erst, wenn es mehrere Grad
  kühler geworden ist. Für Reaktion und Abstand sitzen Plus und Minus **neben**
  dem Feld; die eingebauten Qt-Pfeile im Feld sind 16 Pixel klein und auf einem
  Notebook kaum zu treffen.
* **Beleuchtung** — die fünf Farben des Kühlers als kleine Kreise, Effekt und
  Takt als Ausklapplisten, die Helligkeit als senkrechter Balken rechts, dazu
  LEDs und Hauptschalter. Fünf Kreise und kein freies Farbfeld, weil das Gerät
  nichts mischt: jedes andere Farbbyte rechnet die Firmware auf eine dieser fünf
  Farben zurück (unten nachgemessen), und auch die Windows-Software bietet genau
  diese fünf an. Die Farben gibt es auch im Taskleisten-Menü.
* **Zwei Knöpfe in zwei Richtungen** — „Auf Kühler speichern" schreibt die
  gespeicherte Beleuchtung noch einmal auf das Gerät, „Vom Kühler laden" nimmt
  das, was der Kühler gerade wirklich zeigt, und macht es zur gespeicherten
  Einstellung. Nützlich nach dem Wiedereinstöpseln, nach Stromlos, oder wenn
  jemand den Kühler von Hand — oder an einem anderen Rechner — umgestellt hat.
  Beide lassen die Lüfterstufe in Ruhe.
* **An und Aus** — zwei Hakfen im Lüfterkasten: beim Start einschalten und beim
  Beenden ausschalten. Beides ist unten genauer beschrieben.

**Taskleisten-Symbol.** Das Symbol färbt sich in der eingestellten LED-Farbe und
zeigt im Tooltip Stufe und Temperatur. Das Menü enthält Modus, feste Stufen,
Farben, Effekte, LEDs an/aus sowie „Fenster zeigen“ und „Beenden“. Linksklick
blendet das Fenster ein oder aus. Beim Schließen des Fensters läuft die
Steuerung im Hintergrund weiter.

## An beim Start, aus beim Herunterfahren

Der Kühler hat einen Hauptschalter, und der bleibt stehen, wie man ihn zuletzt
gesehen hat. Wer das Anlassen nicht jedem selbst überlassen will, schaltet die
beiden Hakfen im Lüfterkasten an:

* **Kühler beim Start einschalten.** Beim Anmelden, und überhaupt jedes Mal,
  wenn die Oberfläche oder der Kopf-Dienst anfängt.
* **Kühler beim Beenden ausschalten.** Beim „Beenden“ im Symbolmenü, bei Strg+C
  im Terminal und — der eigentliche Grund — beim Abmelden und Herunterfahren.
  Beim Sitzungsende schickt die Anmeldung SIGTERM; die Oberfläche fängt das ab,
  fährt sauber herunter und schaltet vorher aus. Auf diesem Rechner sind das
  256 Millisekunden zwischen Signal und ausgeschaltetem Kühler.

Damit das auch gilt, wenn gar keine Oberfläche läuft, schaltet zusätzlich ein
Benutzer-Dienst ein und aus:

```bash
contrib/install-user.sh --power     # Dienst einrichten und sofort einschalten
systemctl --user status llano-power.service
```

Der Dienst wartet beim Start bis zu 25 Sekunden auf den USB-Kühler, weil der
manchmal erst kurz nach der Anmeldung aufgetaucht ist, und tut nichts, wenn
gerade die Oberfläche oder der Kopf-Dienst am Gerät hängt — die kümmern sich
dann selbst darum. Beim Herunterfahren fährt er in umgekehrter Reihenfolge
`power off`. Von Hand:

```bash
./llano power an          # auch: aus, ein, on, off, --on, --off
./llano power an --wait 20
```

Der Prozess, der die Kurve fährt, ist über eine Datei-Sperre der einzige
Besitzer des Geräts; Fenster und Symbol gehören zu diesem Prozess. Deshalb
kämpft nichts gegen nichts — wichtig, weil jedes Licht-Kommando auch die
Lüfterstufe schreibt.

## Autostart und Menüeintrag

```bash
contrib/install-user.sh                      # Menüeintrag + Symbol
contrib/install-user.sh --autostart          # zusätzlich beim Anmelden starten
contrib/install-user.sh --power              # zusätzlich Ein/Aus-Dienst (s.o.)
contrib/install-user.sh --autostart --power  # beides
contrib/install-user.sh --remove             # alles wieder weg
```

Wer stattdessen einen reinen Kopf-Dienst ohne Oberfläche will:

```bash
mkdir -p ~/.config/systemd/user
cp contrib/llano-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now llano-daemon
```

`systemctl --user enable` wirkt erst nach `loginctl enable-linger $USER` oder
wenn die Einheit von Hand gestartet wird. Nicht beides gleichzeitig laufen
lassen — Fenster und Dienst sonst streiten sie um das Gerät; der zweite
bekommt dann die Meldung, dass schon ein llano-Daemon läuft.

Anzeigen, was der Dienst tut, ohne etwas zu schreiben:

```bash
./llano daemon --dry-run
```

## Konfiguration

`~/.config/llano/config.json`, entsteht beim ersten Start:

```json
{
  "mode": "auto",
  "manual_speed": 60,
  "sensors": ["coretemp:Package id 0", "nvidia:GPU"],
  "curve": [[45, 20], [55, 35], [65, 50], [75, 70], [85, 90], [92, 100]],
  "hysteresis": 3.0,
  "poll_seconds": 3.0,
  "write_interval": 5.0,
  "min_speed_step": 2,
  "light": {"on": true, "color": 2, "effect": 0, "speed": 0, "brightness": 255},
  "power_on_start": true,
  "power_off_on_exit": true
}
```

```bash
./llano config --set mode=manual manual_speed=70
./llano config --set 'sensors=["nvidia:GPU"]'
./llano config --set power_off_on_exit=false
./llano sensors                  # welche Sensor-IDs es gibt
./llano curve 60 75 90           # was die Kurve daraus macht
```

Die NVIDIA-Temperatur kommt über `nvidia-smi`, alles andere direkt aus
`/sys/class/hwmon`.

### Wenn die Datei von woanders herkommt

Die Einstellungsdatei überlebt ein Deinstallieren mit Absicht – sie enthält die
Kurve, die sich jemand erarbeitet hat. Damit liegt sie nach einer
Neuinstallation oder nach einem Wechsel von und zur Rust-Fassung immer noch da,
und deshalb darf darin alles Mögliche stehen: fehlende Schlüssel, `null`, Texte
statt Zahlen, ein Modus `"kurve"`. Beim Lesen wird jeder Wert in Form gebracht;
worauf nicht zu bauen war, sagt das Programm dazu, und `llano selftest` nennt,
aus welcher Fassung die Datei stammt und wann sie zuletzt geschrieben wurde.
Beim Deinstallieren unter Windows fragt der Installer nach, ob die Einstellungen
auch weg sollen.

Vor 1.1.5 genügte unter Umständen ein einziger unbrauchbarer Wert, um die
Oberfläche beim Start lautlos sterben zu lassen: Der Kühler war eingeschaltet,
das Fenster kam nie, und weil die Datei das Deinstallieren übersteht, half auch
ein neues Programm nicht.

## Protokoll

Der Kühler meldet eine Vendor-HID-Schnittstelle ohne Report-IDs: ein
Feature-Report mit 8 Bytes trägt **alle** Steuerung und alle Statuswerte, dazu
ein Input- und ein Output-Report mit je 64 Bytes ohne bekannte Funktion. Weil
das Gerät keine Report-IDs hat, hängt der Kernel ein führendes `0x00` an,
gearbeitet wird also mit 9-Byte-Puffern.

| Feld | Bytes | Bedeutung |
|---|---|---|
| Report-ID | 0 | immer `0x00` |
| Befehl | 1 | `0x00` = Licht, `0x01` = Lüfter |
| Lüfter | 2 | 1–100, kein RPM |
| Hauptschalter | 3 | `0x00` = ein |
| Effekt | 4 | 0–4, `>= 0x80` = LEDs aus |
| Farbe | 5 | 0 rot, 1 hellblau, 2 grün, 3 lila, 4 orange |
| Effekttakt | 6 | 0 = am schnellsten, 3 = am langsamsten |
| Helligkeit | 7 | 0–255 |
| Prüfsumme | 8 | `0xFF - Summe(Bytes 1..7)` |

Zwei Dinge sind beim Nachbau leicht falsch zu machen und hier getestet:

1. **Jeder Bericht ist der vollständige Zustand.** Die Bytes 3–6 sind *bei
   beiden* Befehlen die Beleuchtung. Wer beim Lüfter-Kommando feste Werte
   mitschickt — die Windows-Software tut das mit `00 02 00 FF` — überschreibt
   bei jeder Lüfterstufe Farbe, Effekt, Takt und Helligkeit auf
   „durchgehend / grün / 255“. Am Gerät nachgemessen; beide Gegenprojekte
   sagen an dieser Stelle etwas anderes. Deshalb führt jeder Bericht die
   Werte mit, die gerade gelten sollen: `set_fan()` schickt die Beleuchtung,
   `set_light()` die Lüfterstufe (eine `0` an dieser Stelle bleibt stehen).
2. **Lesen braucht eine Anfrage.** Ein nacktes `GET_FEATURE` liefert den
   letzten Anfrage-Bericht zurück, nicht den Zustand. Vor dem Lesen muss der
   Bericht `80 00 00 00 00 00 00 7F` geschrieben werden. Sonst liest man
   Nullen — und wer die als „aktuellen Zustand“ weiterschreibt, setzt den
   Kühler auf dunkel und null Prozent. Die Versionsabfrage (`81 …`)
   beantwortet das Gerät über den Interrupt-IN-Kanal und verstellt dabei den
   Statusbericht; sie ist deshalb nur über `llano status --firmware` erreichbar
   und stellt danach den Statusbericht wieder her.
3. **Das Farbbyte ist eine Nummer, kein Farbton — und es gibt genau fünf.**
   Am Gerät nachgemessen: `5 → rot`, `7 → grün`, `9 → orange`, `42 → grün`,
   `200 → rot`. Die Firmware rechnet selbst den Rest der Division durch fünf,
   jeder Wert wird also auf eine der fünf Farben abgebildet. Ein Feld für
   Rot/Grün/Blau existiert nicht, die Bytes 4–6 sind vollständig verplant
   (Nummer, Takt, Helligkeit): ein Paket `02 09 00 01 FF 00 AA` wurde am Gerät
   als „Farbe 255 → rot, Helligkeit 170" gelesen, der vermeintliche Blauwert war
   die Helligkeit. Auch die Windows-Software schickt für `light_color_mode` nur
   eine Nummer. Freie Farbwahl ist deshalb nicht implementierbar; das Farbrad
   wählt die nächstliegende Stellung. Zum Vergleich in der Windows-Software
   nachgesehen: auch dort sind genau diese fünf Farben wählbar.
4. **Unbekannte Effektnummern werden gemerkt, aber nicht gezeigt.** Auf
   Effekt 5–8 antwortet das Gerät mit der eigenen Nummer (kein Modulo wie beim
   Farbbyte), die LEDs leuchteten dabei aber dauerhaft in der eingestellten
   Farbe ohne Helligkeitsschwankung — sichtbar kein Unterschied zu
   `0 = durchgehend`.
5. **Der Takt hat keine Stufe jenseits von 3, und schon gar keine schnellere.**
   Takt 4, 6 und 8 merkt sich das Gerät wieder als eigene Zahl — schneller wurde
   nichts. Bei `atmend` mit Takt 6 leuchtete der Kühler 30 Sekunden lang
   dauerhaft grün und etwas dunkler, statt zu pulsieren (mitangesehen). Die
   Werte oberhalb von 3 verlassen also das Raster der vier Tempi, statt es nach
   oben zu erweitern.

Die Firmware dieses Geräts meldet sich als `V1626284223`.

Der Lüfterwert ist keine Drehzahl. Anzeigewert des Geräts ist
`300 + runden((roh-1)*25/99)*100` U/min, also roh 1 ≈ 300 und roh 100 ≈ 2800.

Die Prüfsummen- und Rahmenbildung ist gegen echte mitgeschnittene Pakete
getestet (`tests/test_protocol.py`).

## Pakete selbst bauen

Auf GitHub baut die Aktion `Prüfen und Pakete bauen` bei jedem Marken-Tag alle
vier Dateien und legt sie in die Veröffentlichung. Lokal geht dasselbe:

```bash
pip install pyinstaller pyqt6          # oder in einer Leihumgebung
bash packaging/version.sh              # welche Version?
bash packaging/build-deb.sh            # -> out/*.deb        (braucht dpkg-deb)
bash packaging/build-appimage.sh       # -> out/*.AppImage   (holt appimagetool)
bash packaging/build-portable.sh       # -> out/*.tar.gz
```

Für den Windows-Installer brauchst du Windows selbst (Inno Setup 6 und
`pyinstaller --noconfirm --clean packaging/llano.spec`, danach
`ISCC.exe /DVersion=1.1.5 packaging\windows\llano.iss`). Auf einem Linux- oder
Mac-Rechner wird der Installer nur auf GitHub gebaut — der Weg über Wine ist
mit Qt in PyInstaller unzuverlässig, und die Tester sollen ein echtes Windows
sehen.

Die Bau-Vorschrift `packaging/llano.spec` erzeugt in einem Ordner zwei
Programmdateien: `llano` mit Konsole (Kommandozeile) und `llano-control` ohne
Konsole (Oberfläche). Beide teilen sich denselben Satz Bibliotheken, damit
nicht zweimal dasselbe Qt im Paket liegt.

## Tests

```bash
python3 -m unittest discover -s tests
```

Die Oberfläche lässt sich ohne Kühler durchspielen: ein Simulator ersetzt das
Gerät, das Fenster wird gezeichnet und als Bild abgelegt. Geprüft werden Modus,
Stufe, Farben, Effekte, Helligkeit, das Taskleisten-Symbol und die Maus auf der
Kurve — ziehen, Doppelklick, Rechtsklick. Die Konfiguration landet dabei in
einem Behelfsverzeichnis, die eigene `~/.config/llano` bleibt unberührt.

```bash
QT_QPA_PLATFORM=offscreen python3 tools/gui_probe.py /tmp/llano.png
```

Dabei entstehen `/tmp/llano.png` und `/tmp/llano-kurve.png`. So sieht die
Oberfläche aus: `assets/screenshot.png`, beim Ziehen eines Kurvenpunkts
`assets/screenshot-kurve.png`.

Die Prüfsummen- und Rahmenbildung ist gegen mitgeschnittene Pakete getestet,
ausserdem gegen die Reports, die dieses Gerät tatsächlich zurückmeldet.

## Die Rust-Fassung

Unter `rust/` sitzt dasselbe Protokoll noch einmal, von Grund auf: die neun Byte
eines Berichts, der Gerätezugriff über hidraw (Linux) und `HidD_`/`SetupDi_`
(Windows), die Temperaturen aus `/sys/class/hwmon` und von `nvidia-smi`, die
Kurve mit ihrem Verzug beim Herunter und der Hintergrunddienst, der sie
nachfährt. Der Sinn ist nicht Geschwindigkeit, sondern Messtreue — beide
Fassungen müssen dieselben Byte-Folien bauen und gleich lesen, die
`tools/protokoll-vektoren.py` aus dem am Gerät gemessenen Python-Protokoll
erzeugt. Weicht eine Seite ab, scheitert die Prüfung und nicht später der Kühler.

```bash
cd rust && cargo test                  # 69 Pruefungen, inklusive der Byte-Folien
cargo run -- status                    # was macht der Kuehler gerade?
cargo run -- fan 45                    # schreiben, aber erst nachgemessen
cargo run -- rules                     # was der Dienst taet, und warum
cargo run -- daemon                    # die Kurve von selbst nachsehen lassen
```

Das Programm heißt `llano-rs`, wiegt um die 700 Kilobyte und kommt mit: im
Debian-Paket als `/usr/bin/llano-rs`, in der tragbaren Mappe als `./llano-rs`,
im Windows-Installer neben `llano.exe`. Die AppImage enthält es nicht — in einer
einzigen Datei ist ein zweites Programm schwer erreichbar, und wer es braucht,
nimmt die Mappe oder das Paket.

Es liest und schreibt dieselbe Einstellungsdatei wie die Python-Fassung
(`~/.config/llano/config.json`, unter Windows `%APPDATA%`) und hält dieselbe
Sperrdatei: Läuft `llano gui`, nennt `llano-rs` deren Prozessnummer und lässt
die Finger vom Gerät (Rückgabe 3). Was die Rust-Fassung nicht kann, ist das
Fenster — die Oberfläche bleibt in Qt. Der Windows-Gerätezugriff ist gebaut und
typegeprüft, aber noch nie an einem echten Pad probiert; dafür ist der Installer
da. Einzelheiten in [rust/README.md](rust/README.md).

## Verifiziert am Gerät

Farbe, Effekt, Effekttakt, Helligkeit, LEDs aus/an und Lüfterstufen wurden auf
diesem Pad geschrieben und per Statusbericht zurückgelesen; der Daemon hat die
Stufe aus der CPU-Temperatur nachgeregelt. Die Punkte 1 und 2 oben sind dabei
erst aufgefallen — beide Gegenprojekte beschreiben sie anders, was diese
Firmware nicht bestätigt.

## Danksagung und Stand

Der Windows-Installer (`Setup_2.1.80.703.exe`) ist eine Electron-App; die
`.gpk`-Dateien sind umbenannte ASAR-Archive. Aus dem JavaScript stammen die
Befehlsnamen `SetLapFanParam`/`GetLapFanParam` und die Felder `fan_speed`,
`light_mode`, `light_color_mode`, `light_speed`, `light_power`. Das eigentliche
USB-Modul `GPP_USB_Center.exe` liegt nicht im Installer, es wird erst beim
Start heruntergeladen — die Byte-Ebene deshalb aus öffentlich dokumentierten
Gegenprojekten:

* [stiege/llano-v12-linux](https://github.com/stiege/llano-v12-linux)
* [Quahuay/llano-v12ultra-ctrl](https://github.com/Quahuay/llano-v12ultra-ctrl)

Ein eigenständiges Projekt, ohne Verbindung zu llano oder Myth.Cool.

## Lizenz

GNU General Public License v3.0 oder später — siehe [LICENSE](LICENSE). Der
Windows-Installer und die AppImage enthalten PyQt6, das selbst unter GPL steht
und damit gut passt.

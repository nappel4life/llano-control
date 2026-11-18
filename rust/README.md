# Die Rust-Fassung

Ein Unterbau, der das nachbaut, was die Python-Fassung am echten Kühler
gemessen hat: die neun Byte eines Berichts, der Gerätezugriff über hidraw und
die Temperaturen aus `/sys/class/hwmon`.

Geschrieben wird erst, nachdem es an diesem Pad nachgemessen war: Stufe, Farbe,
Effekt, Effekttakt, Helligkeit und Beleuchtung aus/an sind geschrieben und
zurückgelesen. Vor jedem Schreiben hält das Programm dieselbe Sperrdatei wie die
Python-Fassung — läuft `llano gui`, steht dort deren Prozessnummer und das
Gerät wird nicht zweigeteilt.

## Ausprobieren

```bash
cd rust
cargo run -- status        # was macht der Kühler gerade?
cargo run -- sensors       # Temperaturen dieses Rechners
cargo run -- selftest      # kann dieser Rechner den Kühler?
cargo test                 # Prüfungen, inklusive der Byte-Folien

cargo run -- fan 45                        # Stufe setzen
cargo run -- light --farbe gruen --helligkeit 128
cargo run -- power an                      # an, und aus
cargo run -- curve 52 68                   # was die Kurve für diese Temperaturen sagt
cargo run -- rules                         # was der Dienst täte, und warum
cargo run -- config --setzen mode=auto     # in der Einstellungsdatei ändern
cargo run -- daemon                        # die Kurve von selbst nachsehen lassen
cargo run -- daemon --einmal               # nur eine Runde, zum Sehen
```

Das Programm heißt `llano-rs` und passt in 700 Kilobyte. Im Debian-Paket und in
der tragbaren Mappe ist es mit installiert, im Windows-Installer liegt es neben
`llano.exe`. Wer beide Fassungen abwechselnd benutzt, merkt davon nichts: Sie
lesen dieselbe Datei `~/.config/llano/config.json` und halten dieselbe
Sperrdatei, von der eine den anderen höflich abweist (Rückgabe 3, mit der
Prozessnummer des Halters).

## Warum es zwei Fassungen gibt, die sich gegenseitig prüfen

`tests/byte-vektoren.json` entsteht aus dem Python-Protokoll:

```bash
python3 tools/protokoll-vektoren.py
```

`rust/tests/vektoren.rs` muss dieselben Berichte Byte für Byte bauen und sie
genau so lesen. Wer nur die eine Implementierung gegen die andere laufen lässt,
bestätigt höchstens, dass beide denselben Denkfehler haben — hier sitzt die
Messtreue am Gerät in einer Datendatei, und beide Fassungen müssen daran vorbei.

## Stand

| Wozu | Stand |
| --- | --- |
| Protokoll, lesen und schreiben | fertig; Schreiben am Gerät nachgemessen |
| Gerätezugriff Linux | fertig, am Gerät probiert |
| Temperaturen (hwmon und `nvidia-smi`) | fertig, dieselben Schlüssel wie die Python-Fassung |
| Einstellungsdatei | fertig; schreibt zurück, was sie nicht kennt, bleibt stehen |
| Kurve mit Verzug, Hintergrunddienst | fertig; Kurvenwerte und Hysterese-Verläufe als Folien aus der Python-Fassung |
| Windows | gebaut und durch den Seher (`cargo clippy --target x86_64-pc-windows-msvc`); am Gerät hat ihn noch niemand probiert |
| Oberfläche | bleibt in Qt; eine Rust-Oberfläche ist ein eigenes Projekt |

Zwei getrennte Programme sind es trotzdem, mit derselben Datei und denselben
Byte-Folien dahinter. Die Kurve zum Beispiel sitzt einmal in Python und einmal
in Rust, und beide müssen aus 70 °C dasselbe Prozentmaß machen — deshalb liegen
in `tests/byte-vektoren.json` inzwischen auch 29 Kurvenwerte und vier
Hysterese-Verläufe, erzeugt aus der Python-Fassung. Ein feiner Unterschied
dabei: Python rundet eine halbe Zahl zur nächsten geraden Zahl, Rust würde von
der Null weg runden, und bei einer halben Prozentstufe trennen die beiden
sonst genau eine Stufe. Es steht `round_ties_even` im Code, damit das niemand
"korrigiert".

Der Windows-Zugriff ist der einzige Teil, der hier nicht am Gerät war: HidD- und
SetupDi-Aufrufe, spiegelbildlich zu `llanotool/device_windows.py`, mit
Layoutprüfungen für die Detailstruktur (8 Bayt auf 64-Bit, 4 auf 32-Bit). Der
Windows-Bauwagen legt `llano-rs.exe` zum Installer dazu; wer ihn ausprobiert,
findet als Erstes `llano-rs status` und `llano-rs selftest` heraus.

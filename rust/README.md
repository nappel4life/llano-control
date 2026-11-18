# Die Rust-Fassung (in Arbeit)

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
```

## Warum es zwei Fassungen gibt, die sich gegenseitig prüfen

`tests/byte-vektoren.json` entsteht aus dem Python-Protokoll:

```bash
python3 tools/protokoll-vektoren.py
```

`rust/tests/vektoren.rs` muss dieselben Berichte Byte für Byte bauen und sie
genau so lesen. Wer nur die eine Implementierung gegen die andere laufen lässt,
bestätigt höchstens, dass beide denselben Denkfehler haben — hier sitzt die
Messtreue am Gerät in einer Datendatei, und beide Fassungen müssen daran vorbei.

## Was noch fehlt

| Wozu | Stand |
| --- | --- |
| Protokoll, lesen und schreiben | fertig; Schreiben am Gerät nachgemessen |
| Gerätezugriff Linux | fertig, am Gerät probiert |
| Temperaturen (hwmon und `nvidia-smi`) | fertig, dieselben sieben Schlüssel wie die Python-Fassung |
| Kurve, Hintergrunddienst, Konfiguration | fehlt; ohne sie kühlt ein Schreibbefehl nicht von selbst weiter |
| Windows | fehlt; die Python-Fassung hat den Zugriff schon, `llanotool/device_windows.py` zeigt, welche Aufrufe nötig sind |
| Oberfläche | bleibt zuerst in Qt; eine Rust-Oberfläche ist ein eigenes Projekt |

Zwei getrennte Programme sind es trotzdem: Die Rust-Fassung liest die
Konfigurationsdatei der Python-Fassung noch nicht und legt keine Kurve an.
Beide teilen sich aber die Sperrdatei, und beide müssen dieselben Byte-Folien
bauen.

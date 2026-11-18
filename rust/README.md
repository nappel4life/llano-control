# Die Rust-Fassung (in Arbeit)

Ein Unterbau, der das nachbaut, was die Python-Fassung am echten Kühler
gemessen hat: die neun Byte eines Berichts, der Gerätezugriff über hidraw, und
die Temperaturen aus `/sys/class/hwmon`. **Diese Fassung liest nur.**
Schreiben bleibt bei `llano`, bis jeder Schreibweg am Gerät nachgemessen ist —
die Bibliothek kann es bereits, die Kommandozeile bietet es absichtlich nicht an.

## Ausprobieren

```bash
cd rust
cargo run -- status        # was macht der Kühler gerade?
cargo run -- sensors       # Temperaturen dieses Rechners
cargo run -- selftest      # kann dieser Rechner den Kühler?
cargo test                 # Prüfungen, inklusive der Byte-Folien
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
| Protokoll, lesen und schreiben | fertig, gegen die Byte-Folien geprüft |
| Gerätezugriff Linux | fertig, am Gerät probiert |
| Temperaturen (hwmon) | fertig, gleiche Schlüssel wie die Python-Fassung |
| NVIDIA über `nvidia-smi` | fehlt; auf Notebooks mit Optimus fehlt sonst die Grafikkarte |
| Kurve, Hintergrunddienst, Konfiguration | fehlt |
| Windows | fehlt; die Python-Fassung hat den Zugriff schon, `llanotool/device_windows.py` zeigt, welche Aufrufe nötig sind |
| Oberfläche | bleibt zuerst in Qt; eine Rust-Oberfläche ist ein eigenes Projekt |

Bis dahin sind das zwei getrennte Programme, keine zwei Hälften eines: Die
Rust-Fassung liest die Konfigurationsdatei der Python-Fassung noch nicht und
verändert auch sonst nichts am Gerät.

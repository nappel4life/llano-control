//! Freie Steuerung des llano V12 Ultra Notebookkühlers - Rust-Fassung.
//!
//! Diese Fassung ist der Unterbau, der aus der Python-Fassung übernommen
//! wurde, die am Geraet gemessen und mitgeprueft ist:
//!
//! * [`protocol`] - die neun Byte eines Berichts, rein und ohne Ein-/Ausgabe
//! * [`device`]   - ein Vertrag, zwei Backend-Module (Linux gebaut, Windows
//!   folgt), inklusive der Voranfrage, die das Geraet vor jedem Lesen erwartet
//! * [`sensors`]  - Temperaturen aus `/sys/class/hwmon`
//!
//! Schreiben ist seit dem Nachmessen am Geraet freigegeben: Stufe, Farbe,
//! Effekt, Effekttakt, Helligkeit und Beleuchtung aus/an sind auf diesem Pad
//! geschrieben und per Statusbericht zurueckgelesen worden. Jeder Schreibbefehl
//! haelt vorher die [Sperrdatei](lock) der Python-Fassung - wer die Oberflaeche
//! laufen laesst, bekommt deren Prozessnummer in der Meldung und schreibt nicht
//! gegen sie an.
//!
//! Was diese Fassung **noch nicht** kann: die Kurve berechnen, im Hintergrund
//! laufen, die Konfigurationsdatei lesen und Windows. Bis dahin macht das die
//! Python-Fassung; es sind zwei getrennte Programme, nicht zwei Haelfften eines.
//!
//! Die Byte-Ebene wird gegen `tests/byte-vektoren.json` geprueft, dieselben
//! Folien wie die Python-Fassung (`tools/protokoll-vektoren.py`).

pub mod device;
pub mod lock;
pub mod protocol;
pub mod sensors;

#[cfg(target_os = "linux")]
pub mod device_linux;

#[cfg(not(target_os = "linux"))]
pub mod device_other;

/// Die Fassung, die in der Hilfe und in der Selbstpruefung steht.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

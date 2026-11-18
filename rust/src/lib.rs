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
//! Was diese Fassung **noch nicht** kann: schreiben (die Bibliothek kann es,
//! die Kommandozeile bietet es bewusst noch nicht an), die Kurve berechnen, im
//! Hintergrund laufen und die Oberflaeche. Bis dahin macht das die
//! Python-Fassung, und beide lesen dieselbe Konfigurationsdatei nicht - sie
//! sind also zwei getrennte Programme, nicht zwei Haelften eines.
//!
//! Die Byte-Ebene wird gegen `tests/byte-vektoren.json` geprueft, dieselben
//! Folien wie die Python-Fassung (`tools/protokoll-vektoren.py`).

pub mod device;
pub mod protocol;
pub mod sensors;

#[cfg(target_os = "linux")]
pub mod device_linux;

#[cfg(not(target_os = "linux"))]
pub mod device_other;

/// Die Fassung, die in der Hilfe und in der Selbstpruefung steht.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

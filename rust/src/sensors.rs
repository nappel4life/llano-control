//! Temperaturen vom Notebook lesen, ohne Zusatzprogramme.
//!
//! Unter Linux ist die Quelle `/sys/class/hwmon`: Prozessoren (`coretemp`,
//! `k10temp`), NVMe, Chipsatz, WLAN und Grafikkarten bei `amdgpu` und
//! `nouveau`. Das kostet ein paar Dateilesevorgaenge und keine Abhaengigkeit.
//!
//! Eine NVIDIA-Karte fehlt dort oft, weil Optimus-Notebooks sie ueber hwmon
//! gar nicht anzeigen; die Python-Fassung holt sie mit `nvidia-smi` nach. Das
//! steht in dieser Fassung noch aus - die Selbstpruefung sagt es deshalb dazu.
//!
//! Die Schlüssel sind dieselben wie in der Python-Fassung (`Chip:Messstelle`),
//! damit eine gespeicherte Kurve beide Fassungen uebersteht.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

const HWMON: &str = "/sys/class/hwmon";

/// Chips, deren Messstelle keine Temperatur ist, auf die man reagieren will.
const NICHT_INTERESSANT: [&str; 5] = ["ucsi_source_psy", "iwlwifi_1", "r8169", "gpp", "ACAD"];

/// Bezeichnungen, an denen ein Gesamtwert des Prozessors zu erkennen ist.
const GESAMT_WERTE: [&str; 4] = ["package", "tsen", "tctl", "composite"];

fn text(pfad: &Path) -> Option<String> {
    fs::read_to_string(pfad)
        .ok()
        .map(|wert| wert.trim().to_owned())
}

fn nummer(pfad: &Path) -> Option<i64> {
    text(pfad).and_then(|wert| wert.parse::<i64>().ok())
}

fn chip_interessant(name: &str) -> bool {
    !NICHT_INTERESSANT
        .iter()
        .any(|anfang| name.starts_with(anfang))
}

fn hwmon_chips() -> Vec<PathBuf> {
    let mut pfade: Vec<PathBuf> = match fs::read_dir(HWMON) {
        Ok(eintraege) => eintraege
            .filter_map(|eintrag| eintrag.ok())
            .map(|eintrag| eintrag.path())
            .filter(|pfad| {
                pfad.file_name()
                    .is_some_and(|name| name.to_string_lossy().starts_with("hwmon"))
            })
            .collect(),
        Err(_) => return Vec::new(),
    };
    pfade.sort();
    pfade
}

/// Name der Messstelle, so wie die Tabelle sie zeigen soll.
fn messstelle_name(chip: &Path, eingang: &Path) -> String {
    let basis = eingang
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let basis = basis.trim_end_matches("_input");

    if let Some(etikett) = text(&chip.join(format!("{basis}_label"))) {
        if !etikett.is_empty() {
            return etikett;
        }
    }
    let kurzer = basis.trim_start_matches("temp");
    match kurzer {
        "" => "total".to_owned(),
        andere => andere.to_owned(),
    }
}

/// Jede Messstelle als `Chip:Messstelle` in Grad Celsius.
pub fn hwmon_lesen() -> BTreeMap<String, f64> {
    let mut werte = BTreeMap::new();
    for chip in hwmon_chips() {
        let name = text(&chip.join("name")).unwrap_or_else(|| "chip".to_owned());
        if !chip_interessant(&name) {
            continue;
        }
        let mut eingange: Vec<PathBuf> = match fs::read_dir(&chip) {
            Ok(eintraege) => eintraege
                .filter_map(|eintrag| eintrag.ok())
                .map(|eintrag| eintrag.path())
                .filter(|pfad| {
                    pfad.file_name().is_some_and(|name| {
                        let name = name.to_string_lossy();
                        name.starts_with("temp") && name.ends_with("_input")
                    })
                })
                .collect(),
            Err(_) => continue,
        };
        eingange.sort();

        for eingang in eingange {
            let Some(rohwert) = nummer(&eingang) else {
                continue;
            };
            let grad = rohwert as f64 / 1000.0;
            // Null und negativ heisst: hier sitzt nichts.
            if grad <= 0.0 {
                continue;
            }
            let schluessel = format!("{}:{}", name, messstelle_name(&chip, &eingang));
            match werte.get(&schluessel) {
                Some(bekannt) if *bekannt >= grad => {}
                _ => {
                    werte.insert(schluessel, grad);
                }
            }
        }
    }
    werte
}

fn ist_kern_melder(messstelle: &str) -> bool {
    let kleiner = messstelle.to_ascii_lowercase();
    let Some(zahl) = kleiner.strip_prefix("core ") else {
        return false;
    };
    !zahl.is_empty() && zahl.chars().all(|z| z.is_ascii_digit())
}

/// Die Kernwerte eines Prozessors wegwerfen, wenn es auch einen Gesamtwert gibt.
///
/// Ein moderner Prozessor meldet pro Kern eine Zahl und dazu eine fuer das
/// ganze Paket. Fuer eine Lufterkurve ist nur die Paketzahl brauchbar, und
/// vierzig gleiche Zeilen machen die Auswahl unbenutzbar.
pub fn kerne_zusammenfassen(werte: &BTreeMap<String, f64>) -> BTreeMap<String, f64> {
    let chips_mit_gesamt: Vec<&str> = werte
        .keys()
        .filter(|schluessel| {
            let kleiner = schluessel.to_ascii_lowercase();
            GESAMT_WERTE.iter().any(|hinweis| kleiner.contains(hinweis))
        })
        .filter_map(|schluessel| schluessel.split_once(':').map(|(chip, _)| chip))
        .collect();

    werte
        .iter()
        .filter(|(schluessel, _)| match schluessel.split_once(':') {
            Some((chip, messstelle)) => {
                !(chips_mit_gesamt.contains(&chip) && ist_kern_melder(messstelle))
            }
            None => true,
        })
        .map(|(schluessel, grad)| (schluessel.clone(), *grad))
        .collect()
}

/// Alles, was dieser Rechner an Temperaturen weis, in der Reihenfolge, die die
/// Oberflaeche zeigt.
pub fn lesen() -> BTreeMap<String, f64> {
    kerne_zusammenfassen(&hwmon_lesen())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unwichtige_chips_fallen_weg() {
        assert!(!chip_interessant("ucsi_source_psy_handler_0"));
        assert!(!chip_interessant("ACAD"));
        assert!(chip_interessant("coretemp"));
        assert!(chip_interessant("k10temp"));
        assert!(chip_interessant("amdgpu"));
    }

    #[test]
    fn kern_melder_werden_erkannt() {
        assert!(ist_kern_melder("Core 0"));
        assert!(ist_kern_melder("core 17"));
        assert!(!ist_kern_melder("Package id 0"));
        assert!(!ist_kern_melder("edge"));
        assert!(!ist_kern_melder("Core"));
        assert!(!ist_kern_melder("Core x"));
    }

    #[test]
    fn ein_gesamtwert_gnuegt() {
        let mut werte = BTreeMap::new();
        werte.insert("coretemp:Package id 0".to_owned(), 61.0);
        werte.insert("coretemp:Core 0".to_owned(), 58.0);
        werte.insert("coretemp:Core 1".to_owned(), 59.0);
        werte.insert("nvme:Composite".to_owned(), 44.0);
        werte.insert("acpitz:1".to_owned(), 52.0);

        let nachher = kerne_zusammenfassen(&werte);
        assert_eq!(nachher.len(), 3);
        assert!(nachher.contains_key("coretemp:Package id 0"));
        assert!(!nachher.contains_key("coretemp:Core 0"));
        // Ein Chip ohne Gesamtwert behaelt, was er hat.
        assert!(nachher.contains_key("acpitz:1"));
    }

    #[test]
    fn ein_rechner_ohne_hwmon_liefert_nichts_statt_fehler() {
        // Auf einem Bauwagen ohne hwmon darf nichts platschen.
        let werte = hwmon_lesen();
        for (schluessel, grad) in werte {
            assert!(schluessel.contains(':'), "{schluessel}");
            assert!(grad > 0.0, "{schluessel} ist nicht ueber null");
        }
    }
}

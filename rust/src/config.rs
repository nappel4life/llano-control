//! Die Einstellungsdatei: dieselbe Datei, die auch die Python-Fassung liest.
//!
//! Zwei Programme, eine Datei. Wer in der Oberfläche die Kurve verbiegt, erwartet,
//! dass der Dienst beim nächsten Start dasselbe vorfindet - und umgekehrt.
//! Deshalb weicht diese Fassung in nichts ab, was die andere Seite auch täte:
//! derselbe Ort, dieselben Schlüssel, dieselben Standardwerte, dieselbe Nachsicht
//! gegen kaputte Einträge. Geprüft wird beim Lesen, nicht beim Schreiben: Eine
//! Kurve mit Buchstaben darin soll den Lüfter nicht stillstehen lassen, sondern
//! auf die Standardkurve zurückfallen.
//!
//! Die Datei liegt unter `~/.config/llano/config.json` (respektive
//! `XDG_CONFIG_HOME`), unter Windows unter `%APPDATA%\llano`. Mit `LLANO_CONFIG`
//! lässt sie sich umlenken; die Prüfungen machen davon Gebrauch, indem sie den
//! Weg direkt durchgeben statt die Umgebung zu verbiegen.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

/// Der Name, der im Ordner und in der Datei steht.
pub const APP_NAME: &str = "llano";

/// Eine Stelle der Kurve: Grad, Prozent.
pub type Punkt = (f64, u8);

/// Die Beleuchtung, so wie die Datei sie beschreibt.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Beleuchtung {
    /// Aus meint nur das Licht; der Lüfter läuft weiter.
    pub an: bool,
    pub farbe: u8,
    pub effekt: u8,
    /// 0 ist der schnellste Wechsel.
    pub takt: u8,
    pub helligkeit: u8,
}

/// Alles, was man dem Kühler über sein Verhalten sagen kann.
#[derive(Debug, Clone, PartialEq)]
pub struct Einstellungen {
    /// `auto` folgt der Kurve, alles andere hält die manuelle Stufe.
    pub modus: String,
    pub manuelle_stufe: f64,
    /// Die Messstellen, auf die die Kurve hört; die wärmste von ihnen zählt.
    pub messstellen: Vec<String>,
    pub kurve: Vec<Punkt>,
    /// Erst so viel Grad tiefer darf der Lüfter wieder herunter.
    pub hysterese: f64,
    pub poll_sekunden: f64,
    /// Öfter als so viele Sekunden wird das Gerät nicht beschrieben.
    pub schreib_abstand: f64,
    /// Erst ab so viel Prozent Unterschied lohnt ein neuer Bericht.
    pub stufe_mindest_schritt: f64,
    pub licht: Beleuchtung,
    pub beim_start_an: bool,
    pub beim_ende_aus: bool,
}

impl Default for Einstellungen {
    fn default() -> Self {
        // Schlüssel für Schlüssel wie `config.DEFAULTS` in der Python-Fassung.
        Self {
            modus: "auto".to_owned(),
            manuelle_stufe: 60.0,
            messstellen: vec!["coretemp:Package id 0".to_owned(), "nvidia:GPU".to_owned()],
            kurve: standard_kurve(),
            hysterese: 3.0,
            poll_sekunden: 3.0,
            schreib_abstand: 5.0,
            stufe_mindest_schritt: 2.0,
            licht: Beleuchtung {
                an: true,
                farbe: 2,
                effekt: 0,
                takt: 0,
                helligkeit: 255,
            },
            beim_start_an: true,
            beim_ende_aus: true,
        }
    }
}

/// Die Ausweichkurve - auch die, auf die eine unlesbare Kurve fällt.
pub fn standard_kurve() -> Vec<Punkt> {
    vec![
        (45.0, 20),
        (55.0, 35),
        (65.0, 50),
        (75.0, 70),
        (85.0, 90),
        (92.0, 100),
    ]
}

/// Der Ordner, in dem die Datei liegt.
pub fn ordner() -> PathBuf {
    #[cfg(windows)]
    let grund = erstersetzen("APPDATA")
        .or_else(|| erstersetzen("USERPROFILE").map(|basis| basis.join("AppData/Roaming")));
    #[cfg(not(windows))]
    let grund = erstersetzen("XDG_CONFIG_HOME")
        .or_else(|| erstersetzen("HOME").map(|basis| basis.join(".config")));
    grund.unwrap_or_else(|| PathBuf::from(".")).join(APP_NAME)
}

fn erstersetzen(schluessel: &str) -> Option<PathBuf> {
    std::env::var(schluessel)
        .ok()
        .filter(|text| !text.is_empty())
        .map(PathBuf::from)
}

/// Die Datei, wie das Programm sie versteht.
pub fn datei() -> PathBuf {
    erstersetzen("LLANO_CONFIG").unwrap_or_else(|| ordner().join("config.json"))
}

/// Der Inhalt einer Datei, oder die Standardwerte. Der zweite Wert ist der
/// Hinweis, den die Python-Fassung in demselben Fall auf den Bildschirm schreibt.
pub fn laden_pfad(pfad: &Path) -> (Einstellungen, Option<String>) {
    let text = match fs::read_to_string(pfad) {
        Ok(text) => text,
        Err(fehler) if fehler.kind() == io::ErrorKind::NotFound => {
            return (Einstellungen::default(), None)
        }
        Err(fehler) => {
            return (
                Einstellungen::default(),
                Some(format!(
                    "warn: {} ist nicht zu lesen ({fehler}), Standardwerte werden benutzt",
                    pfad.display()
                )),
            )
        }
    };
    match serde_json::from_str::<Value>(&text) {
        Ok(roh) => (aus_werten(&roh), None),
        Err(fehler) => (
            Einstellungen::default(),
            Some(format!(
                "warn: {} ist beschädigt ({fehler}), Standardwerte werden benutzt",
                pfad.display()
            )),
        ),
    }
}

/// Wie [`laden_pfad`], nur mit dem Weg aus [`datei`].
pub fn laden() -> (Einstellungen, Option<String>) {
    laden_pfad(&datei())
}

/// Der rohe Inhalt derselben Datei, damit beim Speichern nichts verloren geht,
/// was diese Fassung nicht kennt.
pub fn roh_pfad(pfad: &Path) -> Option<Value> {
    fs::read_to_string(pfad)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
}

/// Dasselbe aus einem fertigen JSON-Wert; die Prüfungen arbeiten so.
pub fn aus_werten(roh: &Value) -> Einstellungen {
    let standard = Einstellungen::default();
    let feld = |schluessel: &str| roh.get(schluessel);
    let zahl =
        |schluessel: &str, ausweich: f64| feld(schluessel).and_then(dezimal).unwrap_or(ausweich);
    let entschieden = |schluessel: &str, ausweich: bool| {
        feld(schluessel)
            .and_then(Value::as_bool)
            .unwrap_or(ausweich)
    };

    let licht = feld("light").cloned().unwrap_or(Value::Null);
    let licht_feld = |name: &str, ausweich: u8| {
        licht
            .get(name)
            .and_then(ganze_zahl)
            .map_or(ausweich, |wert| wert.clamp(0, 255) as u8)
    };

    let messstellen = match feld("sensors") {
        Some(Value::Array(liste)) if !liste.is_empty() => liste
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_owned)
            .collect(),
        _ => standard.messstellen,
    };

    Einstellungen {
        modus: feld("mode")
            .and_then(Value::as_str)
            .unwrap_or(&standard.modus)
            .to_owned(),
        manuelle_stufe: zahl("manual_speed", standard.manuelle_stufe),
        messstellen,
        kurve: kurve_oder_standard(feld("curve")),
        hysterese: zahl("hysteresis", standard.hysterese),
        poll_sekunden: zahl("poll_seconds", standard.poll_sekunden),
        schreib_abstand: zahl("write_interval", standard.schreib_abstand),
        stufe_mindest_schritt: zahl("min_speed_step", standard.stufe_mindest_schritt),
        licht: Beleuchtung {
            an: licht.get("on").and_then(Value::as_bool).unwrap_or(true),
            farbe: licht_feld("color", standard.licht.farbe),
            effekt: licht_feld("effect", standard.licht.effekt),
            takt: licht_feld("speed", standard.licht.takt),
            helligkeit: licht_feld("brightness", standard.licht.helligkeit),
        },
        beim_start_an: entschieden("power_on_start", standard.beim_start_an),
        beim_ende_aus: entschieden("power_off_on_exit", standard.beim_ende_aus),
    }
}

/// Nur brauchbare Kurvenpunkte, nach Temperatur sortiert - wie `_normalise_curve`
/// der Python-Fassung, inklusive des Rückfalls, wenn gar keiner übrig bleibt.
pub fn kurve_oder_standard(wert: Option<&Value>) -> Vec<Punkt> {
    let liste: &[Value] = match wert {
        Some(Value::Array(liste)) => liste,
        _ => &[],
    };
    let mut punkte: Vec<Punkt> = liste
        .iter()
        .filter_map(|punkt| {
            let stelle = punkt.as_array()?;
            let grad = stelle.first().and_then(dezimal)?;
            let stufe = stelle.get(1).and_then(ganze_zahl)?;
            Some((grad, stufe.clamp(1, 100) as u8))
        })
        .collect();
    punkte.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    if punkte.is_empty() {
        standard_kurve()
    } else {
        punkte
    }
}

/// Die Einstellungen in eine Datei schreiben, ohne sie halb fertig
/// hinterzulassen: erst die Hilfsdatei, dann das Umbenennen innerhalb
/// desselben Ordners. Alles, was dieses Programm nicht kennt, bleibt stehen -
/// die Oberfläche darf Schlüssel haben, die hier niemand liest.
pub fn speichern_pfad(
    neu: &Einstellungen,
    roh: Option<&Value>,
    pfad: &Path,
) -> io::Result<PathBuf> {
    if let Some(vater) = pfad.parent() {
        fs::create_dir_all(vater)?;
    }
    let mut werte = roh
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_else(Map::new);

    werte.insert("mode".to_owned(), Value::String(neu.modus.clone()));
    werte.insert("manual_speed".to_owned(), zahl_wert(neu.manuelle_stufe));
    werte.insert(
        "sensors".to_owned(),
        Value::Array(
            neu.messstellen
                .iter()
                .map(|text| Value::String(text.clone()))
                .collect(),
        ),
    );
    werte.insert(
        "curve".to_owned(),
        Value::Array(
            neu.kurve
                .iter()
                .map(|(grad, stufe)| Value::Array(vec![zahl_wert(*grad), Value::from(*stufe)]))
                .collect(),
        ),
    );
    werte.insert("hysteresis".to_owned(), zahl_wert(neu.hysterese));
    werte.insert("poll_seconds".to_owned(), zahl_wert(neu.poll_sekunden));
    werte.insert("write_interval".to_owned(), zahl_wert(neu.schreib_abstand));
    werte.insert(
        "min_speed_step".to_owned(),
        zahl_wert(neu.stufe_mindest_schritt),
    );

    let mut licht = Map::new();
    licht.insert("on".to_owned(), Value::Bool(neu.licht.an));
    licht.insert("color".to_owned(), Value::from(neu.licht.farbe));
    licht.insert("effect".to_owned(), Value::from(neu.licht.effekt));
    licht.insert("speed".to_owned(), Value::from(neu.licht.takt));
    licht.insert("brightness".to_owned(), Value::from(neu.licht.helligkeit));
    werte.insert("light".to_owned(), Value::Object(licht));

    werte.insert("power_on_start".to_owned(), Value::Bool(neu.beim_start_an));
    werte.insert(
        "power_off_on_exit".to_owned(),
        Value::Bool(neu.beim_ende_aus),
    );

    let text = serde_json::to_string_pretty(&Value::Object(werte))
        .map_err(|fehler| io::Error::new(io::ErrorKind::InvalidData, fehler))?;

    let hilfe = hilfs_datei(pfad.parent());
    fs::write(&hilfe, format!("{text}\n"))?;
    if let Err(fehler) = fs::rename(&hilfe, pfad) {
        let _ = fs::remove_file(&hilfe);
        return Err(fehler);
    }
    Ok(pfad.to_path_buf())
}

/// Wie [`speichern_pfad`], nur mit dem Weg aus [`datei`].
pub fn speichern(neu: &Einstellungen, roh: Option<&Value>) -> io::Result<PathBuf> {
    let pfad = datei();
    speichern_pfad(neu, roh, &pfad)
}

/// Eine Hilfsdatei im selben Ordner, damit das Umbenennen innerhalb eines
/// Dateisystems bleibt und die Datei nie halb zu lesen ist.
fn hilfs_datei(ordner: Option<&Path>) -> PathBuf {
    let grund = ordner.map(PathBuf::from).unwrap_or_else(std::env::temp_dir);
    static NUMMER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let nummer = NUMMER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    grund.join(format!(".cfg-{}-{nummer}.tmp", std::process::id()))
}

/// Eine Zahl als JSON, ohne dass drei Sekunden als `3.0000000000000004` dastehen.
fn zahl_wert(wert: f64) -> Value {
    if wert.fract() == 0.0 && wert.abs() < 9.0e15 {
        Value::from(wert as i64)
    } else {
        serde_json::Number::from_f64(wert).map_or(Value::Null, Value::Number)
    }
}

/// Eine Ganzzahl, auch wenn in der Datei `"20"` steht - die Python-Fassung lässt
/// beides durch (`int(...)` auf einem Text).
fn ganze_zahl(wert: &Value) -> Option<i64> {
    match wert {
        Value::Number(zahl) => zahl.as_f64().map(|wert| wert as i64),
        Value::String(text) => text.trim().parse::<f64>().ok().map(|wert| wert as i64),
        Value::Bool(entschieden) => Some(i64::from(*entschieden)),
        _ => None,
    }
}

/// Dasselbe mit Nachkommastellen.
fn dezimal(wert: &Value) -> Option<f64> {
    match wert {
        Value::Number(zahl) => zahl.as_f64(),
        Value::String(text) => text.trim().parse::<f64>().ok(),
        Value::Bool(entschieden) => Some(f64::from(*entschieden)),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ohne_datei_gelten_die_standardwerte() {
        let standard = Einstellungen::default();
        assert_eq!(standard.modus, "auto");
        assert_eq!(standard.kurve, standard_kurve());
        assert_eq!(standard.licht.farbe, 2);
        assert!(standard.beim_start_an && standard.beim_ende_aus);
        assert_eq!(standard.messstellen.len(), 2);
    }

    #[test]
    fn eine_halbe_einstellungsdatei_wird_ergaenzt() {
        let roh: Value = serde_json::from_str(r#"{"manual_speed": 30}"#).unwrap();
        let settings = aus_werten(&roh);
        assert_eq!(settings.manuelle_stufe, 30.0);
        assert_eq!(settings.modus, "auto");
        assert_eq!(settings.kurve, standard_kurve());
    }

    #[test]
    fn krumme_kurvenpunkte_werden_ausgesiebt() {
        let roh: Value = serde_json::from_str(
            r#"{"curve": [[70, 90], ["buchstabe", 5], [40, 20], [55, 900], [50, null]]}"#,
        )
        .unwrap();
        let settings = aus_werten(&roh);
        assert_eq!(
            settings.kurve,
            vec![(40.0, 20), (55.0, 100), (70.0, 90)],
            "sortiert, begrenzt, unbrauchbares draussen"
        );
    }

    #[test]
    fn eine_leere_kurve_faellt_auf_die_standardkurve_zurueck() {
        for text in ["[]", "null", "[[\"x\", 1]]", "{}"] {
            let roh: Value = serde_json::from_str(text).unwrap();
            assert_eq!(
                kurve_oder_standard(roh.get("curve")),
                standard_kurve(),
                "bei {text}"
            );
        }
    }

    #[test]
    fn zahlen_als_text_gelten_wie_zahlen() {
        let roh: Value =
            serde_json::from_str(r#"{"manual_speed": "45", "curve": [["60", "80"]]}"#).unwrap();
        let settings = aus_werten(&roh);
        assert_eq!(settings.manuelle_stufe, 45.0);
        assert_eq!(settings.kurve, vec![(60.0, 80)]);
    }

    #[test]
    fn eine_kaputte_lichtgruppe_nimmt_die_standardwerte() {
        let roh: Value = serde_json::from_str(r#"{"light": {"on": false, "color": 4}}"#).unwrap();
        let settings = aus_werten(&roh);
        assert!(!settings.licht.an);
        assert_eq!(settings.licht.farbe, 4);
        assert_eq!(settings.licht.helligkeit, 255);
    }

    #[test]
    fn schreiben_und_lesen_passen_sich() {
        let pfad = hilfs_datei(Some(&std::env::temp_dir()));
        let (urspruenglich, warnung) = laden_pfad(&pfad);
        assert!(
            warnung.is_none(),
            "die Datei fehlt, soll aber keine Warnung geben"
        );
        assert_eq!(urspruenglich, Einstellungen::default());

        let settings = Einstellungen {
            modus: "manual".to_owned(),
            manuelle_stufe: 12.0,
            kurve: vec![(40.0, 6), (70.0, 40)],
            licht: Beleuchtung {
                an: false,
                farbe: 0,
                effekt: 3,
                takt: 2,
                helligkeit: 30,
            },
            ..Einstellungen::default()
        };
        speichern_pfad(&settings, None, &pfad).unwrap();
        let (zurueck, warnung) = laden_pfad(&pfad);
        assert!(warnung.is_none());
        assert_eq!(zurueck, settings);
        let _ = fs::remove_file(&pfad);
    }

    #[test]
    fn fremde_schluessel_bleiben_beim_schreiben_stehen() {
        let pfad = hilfs_datei(Some(&std::env::temp_dir()));
        fs::write(&pfad, "{\n  \"mode\": \"manual\",\n  \"fenster_x\": 120\n}").unwrap();
        let roh = roh_pfad(&pfad).expect("die Datei ist lesbar");
        let (mut settings, _) = laden_pfad(&pfad);
        assert_eq!(settings.modus, "manual");
        settings.manuelle_stufe = 12.0;
        speichern_pfad(&settings, Some(&roh), &pfad).unwrap();

        let text = fs::read_to_string(&pfad).unwrap();
        assert!(
            text.contains("fenster_x"),
            "eigener Schlüssel ist weggefallen"
        );
        assert!(text.contains("\"manual_speed\": 12"), "neuer Wert fehlt");
        assert!(text.ends_with('\n'), "die Datei endet ohne Umbruch");
        assert!(
            !text.contains("\"licht\":"),
            "deutscher Schlüssel in eine englische Datei"
        );
        let _ = fs::remove_file(&pfad);
    }

    #[test]
    fn eine_beschadigte_datei_wehrt_sich_nicht() {
        let pfad = hilfs_datei(Some(&std::env::temp_dir()));
        fs::write(&pfad, "{ \"mode\": ").unwrap();
        let (settings, warnung) = laden_pfad(&pfad);
        assert_eq!(settings.kurve, standard_kurve());
        assert!(warnung.is_some_and(|text| text.contains("beschädigt")));
        let _ = fs::remove_file(&pfad);
    }
}

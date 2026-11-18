//! Die Kurve und die Einstellungsdatei gegen dieselben Folien wie die
//! Python-Fassung.
//!
//! Die Datei `tests/byte-vektoren.json` erzeugt
//! `tools/protokoll-vektoren.py` aus der Python-Implementierung, die am echten
//! Kühler läuft. Was hier steht, ist deshalb keine Vermutung, sondern ein
//! Messwert: Wer in einer der beiden Fassungen an Rundung, Hysterese oder
//! Nachlässigkeit gegen kaputte Kurvenpunkte dreht, sieht es hier - und in der
//! Bauautomatik, die die Folien gegenrechnet.

use std::collections::BTreeMap;

use llano_core::config::{self, Einstellungen, Punkt};
use llano_core::curve::Kurvenfolger;
use serde_json::Value;

fn folien() -> Value {
    let text = std::fs::read_to_string(format!(
        "{}/../tests/byte-vektoren.json",
        env!("CARGO_MANIFEST_DIR")
    ))
    .expect("tests/byte-vektoren.json fehlt: tools/protokoll-vektoren.py aufrufen");
    serde_json::from_str(&text).expect("die Folien sind kein JSON")
}

fn punktliste(wert: &Value) -> Vec<Punkt> {
    wert.as_array()
        .expect("eine Kurve ist eine Liste")
        .iter()
        .map(|stelle| {
            let paar = stelle.as_array().expect("ein Punkt ist ein Paar");
            (
                paar[0].as_f64().expect("Grad ist eine Zahl"),
                paar[1].as_i64().expect("Stufe ist eine Zahl") as u8,
            )
        })
        .collect()
}

#[test]
fn jeden_kurvenwert_kennt_auch_die_rust_fassung() {
    let daten = folien();
    let faelle = daten["kurve"]["interpolation"]
        .as_array()
        .expect("Interpolationsfaelle");
    assert!(
        faelle.len() >= 20,
        "zu wenige Kurvenwerte, um etwas zu beweisen: {}",
        faelle.len()
    );
    for fall in faelle {
        let kurve = punktliste(&fall["kurve"]);
        let grad = fall["grad"].as_f64().expect("Grad");
        let erwartet = fall["stufe"].as_i64().expect("Stufe") as u8;
        let bekommen = llano_core::curve::interpolieren(&kurve, grad);
        assert_eq!(
            bekommen,
            Some(erwartet),
            "{} bei {grad} degC: Python sagt {erwartet}, Rust {:?}",
            fall["name"].as_str().unwrap_or("?"),
            bekommen
        );
    }
}

#[test]
fn die_hysterese_verlaeuft_in_beiden_fassungen_gleich() {
    let daten = folien();
    let verlaeufe = daten["kurve"]["verfolgung"].as_array().expect("Verlaeufe");
    assert!(!verlaeufe.is_empty(), "keine einzigen Verlauf getestet");
    for verlauf in verlaeufe {
        let kurve = punktliste(&verlauf["kurve"]);
        let mut folger =
            Kurvenfolger::neu(&kurve, verlauf["hysterese"].as_f64().expect("Hysterese"));
        let messungen: Vec<f64> = verlauf["messungen"]
            .as_array()
            .expect("Messungen")
            .iter()
            .map(|wert| wert.as_f64().expect("eine Messung ist eine Zahl"))
            .collect();
        let bekommen: Vec<u8> = messungen
            .iter()
            .map(|grad| folger.aktualisieren(*grad))
            .collect();
        let erwartet: Vec<u8> = verlauf["stufen"]
            .as_array()
            .expect("Stufen")
            .iter()
            .map(|wert| wert.as_i64().expect("eine Stufe ist eine Zahl") as u8)
            .collect();
        assert_eq!(
            bekommen,
            erwartet,
            "{}: die Folge {} passt nicht",
            verlauf["name"].as_str().unwrap_or("?"),
            messungen
                .iter()
                .map(|grad| grad.to_string())
                .collect::<Vec<String>>()
                .join(", ")
        );
    }
}

#[test]
fn kaputte_kurven_werden_gleich_aussortiert() {
    let daten = folien();
    let faelle = daten["einstellungen"]["kurven_normierung"]
        .as_array()
        .expect("Normierungsfaelle");
    for fall in faelle {
        let erwartet = punktliste(&fall["erwartet"]);
        let roh = fall["roh"].clone();
        let bekommen = config::kurve_oder_standard(Some(&roh));
        let text = |punkte: &[Punkt]| {
            punkte
                .iter()
                .map(|(grad, stufe)| format!("{grad}={stufe}"))
                .collect::<Vec<String>>()
                .join(",")
        };
        assert_eq!(
            text(&bekommen),
            text(&erwartet),
            "{}: Python laesst anderes uebrig als Rust",
            fall["name"].as_str().unwrap_or("?")
        );
    }
}

#[test]
fn die_standardwerte_sind_dieselben() {
    let daten = folien();
    let standard = Einstellungen::default();
    assert_eq!(
        standard.kurve,
        punktliste(&daten["einstellungen"]["standardwerte"]),
        "die Ausweichkurve unterscheidet sich"
    );

    let roh = daten["einstellungen"]["standardwerte"].clone();
    assert!(config::kurve_oder_standard(Some(&roh)) == standard.kurve);
}

#[test]
fn was_gespeichert_wird_steht_auch_in_der_datei() {
    // Die Python-Fassung kennt genau diese Schluessel. Wer in einer Fassung
    // einen neuen Schluessel erfindet, muss die andere mitnehmen - sonst
    // schreibt die eine Seite der anderen etwas vor, das sie nie liest.
    let daten = folien();
    let soll: Vec<String> = daten["einstellungen"]["schluessel"]
        .as_array()
        .expect("Schluessel")
        .iter()
        .map(|wert| wert.as_str().expect("ein Schluessel ist Text").to_owned())
        .collect();

    let pfad = std::env::temp_dir().join(format!(
        "llano-schluessel-{}-{}",
        std::process::id(),
        std::time::UNIX_EPOCH
            .elapsed()
            .map(|frist| frist.subsec_nanos())
            .unwrap_or(0)
    ));
    config::speichern_pfad(&Einstellungen::default(), None, &pfad).expect("schreiben klappt");
    let text = std::fs::read_to_string(&pfad).expect("lesen klappt");
    let geschrieben: BTreeMap<String, Value> =
        serde_json::from_str(&text).expect("die Datei ist JSON");
    let _ = std::fs::remove_file(&pfad);

    let ist: Vec<String> = geschrieben.keys().cloned().collect();
    assert_eq!(
        ist,
        {
            let mut sortiert = soll.clone();
            sortiert.sort();
            sortiert
        },
        "die Einstellungsdatei weicht von der der Python-Fassung ab"
    );
}

#[test]
fn eine_leere_datei_ergibt_die_standardwerte() {
    let pfad = std::env::temp_dir().join(format!("llano-leer-{}", std::process::id()));
    let (settings, warnung) = config::laden_pfad(&pfad);
    assert!(
        warnung.is_none(),
        "eine fehlende Datei ist kein Grund zur Warnung"
    );
    assert_eq!(settings, Einstellungen::default());
    assert_eq!(settings.licht.helligkeit, 255);
    assert!(settings.licht.an);
}

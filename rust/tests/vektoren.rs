//! Die Byte-Folien, gemessen an der Python-Fassung, die am Kuehler hing.
//!
//! Diese Pruefungen sind der Grund, warum es ueberhaupt zwei Fassungen geben
//! darf: `tests/byte-vektoren.json` entsteht aus dem Python-Protokoll
//! (`tools/protokoll-vektoren.py`), und hier muss die Rust-Fassung dieselben
//! Berichte Byte fuer Byte bauen und sie gleich lesen. Weicht eine Seite ab,
//! scheitert diese Datei - nicht spaeter das Geraet.

use std::fs;
use std::path::PathBuf;

use llano_core::protocol::{self, Lighting, State, BUFFER_LEN};
use serde_json::Value;

fn daten() -> Value {
    let pfad = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("der Quellbaum liegt in rust/")
        .join("tests/byte-vektoren.json");
    let text = fs::read_to_string(&pfad)
        .unwrap_or_else(|fehler| panic!("{} lesen: {fehler}", pfad.display()));
    serde_json::from_str(&text).expect("die Byte-Folien sind kein brauchbares JSON")
}

fn hex(wort: &str) -> Vec<u8> {
    wort.split_whitespace()
        .map(|teil| u8::from_str_radix(teil, 16).unwrap_or_else(|_| panic!("kein Byte: {teil}")))
        .collect()
}

fn als_puffer(wert: &[u8]) -> [u8; BUFFER_LEN] {
    wert.try_into()
        .unwrap_or_else(|_| panic!("Bericht muss {BUFFER_LEN} Byte haben, waren {}", wert.len()))
}

/// Werte, wie die JSON-Datei sie nennt; fehlt etwas, gilt der Protokollstandard.
fn zahl(fall: &Value, name: &str, standard: u8) -> u8 {
    match &fall[name] {
        Value::Number(zahl) => zahl.as_u64().unwrap_or(standard as u64) as u8,
        Value::Null => standard,
        anderes => panic!("{name}: unerwarteter Wert {anderes}"),
    }
}

fn wahr(fall: &Value, name: &str, standard: bool) -> bool {
    match &fall[name] {
        Value::Bool(wert) => *wert,
        Value::Null => standard,
        anderes => panic!("{name}: unerwarteter Wert {anderes}"),
    }
}

fn licht_aus(fall: &Value) -> Lighting {
    Lighting {
        color: zahl(fall, "color", 0),
        effect: zahl(fall, "effect", 0),
        effect_speed: zahl(fall, "effect_speed", 0),
        brightness: zahl(fall, "brightness", 0xFF),
        light_on: wahr(fall, "light_on", true),
    }
}

#[test]
fn protokoll_angaben_stimmen() {
    let daten = daten();
    let protokoll = &daten["protokoll"];
    assert_eq!(
        protokoll["vendor_id"].as_u64().unwrap() as u16,
        protocol::VENDOR_ID
    );
    assert_eq!(
        protokoll["product_id"].as_u64().unwrap() as u16,
        protocol::PRODUCT_ID
    );
    assert_eq!(
        protokoll["koerper_laenge"].as_u64().unwrap() as usize,
        protocol::BODY_LEN
    );
    assert_eq!(
        protokoll["puffer_laenge"].as_u64().unwrap() as usize,
        protocol::BUFFER_LEN
    );
    assert_eq!(
        protokoll["befehl_luefter"].as_u64().unwrap() as u8,
        protocol::CMD_FAN
    );
    assert_eq!(
        protokoll["befehl_beleuchtung"].as_u64().unwrap() as u8,
        protocol::CMD_LIGHT
    );
    assert_eq!(
        protokoll["effekt_aus_flag"].as_u64().unwrap() as u8,
        protocol::LIGHT_OFF_FLAG
    );
}

#[test]
fn summen_passen() {
    let daten = daten();
    for fall in daten["pruefsummen"].as_array().unwrap() {
        let koerper = hex(fall["koerper"].as_str().unwrap());
        let erwartet = fall["summe"].as_str().unwrap();
        let gefunden = protocol::checksum(&koerper).expect("sieben Byte sind ein Korper");
        assert_eq!(
            format!("{gefunden:02x}"),
            erwartet,
            "Summe zu {}",
            fall["koerper"].as_str().unwrap()
        );
    }
}

#[test]
fn geschriebene_berichte_sind_dieselben_byte() {
    let daten = daten();
    let faelle = daten["schreiben"].as_array().unwrap();
    assert!(!faelle.is_empty(), "die Folien datei ist leer");
    for fall in faelle {
        let name = fall["name"].as_str().unwrap();
        let befehl = fall["befehl"].as_str().unwrap();
        let parameter = &fall["parameter"];
        let erwartet = fall["bytes"].as_str().unwrap();

        let bericht = match befehl {
            "luefter" => protocol::build_fan_report(
                zahl(parameter, "speed", 1) as f64,
                wahr(parameter, "powered_on", true),
                &licht_aus(parameter),
            ),
            "beleuchtung" => protocol::build_light_report(
                zahl(parameter, "fan_speed", 0),
                wahr(parameter, "powered_on", true),
                &licht_aus(parameter),
            ),
            anderes => panic!("unbekannter Befehl {anderes} in {name}"),
        };
        let gefunden: Vec<String> = bericht.iter().map(|byte| format!("{byte:02x}")).collect();
        assert_eq!(gefunden.join(" "), erwartet, "Bericht {name}");
    }
}

#[test]
fn gelesene_berichte_sind_gleich_verstanden() {
    let daten = daten();
    for fall in daten["lesen"].as_array().unwrap() {
        let name = fall["name"].as_str().unwrap();
        let roh = hex(fall["bytes"].as_str().unwrap());
        let zustand = State::parse(&roh).unwrap_or_else(|fehler| panic!("{name}: {fehler}"));
        let soll = &fall["zustand"];

        assert_eq!(zustand.mode, zahl(soll, "mode", 0), "Modus von {name}");
        assert_eq!(
            zustand.fan_speed,
            zahl(soll, "fan_speed", 0),
            "Stufe von {name}"
        );
        assert_eq!(
            zustand.rpm_display(),
            soll["rpm_anzeige"].as_u64().unwrap() as u16,
            "Anzeigedrehzahl von {name}"
        );
        assert_eq!(
            zustand.powered_on,
            wahr(soll, "powered_on", true),
            "An/Aus von {name}"
        );
        assert_eq!(
            zustand.light_on,
            wahr(soll, "light_on", true),
            "Licht an von {name}"
        );
        assert_eq!(zustand.effect, zahl(soll, "effect", 0), "Effekt von {name}");
        assert_eq!(zustand.color, zahl(soll, "color", 0), "Farbe von {name}");
        assert_eq!(
            zustand.effect_speed,
            zahl(soll, "effect_speed", 0),
            "Effekttakt von {name}"
        );
        assert_eq!(
            zustand.brightness,
            zahl(soll, "brightness", 0),
            "Helligkeit von {name}"
        );
        assert_eq!(
            zustand.color_name(),
            soll["color_name"].as_str().unwrap(),
            "Farbname"
        );
        assert_eq!(
            zustand.effect_name(),
            soll["effect_name"].as_str().unwrap(),
            "Effektname"
        );
    }
}

#[test]
fn kaputte_berichte_werden_abgewiesen() {
    let daten = daten();
    for fall in daten["zurueckweisen"].as_array().unwrap() {
        let name = fall["name"].as_str().unwrap();
        let grund = fall["grund"].as_str().unwrap();
        let roh = hex(fall["bytes"].as_str().unwrap());
        let ergebnis = State::parse(&roh);
        assert!(ergebnis.is_err(), "{name} wurde durchgewinkt");
        let meldung = ergebnis.unwrap_err().to_string();
        match grund {
            "zu kurz" => assert!(meldung.contains("Byte"), "{name}: {meldung}"),
            "pruefsumme" => assert!(meldung.contains("Summe"), "{name}: {meldung}"),
            anderes => panic!("unbekannter Grund {anderes} in {name}"),
        }
    }
}

#[test]
fn runder_und_begrenzen_wie_die_python_fassung() {
    // Die Kurve rechnet mit gebrochenen Stufen; beide Fassungen muessen auf
    // derselben Stufe landen.
    for (wert, erwartet) in [
        (-5.0, 1u8),
        (0.0, 1),
        (0.4, 1),
        (12.49, 12),
        (12.5, 13),
        (99.6, 100),
        (500.0, 100),
    ] {
        assert_eq!(protocol::clamp_fan(wert), erwartet, "Stufe {wert}");
    }
}

#[test]
fn ein_bericht_ist_neun_byte_lang() {
    let bericht = protocol::build_fan_report(50.0, true, &Lighting::default());
    assert_eq!(bericht.len(), BUFFER_LEN);
    assert_eq!(bericht[0], 0x00, "ohne Berichtskennung geht nichts");
    assert_eq!(als_puffer(&bericht), bericht);
}

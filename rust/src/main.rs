//! Kommandozeile der Rust-Fassung.
//!
//! Kann dasselbe wie die Python-Fassung auf der Kommandozeile: lesen, Stufe,
//! Beleuchtung, Kurve, Dienst. Beide Fassungen teilen sich Einstellungsdatei
//! und Sperrdatei, weil das Geraet keine zweite Steuerung vertragt - wer als
//! zweiter will, bekommt die Meldung mit der Nummer des anderen Prozesses.

use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::process::ExitCode;

use llano_core::config::{self, Einstellungen};
use llano_core::controller::Steuerung;
use llano_core::curve;
use llano_core::device::{self, Pad};
use llano_core::protocol::{self, Lighting};
use llano_core::sensors;
use llano_core::VERSION;

const HILFE: &str = "\
llano-rs - llano V12 Ultra Notebookkuehler (Rust-Fassung)

  llano-rs status [--node PFAD]   was macht der Kuehler gerade
  llano-rs sensors                Temperaturen, die dieser Rechner meldet
  llano-rs selftest               kann dieser Rechner den Kuehler

  llano-rs fan 45                 Stufe setzen
  llano-rs light --farbe gruen --effekt atmend --helligkeit 128
                                  Farbe, Effekt, Takt (0-3) und Helligkeit (0-255)
                                  --an / --off fuer die LEDs

  llano-rs power an                 Kuehler an oder aus
  llano-rs curve 52 68              was die Kurve fuer diese Temperaturen sagt
  llano-rs rules                    was der Dienst tun wuerde, und warum
  llano-rs daemon [--einmal]        die Kurve von selbst nachsehen lassen
  llano-rs config [schluessel] [--setzen key=wert ...]

  llano-rs version                Fassung dieser Datei

Schreiben bekommt die Sperrdatei der laufenden Oberflaeche: Wer `llano gui`
laufen laesst, steuert besser ueber sie. Kurve, Dienst und Windows fehlen in
dieser Fassung noch - die Python-Fassung kann sie.
";

/// Der Hauptschalter des Kuehlers.
fn strom_setzen(wort: &str, knoten: Option<&PathBuf>) -> ExitCode {
    let an = match wort.trim().to_lowercase().as_str() {
        "an" | "ein" | "on" | "1" | "true" => true,
        "aus" | "off" | "0" | "false" => false,
        _ => {
            println!("`{wort}` ist weder an noch aus. Gemeint ist: llano-rs power an");
            return ExitCode::from(2);
        }
    };
    let mut steuerung = steuerungsbereit(knoten);
    if steuerung.strom(an, false) {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

/// Eine Steuerung mit den Einstellungen aus der Datei.
fn steuerungsbereit(knoten: Option<&PathBuf>) -> Steuerung {
    let (einstellungen, warnung) = config::laden();
    if let Some(meldung) = warnung {
        println!("{meldung}");
    }
    let mut steuerung = Steuerung::neu(einstellungen);
    steuerung.knoten_wunsch = knoten.cloned();
    steuerung
}

/// Die Kurve, und auf Wunsch die Stufe zu ein paar Temperaturen.
fn kurve_zeigen(argumente: &[String]) -> ExitCode {
    let (einstellungen, warnung) = config::laden();
    if let Some(meldung) = warnung {
        println!("{meldung}");
    }
    println!(
        "Kurve aus der Einstellungsdatei, Hysterese {} Grad:",
        einstellungen.hysterese
    );
    for (grad, stufe) in &einstellungen.kurve {
        println!("  {grad:>5.1} degC -> {stufe:>3} %");
    }
    let grade: Vec<f64> = argumente
        .iter()
        .filter_map(|wort| wort.replace(',', ".").parse::<f64>().ok())
        .collect();
    if grade.is_empty() {
        println!("\nTemperaturen dazu ergeben die Stufe: llano-rs curve 52 68");
        return ExitCode::SUCCESS;
    }
    println!();
    for grad in grade {
        let stufe = curve::interpolieren(&einstellungen.kurve, grad).unwrap_or(1);
        println!("  {grad:>5.1} degC -> {stufe:>3} %");
    }
    ExitCode::SUCCESS
}

/// Was der Kuehler als Dienst tun wuerde, und warum.
fn regeln_zeigen() -> ExitCode {
    let (einstellungen, warnung) = config::laden();
    if let Some(meldung) = warnung {
        println!("{meldung}");
    }
    println!("Einstellungsdatei: {}", config::datei().display());
    if einstellungen.modus == "auto" {
        println!("Modus        : Kurve");
        println!(
            "Messstellen  : {}",
            if einstellungen.messstellen.is_empty() {
                "keine eingestellt, die waermste Messung zaehlt".to_owned()
            } else {
                einstellungen.messstellen.join(", ")
            }
        );
        println!("Hysterese    : {} Grad", einstellungen.hysterese);
        println!(
            "Kurve        : {}",
            einstellungen
                .kurve
                .iter()
                .map(|(grad, stufe)| format!("{grad:.0}={stufe}"))
                .collect::<Vec<String>>()
                .join("  ")
        );
    } else {
        println!(
            "Modus        : manuell, Stufe {}",
            einstellungen.manuelle_stufe
        );
    }
    println!(
        "Schreiben    : fruehestens alle {:.1} s und ab {:.0} % Unterschied",
        einstellungen.schreib_abstand, einstellungen.stufe_mindest_schritt
    );
    println!(
        "Licht        : {}, Farbe {}, Effekt {}, Takt {}, Helligkeit {}",
        if einstellungen.licht.an { "an" } else { "aus" },
        einstellungen.licht.farbe,
        einstellungen.licht.effekt,
        einstellungen.licht.takt,
        einstellungen.licht.helligkeit
    );
    println!(
        "Schalten     : beim Start an, beim Ende {}",
        if einstellungen.beim_ende_aus {
            "aus"
        } else {
            "an"
        }
    );
    println!("Nachlesen    : alle {:.1} s", einstellungen.poll_sekunden);
    ExitCode::SUCCESS
}

/// Die Datei zeigen, und mit `--set` auch aendern.
fn einstellungen(argumente: &[String]) -> ExitCode {
    let pfad = config::datei();
    let roh = config::roh_pfad(&pfad);
    let (mut settings, warnung) = config::laden();
    if let Some(meldung) = warnung {
        println!("{meldung}");
    }

    let nur_ein_feld = argumente
        .first()
        .filter(|wort| !wort.starts_with('-'))
        .map(String::as_str);

    let setzungen: Vec<&String> = argumente
        .iter()
        .skip_while(|wort| *wort != "--set" && *wort != "--setzen")
        .skip(1)
        .collect();

    if !setzungen.is_empty() {
        for paar in setzungen {
            if let Some(meldung) = anwenden(paar, &mut settings) {
                println!("{meldung}");
                return ExitCode::from(2);
            }
        }
        match config::speichern(&settings, roh.as_ref()) {
            Ok(pfad) => println!("Gespeichert: {}", pfad.display()),
            Err(fehler) => {
                println!("Speichern: {fehler}");
                return ExitCode::from(1);
            }
        }
    }

    let text = serde_json::to_string_pretty(&einstellungen_json(&settings))
        .unwrap_or_else(|_| "{}".to_owned());
    match nur_ein_feld {
        Some(feld) => {
            let wert = einstellungen_json(&settings).get(feld).cloned();
            match wert {
                Some(wert) => println!(
                    "{}",
                    serde_json::to_string_pretty(&wert).unwrap_or_else(|_| "null".to_owned())
                ),
                None => {
                    println!("Diesen Schluessel kennt die Datei nicht: {feld}");
                    return ExitCode::from(2);
                }
            }
        }
        None => println!("{text}"),
    }
    ExitCode::SUCCESS
}

/// Ein `schluessel=wert` aus `config --set`.
fn anwenden(paar: &str, settings: &mut Einstellungen) -> Option<String> {
    let (schluessel, wert) = paar.split_once('=')?;
    let text = wert.trim();
    let zahl = |was: &str| {
        text.replace(',', ".").parse::<f64>().ok().map_or_else(
            || format!("{was} braucht eine Zahl, nicht `{text}`"),
            |_| String::new(),
        )
    };
    match schluessel.trim() {
        "mode" | "modus" => settings.modus = text.to_owned(),
        "manual_speed" => {
            let fehler = zahl("Die manuelle Stufe");
            if !fehler.is_empty() {
                return Some(fehler);
            }
            settings.manuelle_stufe = text.replace(',', ".").parse().unwrap_or(60.0);
        }
        "hysterese" | "hysteresis" => {
            let fehler = zahl("Die Hysterese");
            if !fehler.is_empty() {
                return Some(fehler);
            }
            settings.hysterese = text.replace(',', ".").parse().unwrap_or(3.0);
        }
        "poll_seconds" => {
            let fehler = zahl("Die Pause");
            if !fehler.is_empty() {
                return Some(fehler);
            }
            settings.poll_sekunden = text.replace(',', ".").parse().unwrap_or(3.0);
        }
        "write_interval" => {
            let fehler = zahl("Der Schreibabstand");
            if !fehler.is_empty() {
                return Some(fehler);
            }
            settings.schreib_abstand = text.replace(',', ".").parse().unwrap_or(5.0);
        }
        "min_speed_step" => {
            let fehler = zahl("Der Mindestschritt");
            if !fehler.is_empty() {
                return Some(fehler);
            }
            settings.stufe_mindest_schritt = text.replace(',', ".").parse().unwrap_or(2.0);
        }
        "sensors" => {
            settings.messstellen = text
                .split(',')
                .map(str::trim)
                .filter(|name| !name.is_empty())
                .map(str::to_owned)
                .collect()
        }
        "power_on_start" => settings.beim_start_an = entscheid(text),
        "power_off_on_exit" => settings.beim_ende_aus = entscheid(text),
        "light.color" => settings.licht.farbe = begrenzt(text, 4)?,
        "light.effect" => settings.licht.effekt = begrenzt(text, 4)?,
        "light.speed" => settings.licht.takt = begrenzt(text, 3)?,
        "light.brightness" => settings.licht.helligkeit = begrenzt(text, 255)?,
        "light.on" => settings.licht.an = entscheid(text),
        "curve" => {
            let punkte = kurve_aus_text(text);
            if punkte.is_empty() {
                return Some(
                    "Eine Kurve ist `40=10,60=40,80=90` - Grad gleich Prozent, durch Komma."
                        .to_owned(),
                );
            }
            settings.kurve = punkte;
        }
        anderes => return Some(format!("Diesen Schluessel kenne ich nicht: {anderes}")),
    }
    None
}

/// Ja oder nein, so wie die Kommandozeile es annimmt.
fn entscheid(text: &str) -> bool {
    !matches!(
        text.trim().to_lowercase().as_str(),
        "0" | "aus" | "off" | "nein" | "false" | "no"
    )
}

/// Eine kleine Ganze Zahl mit Grenze.
fn begrenzt(text: &str, grenze: u8) -> Option<u8> {
    text.trim()
        .parse::<u8>()
        .ok()
        .map(|wert| wert.min(grenze))
        .or_else(|| protocol::color_value(text).or_else(|| protocol::effect_value(text)))
}

/// `40=10,60=40` als Kurve.
fn kurve_aus_text(text: &str) -> Vec<config::Punkt> {
    text.split(',')
        .filter_map(|punkt| {
            let (grad, stufe) = punkt.split_once('=')?;
            let grad = grad.trim().replace(',', ".").parse::<f64>().ok()?;
            let stufe = stufe.trim().parse::<i64>().ok()?.clamp(1, 100) as u8;
            Some((grad, stufe))
        })
        .collect()
}

/// Die Einstellungen als JSON, so wie `llano config` es ausgiebt.
fn einstellungen_json(settings: &Einstellungen) -> serde_json::Value {
    let mut licht = serde_json::Map::new();
    licht.insert("on".to_owned(), serde_json::json!(settings.licht.an));
    licht.insert("color".to_owned(), serde_json::json!(settings.licht.farbe));
    licht.insert(
        "effect".to_owned(),
        serde_json::json!(settings.licht.effekt),
    );
    licht.insert("speed".to_owned(), serde_json::json!(settings.licht.takt));
    licht.insert(
        "brightness".to_owned(),
        serde_json::json!(settings.licht.helligkeit),
    );
    serde_json::json!({
        "mode": settings.modus,
        "manual_speed": settings.manuelle_stufe,
        "sensors": settings.messstellen,
        "curve": settings.kurve.iter().map(|(grad, stufe)| serde_json::json!([grad, stufe])).collect::<Vec<_>>(),
        "hysteresis": settings.hysterese,
        "poll_seconds": settings.poll_sekunden,
        "write_interval": settings.schreib_abstand,
        "min_speed_step": settings.stufe_mindest_schritt,
        "light": licht,
        "power_on_start": settings.beim_start_an,
        "power_off_on_exit": settings.beim_ende_aus,
    })
}

/// Der Hintergrunddienst: eine Kurve, die von selbst nachsieht.
fn dienst(knoten: Option<&PathBuf>, argumente: &[String]) -> ExitCode {
    let einmal = argumente
        .iter()
        .any(|wort| wort == "--einmal" || wort == "--once");
    let sperre = match llano_core::lock::erwerben() {
        Ok(sperre) => sperre,
        Err(belegt) => {
            println!("{belegt}");
            return ExitCode::from(3);
        }
    };
    let mut steuerung = steuerungsbereit(knoten);
    if einstellungswarnung(&steuerung) {
        return ExitCode::from(1);
    }

    if einmal {
        let umlauf = steuerung.umlauf();
        meldung_umlauf(&umlauf);
        return if umlauf.verbunden {
            ExitCode::SUCCESS
        } else {
            ExitCode::from(1)
        };
    }

    llano_core::signale::hoeren();
    println!(
        "llano-rs {VERSION} als Dienst; Kurve aus {}, Ende mit Strg+C",
        config::datei().display()
    );
    // Eine Zeile pro Umlauf waeren 17 000 Zeilen am Tag. Gezeigt wird also nur,
    // was sich anders darstellt als in der letzten Runde.
    let zuletzt = std::cell::RefCell::new((false, None::<u8>, false));
    steuerung.laufen(&sperre, &weiter_sollen, &|umlauf| {
        let stand = (umlauf.verbunden, umlauf.ziel, umlauf.bericht.is_some());
        if *zuletzt.borrow() != stand {
            *zuletzt.borrow_mut() = stand;
            meldung_umlauf(umlauf);
        }
    });
    ExitCode::SUCCESS
}

/// Der Dienst arbeitet weiter, solange niemand beendet haben will.
fn weiter_sollen() -> bool {
    !llano_core::signale::beendet()
}

/// Eine Meldung, wenn die Datei nicht zu lesen war.
fn einstellungswarnung(steuerung: &Steuerung) -> bool {
    let (_, warnung) = steuerung.stand_der_datei();
    if let Some(meldung) = warnung {
        println!("{meldung}");
    }
    false
}

/// Eine Zeile pro Umlauf - kurz gehalten, weil der Dienst tagealt werden soll.
fn meldung_umlauf(umlauf: &llano_core::controller::Umlauf) {
    let bezug = umlauf.bezug.map_or_else(
        || "keine Messung".to_owned(),
        |grad| format!("{grad:.1} degC"),
    );
    let ziel = umlauf
        .ziel
        .map_or_else(|| "?".to_owned(), |stufe| format!("{stufe} %"));
    println!(
        "{}  Bezug {bezug}  Ziel {ziel}  Geraet {}",
        if umlauf.verbunden {
            "verbunden"
        } else {
            "kein Geraet"
        },
        umlauf.bericht.as_ref().map_or_else(
            || "ohne Rueckmeldung".to_owned(),
            |bericht| format!(
                "{} % {}, {}",
                bericht.fan_speed,
                if bericht.powered_on { "an" } else { "aus" },
                bericht.color_name()
            )
        )
    );
}

/// Die Argumente ohne den Knaetchenpfad und sein Schalterwort.
fn ohne_knoten(argumente: &[String]) -> Vec<String> {
    let mut uebrig = Vec::new();
    let mut stelle = 1;
    while stelle < argumente.len() {
        if argumente[stelle] == "--node" || argumente[stelle] == "-n" {
            stelle += 2; // das Schalterwort und sein Wert
            continue;
        }
        uebrig.push(argumente[stelle].clone());
        stelle += 1;
    }
    uebrig
}

/// Der Knaetchenpfad, mit dem eine Anweisung arbeiten soll, falls genannt.
fn gewuenschter_knoten(argumente: &[String]) -> Option<PathBuf> {
    argumente
        .iter()
        .position(|wort| wort == "--node" || wort == "-n")
        .and_then(|stelle| argumente.get(stelle + 1))
        .map(PathBuf::from)
}

fn waermste(werte: &BTreeMap<String, f64>) -> Option<(&String, &f64)> {
    werte
        .iter()
        .max_by(|(_, links), (_, rechts)| links.partial_cmp(rechts).unwrap_or(Ordering::Equal))
}

fn status(knoten: Option<&PathBuf>) -> ExitCode {
    let pad = match Pad::open(knoten.map(PathBuf::as_path)) {
        Ok(pad) => pad,
        Err(fehler) => {
            println!("Kuehler : {fehler}");
            return ExitCode::from(1);
        }
    };
    let zustand = match pad.read_state(true) {
        Ok(zustand) => zustand,
        Err(fehler) => {
            println!("Kuehler : {} - {fehler}", pad.node().display());
            return ExitCode::from(1);
        }
    };

    println!("Geraet  : {}", pad.node().display());
    println!(
        "Stufe   : {} %  (~{} Umdrehungen, wie das Geraet sie anzeigt)",
        zustand.fan_speed,
        zustand.rpm_display()
    );
    println!(
        "An/Aus  : {}",
        if zustand.powered_on { "an" } else { "aus" }
    );
    println!(
        "Licht   : {} {}, {}, Takt {}, Helligkeit {}",
        if zustand.light_on { "an" } else { "aus" },
        zustand.color_name(),
        zustand.effect_name(),
        zustand.effect_speed,
        zustand.brightness
    );
    if !pad.andere.is_empty() {
        let weitere: Vec<String> = pad
            .andere
            .iter()
            .map(|anderer| anderer.display().to_string())
            .collect();
        println!(
            "         (noch {} dieses Typs: {})",
            weitere.len(),
            weitere.join(", ")
        );
    }
    println!(
        "Hinweis : ohne laufenden llano-rs daemon oder Oberflaeche haelt nichts die Kurve -\n\
                   ein einzelner Befehl kaehlt also nur einmal"
    );
    ExitCode::SUCCESS
}

fn sensoren() -> ExitCode {
    let werte = sensors::lesen();
    if werte.is_empty() {
        println!("Dieser Rechner meldet keine Temperaturen unter /sys/class/hwmon.");
        return ExitCode::from(1);
    }
    let breit = werte
        .keys()
        .map(|schluessel| schluessel.chars().count())
        .max();
    let breit = breit.unwrap_or(0);
    for (schluessel, grad) in &werte {
        println!("{schluessel:<breit$}  {grad:5.1} °C");
    }
    if let Some((schluessel, grad)) = waermste(&werte) {
        println!("\nwarmste Messstelle: {schluessel} mit {grad:.1} °C");
    }
    ExitCode::SUCCESS
}

fn selbstpruefung(knotenwunsch: Option<&PathBuf>) -> ExitCode {
    let mut heil = true;

    println!(
        "Betriebssystem : {} {}",
        std::env::consts::OS,
        std::env::consts::ARCH
    );
    println!(
        "Rust-Fassung   : {VERSION}, Geraetezugriff {}",
        device::backend_name()
    );
    println!("Konfiguration  : {}", config::datei().display());
    println!(
        "Sperrdatei     : {}",
        llano_core::lock::sperr_datei().display()
    );
    // Dieselbe Datei wie bei der Python-Fassung, und nur sie verhindert, dass
    // zwei Steuerungen gleichzeitig am Geraet lesen: der Kuehler beantwortet
    // die STATUSANFRAGE einmal, und der zweite Zugriff findet dann nichts mehr.
    match llano_core::lock::erwerben() {
        Ok(_) => println!("Andere Fassung : keine - dieses Programm ist allein am Geraet"),
        Err(belegt) => println!("Andere Fassung : {belegt}"),
    }

    let vorgefunden = device::describe_nodes();
    if vorgefunden.is_empty() {
        heil = false;
        println!(
            "Kuehler        : keiner gefunden (USB {})",
            device::usb_id()
        );
    }
    for punkt in &vorgefunden {
        if !punkt.lesbar {
            heil = false;
        }
        println!(
            "Kuehler        : {} - {}",
            punkt.node.display(),
            if punkt.lesbar {
                "zugaenglich"
            } else {
                "keine Rechte"
            }
        );
    }

    // Ein genannter Knaetchenpfad gilt; sonst der erste, das Geraet meldet.
    let erster = vorgefunden.first().map(|punkt| punkt.node.clone());
    let gewuenschter = knotenwunsch.cloned().or(erster);
    match Pad::open(gewuenschter.as_deref()).and_then(|pad| pad.read_state(true)) {
        Ok(zustand) => println!(
            "Gelesen        : {}% Stufe, {}, {}",
            zustand.fan_speed,
            if zustand.powered_on { "an" } else { "aus" },
            zustand.color_name()
        ),
        Err(fehler) => {
            heil = false;
            println!("Gelesen        : {fehler}");
        }
    }

    let werte = sensors::lesen();
    if werte.is_empty() {
        heil = false;
        println!("Temperaturen   : keine gefunden");
    } else if let Some((schluessel, grad)) = waermste(&werte) {
        println!(
            "Temperaturen   : {} gefunden, waermste {grad:.0} °C an {schluessel}",
            werte.len()
        );
    }

    println!();
    if heil {
        println!(
            "Alles da, was der Rechner zum Steuern braucht. Zwei Fassungen am selben\n\
             Kuehler sind einer zu viel: eine von beiden muss aufhoeren."
        );
        ExitCode::SUCCESS
    } else {
        println!(
            "Siehe die Zeilen oben. Bei ,keine Rechte' hilft die udev-Regel aus contrib/ \
             und ein neuer Stecker."
        );
        ExitCode::from(1)
    }
}

/// Was an der Beleuchtung gerade gilt, aus einem gelesenen Bericht.
fn aktuelle_beleuchtung(zustand: &llano_core::protocol::State) -> Lighting {
    Lighting {
        color: zustand.color,
        effect: zustand.effect,
        effect_speed: zustand.effect_speed,
        brightness: zustand.brightness,
        light_on: zustand.light_on,
    }
}

fn beschreibung(zustand: &llano_core::protocol::State) -> String {
    format!(
        "{}% {}, {}, {}, {}, Takt {}, Helligkeit {}",
        zustand.fan_speed,
        if zustand.powered_on { "an" } else { "aus" },
        if zustand.light_on {
            "Licht an"
        } else {
            "Licht aus"
        },
        zustand.color_name(),
        zustand.effect_name(),
        zustand.effect_speed,
        zustand.brightness
    )
}

/// Der Kuehler, gesichert durch dieselbe Sperrdatei wie die Python-Fassung.
fn unter_sperre(knoten: Option<&PathBuf>) -> Result<(llano_core::lock::Sperre, Pad), String> {
    let sperre = llano_core::lock::erwerben().map_err(|belegt| belegt.to_string())?;
    let pad = Pad::open(knoten.map(PathBuf::as_path)).map_err(|fehler| fehler.to_string())?;
    Ok((sperre, pad))
}

/// Meldung, Pruefung und Rueckgabe fuer einen Schreibversuch.
fn berichten(
    vorher: &llano_core::protocol::State,
    nachher: &llano_core::protocol::State,
    erwartet: &str,
    stimmt: bool,
) -> ExitCode {
    println!("vorher         : {}", beschreibung(vorher));
    println!("gefordert      : {erwartet}");
    println!("zurueckgelesen : {}", beschreibung(nachher));
    if stimmt {
        println!("pruefung       : angenommen");
        ExitCode::SUCCESS
    } else {
        println!("pruefung      : das Geraet hat einen anderen Bericht zurueckgegeben");
        ExitCode::from(1)
    }
}

fn stufe_setzen(argument: &str, knoten: Option<&PathBuf>) -> ExitCode {
    let wert: f64 = match argument.parse() {
        Ok(wert) => wert,
        Err(_) => {
            println!("Eine Stufe ist eine Zahl zwischen 1 und 100, nicht `{argument}`.");
            return ExitCode::from(2);
        }
    };
    let erwartet = protocol::clamp_fan(wert);

    let (_sperre, pad) = match unter_sperre(knoten) {
        Ok(beides) => beides,
        Err(meldung) => {
            println!("{meldung}");
            return ExitCode::from(3);
        }
    };
    let vorher = match pad.read_state(true) {
        Ok(zustand) => zustand,
        Err(fehler) => {
            println!("Lesen: {fehler}");
            return ExitCode::from(1);
        }
    };

    // Der Bericht traegt immer beides: die Beleuchtung wird mitgenommen, wie
    // sie ist, damit sie stehen bleibt.
    let licht = aktuelle_beleuchtung(&vorher);
    let nachher = match pad.write_state(f64::from(erwartet), vorher.powered_on, &licht) {
        Ok(zustand) => zustand,
        Err(fehler) => {
            println!("Schreiben: {fehler}");
            return ExitCode::from(1);
        }
    };

    let beleuchtet = nachher.color == vorher.color
        && nachher.effect == vorher.effect
        && nachher.effect_speed == vorher.effect_speed
        && nachher.brightness == vorher.brightness
        && nachher.light_on == vorher.light_on;
    let stimmt = nachher.fan_speed == erwartet && beleuchtet;
    berichten(
        &vorher,
        &nachher,
        &format!("Stufe {erwartet} %, Beleuchtung behalten"),
        stimmt,
    )
}

/// Ein Wunsch zur Beleuchtung, so wie die Kommandozeile ihn nennt.
#[derive(Debug, Default, PartialEq, Eq)]
struct LichtWunsch {
    farbe: Option<u8>,
    effekt: Option<u8>,
    takt: Option<u8>,
    helligkeit: Option<u8>,
    an: Option<bool>,
}

impl LichtWunsch {
    fn ist_leer(&self) -> bool {
        *self == LichtWunsch::default()
    }
}

/// Eine Zahl, oder das deutsche Wort dafuer.
fn zahl_oder_wert(
    text: &str,
    zu_zahl: fn(&str) -> Option<u8>,
    grenze: u8,
    was: &str,
) -> Result<u8, String> {
    if let Ok(zahl) = text.parse::<u8>() {
        if zahl <= grenze {
            return Ok(zahl);
        }
        return Err(format!("{was} kennt nur 0 bis {grenze}, nicht {zahl}."));
    }
    zu_zahl(text).ok_or_else(|| {
        format!("{was} kenne ich nicht: `{text}`. Zahlen und die deutschen Namen nehmen.")
    })
}

fn licht_wunsch(argumente: &[String]) -> Result<LichtWunsch, String> {
    let mut wunsch = LichtWunsch::default();
    let mut stelle = 0;
    while stelle < argumente.len() {
        let schalter = argumente[stelle].as_str();
        // Die zwei Beleuchtungsschalter stehen fuer sich, ohne Wert daneben.
        match schalter {
            "--an" | "--on" => {
                wunsch.an = Some(true);
                stelle += 1;
                continue;
            }
            "--aus" | "--off" => {
                wunsch.an = Some(false);
                stelle += 1;
                continue;
            }
            _ => {}
        }
        let wert = argumente
            .get(stelle + 1)
            .ok_or_else(|| format!("`{schalter}` braucht einen Wert."))?;
        match schalter {
            "--farbe" | "--color" => {
                wunsch.farbe = Some(zahl_oder_wert(wert, protocol::color_value, 4, "Die Farbe")?)
            }
            "--effekt" | "--effect" => {
                wunsch.effekt = Some(zahl_oder_wert(
                    wert,
                    protocol::effect_value,
                    4,
                    "Der Effekt",
                )?)
            }
            "--takt" | "--speed" => {
                wunsch.takt = Some(zahl_oder_wert(wert, |_| None, 3, "Der Effekttakt")?)
            }
            "--helligkeit" | "--brightness" => {
                wunsch.helligkeit = Some(zahl_oder_wert(wert, |_| None, 255, "Die Helligkeit")?)
            }
            anderes => return Err(format!("Unbekannter Schalter `{anderes}` bei light.")),
        }
        stelle += 2;
    }
    Ok(wunsch)
}

fn beleuchtung_setzen(argumente: &[String], knoten: Option<&PathBuf>) -> ExitCode {
    let wunsch = match licht_wunsch(argumente) {
        Ok(wunsch) => wunsch,
        Err(meldung) => {
            println!("{meldung}");
            return ExitCode::from(2);
        }
    };
    if wunsch.ist_leer() {
        println!(
            "Nichts zu tun: `llano-rs light` braucht --farbe, --effekt, --takt, \
                  --helligkeit, --an oder --off."
        );
        return ExitCode::from(2);
    }

    let (_sperre, pad) = match unter_sperre(knoten) {
        Ok(beides) => beides,
        Err(meldung) => {
            println!("{meldung}");
            return ExitCode::from(3);
        }
    };
    let vorher = match pad.read_state(true) {
        Ok(zustand) => zustand,
        Err(fehler) => {
            println!("Lesen: {fehler}");
            return ExitCode::from(1);
        }
    };

    let jetzige = aktuelle_beleuchtung(&vorher);
    let licht = Lighting {
        color: wunsch.farbe.unwrap_or(jetzige.color),
        effect: wunsch.effekt.unwrap_or(jetzige.effect),
        effect_speed: wunsch.takt.unwrap_or(jetzige.effect_speed),
        brightness: wunsch.helligkeit.unwrap_or(jetzige.brightness),
        light_on: wunsch.an.unwrap_or(jetzige.light_on),
    };
    // Auch dieser Bericht fuehrt die Stufe mit: ohne die aktuelle zu wiederholen
    // wuerde der Kuehler stehen bleiben.
    let nachher = match pad.write_light(vorher.fan_speed, vorher.powered_on, &licht) {
        Ok(zustand) => zustand,
        Err(fehler) => {
            println!("Schreiben: {fehler}");
            return ExitCode::from(1);
        }
    };

    let stimmt = nachher.color == licht.color
        && nachher.effect == licht.effect
        && nachher.effect_speed == licht.effect_speed
        && nachher.brightness == licht.brightness
        && nachher.light_on == licht.light_on
        && nachher.fan_speed == vorher.fan_speed;
    berichten(
        &vorher,
        &nachher,
        &format!(
            "Farbe {}, Effekt {}, Takt {}, Helligkeit {}, Licht {}",
            licht.color,
            licht.effect,
            licht.effect_speed,
            licht.brightness,
            if licht.light_on { "an" } else { "aus" }
        ),
        stimmt,
    )
}

fn haupt_anweisung(anweisung: &str) -> ExitCode {
    match anweisung {
        "power" | "curve" | "daemon" | "gui" | "config" | "rules" => {
            print!("Diese Fassung kann noch nicht schreiben: {anweisung}. ");
            println!(
                "Dafuer ist die Python-Fassung da, sie ist am Geraet geprueft: llano {anweisung}"
            );
            ExitCode::from(2)
        }
        anderes => {
            println!("Unbekannte Anweisung: {anderes}\n");
            print!("{HILFE}");
            ExitCode::from(2)
        }
    }
}

fn main() -> ExitCode {
    let argumente: Vec<String> = std::env::args().skip(1).collect();
    let anweisung = argumente.first().map(String::as_str).unwrap_or("status");
    let knoten = gewuenschter_knoten(&argumente);

    match anweisung {
        "status" => status(knoten.as_ref()),
        "fan" => {
            let wert = argumente.get(1).map(String::as_str).unwrap_or("");
            if wert.is_empty() {
                println!("Eine Stufe dazu: llano-rs fan 45");
                return ExitCode::from(2);
            }
            stufe_setzen(wert, knoten.as_ref())
        }
        "light" => beleuchtung_setzen(&ohne_knoten(&argumente), knoten.as_ref()),
        "power" | "strom" => {
            let wort = argumente.get(1).map(String::as_str).unwrap_or("");
            strom_setzen(wort, knoten.as_ref())
        }
        "curve" | "kurve" => kurve_zeigen(&ohne_knoten(&argumente)),
        "rules" | "regeln" => regeln_zeigen(),
        "config" | "einstellungen" => einstellungen(&ohne_knoten(&argumente)),
        "daemon" | "dienst" => dienst(knoten.as_ref(), &argumente),
        "sensors" | "sensoren" => sensoren(),
        "selftest" => selbstpruefung(knoten.as_ref()),
        "version" | "--version" => {
            println!("llano-rs {VERSION}");
            ExitCode::SUCCESS
        }
        "hilfe" | "--help" | "-h" => {
            print!("{HILFE}");
            ExitCode::SUCCESS
        }
        anderes => haupt_anweisung(anderes),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn worte(werte: &[&str]) -> Vec<String> {
        werte.iter().map(|wort| wort.to_string()).collect()
    }

    #[test]
    fn farbe_als_zahl_oder_wort() {
        let wunsch = licht_wunsch(&worte(&["--farbe", "gruen"])).unwrap();
        assert_eq!(wunsch.farbe, Some(2));
        let wunsch = licht_wunsch(&worte(&["--farbe", "0"])).unwrap();
        assert_eq!(wunsch.farbe, Some(0));
        assert!(licht_wunsch(&worte(&["--farbe", "9"])).is_err());
        assert!(licht_wunsch(&worte(&["--farbe", "gelb"])).is_err());
    }

    #[test]
    fn schalter_ohne_wert_und_schalter_mit_wert() {
        let wunsch = licht_wunsch(&worte(&["--off", "--helligkeit", "40"])).unwrap();
        assert_eq!(wunsch.an, Some(false));
        assert_eq!(wunsch.helligkeit, Some(40));

        let wunsch = licht_wunsch(&worte(&["--an"])).unwrap();
        assert_eq!(wunsch.an, Some(true));
    }

    #[test]
    fn ein_leerer_wunsch_ist_nichts_zu_tun() {
        assert!(licht_wunsch(&[]).unwrap().ist_leer());
        assert!(!LichtWunsch {
            helligkeit: Some(10),
            ..LichtWunsch::default()
        }
        .ist_leer());
    }

    #[test]
    fn unbekannte_schalter_bleiben_abgewiesen() {
        assert!(licht_wunsch(&worte(&["--farbe", "2", "--takt"])).is_err());
        assert!(licht_wunsch(&worte(&["--pull", "2"])).is_err());
    }

    #[test]
    fn der_knotens_wird_vor_den_schaltern_abgenommen() {
        let argumente = worte(&["light", "--node", "/dev/hidraw2", "--farbe", "lila"]);
        assert_eq!(ohne_knoten(&argumente), worte(&["--farbe", "lila"]));
    }
}

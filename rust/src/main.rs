//! Kommandozeile der Rust-Fassung.
//!
//! Bewusst **nur lesend**, solange nicht jeder Schreibweg am echten Kuehler
//! nachgemessen ist: Ein Befehl, den niemand am Geraet geprueft hat, ist kein
//! Fortschritt, sondern ein Risiko fuer Luefter und Anzeige. Bis dahin schreibt
//! die Python-Fassung.

use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::process::ExitCode;

use llano_core::device::{self, Pad};
use llano_core::sensors;
use llano_core::VERSION;

const HILFE: &str = "\
llano-rs - llano V12 Ultra Notebookkuehler (Rust-Fassung, bisher lesend)

  llano-rs status [--node PFAD]   was macht der Kuehler gerade
  llano-rs sensors                Temperaturen, die dieser Rechner meldet
  llano-rs selftest               kann dieser Rechner den Kuehler
  llano-rs version                Fassung dieser Datei

Ein Kuehler schreibt:   llano fan 60     (die Python-Fassung, am Geraet geprueft)
";

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
    println!("Hinweis : diese Fassung liest nur; Schreiben bleibt bei llano");
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
    println!("Konfiguration  : in dieser Fassung noch nicht vorgesehen");

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
            "Alles da, was zum Lesen noetig ist. Schreiben uebernimmt noch die Python-Fassung."
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

fn haupt_anweisung(anweisung: &str) -> ExitCode {
    match anweisung {
        "fan" | "light" | "power" | "curve" | "daemon" | "gui" | "config" | "rules" => {
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

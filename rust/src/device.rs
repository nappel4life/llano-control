//! Der Vertrag des Geraetezugriffs - fuer beide Betriebssysteme einer.
//!
//! Der Kuehler spricht ein Protokoll (siehe [`crate::protocol`) ueber zwei
//! ganz verschiedene Busse: unter Linux ist es ein `/dev/hidrawN`, das zwei
//! ioctls bedient, unter Windows eine Geraetschnittstelle mit den
//! `HidD_`-Aufrufen aus `hid.dll`. Beide Backend-Module bieten dasselbe an,
//! damit die Protokolllogik genau einmal hier steht und nicht einmal pro
//! Betriebssystem:
//!
//! * [`find_paths`]   - alle gefundenen Kuehler, leer wenn keiner
//! * [`Pad::open`]    - einen Eintrag daraus oeffnen
//! * [`Pad::read_state`] - Zustand lesen, mit der Voranfrage, die das Geraet
//!   braucht, und mit dem kurzen Wiederholen, das der erste Zugriff verlangt
//! * [`Pad::write_state`] - schreiben und zuruecklesen
//!
//! Die Kennungen lassen sich ueber die Umgebung ueschreiben
//! (`LLANO_VENDOR_ID`, `LLANO_PRODUCT_ID`), damit Tests und ein zweiter Kuehler
//! nicht den Quelltext aendern muss.

use std::env;
use std::fmt;
use std::path::{Path, PathBuf};

use crate::protocol::{self, Lighting, ProtocolError, State, BUFFER_LEN};

#[cfg(target_os = "linux")]
use crate::device_linux as backend;

#[cfg(not(target_os = "linux"))]
use crate::device_other as backend;

/// Was fehlt, wenn der Kuehler nicht antwortet.
#[derive(Debug)]
pub enum DeviceError {
    /// Kein Geraet gefunden; der Text nennt die Kennung.
    NotFound(String),
    /// Knaetchen da, aber die Rechte fehlen.
    Permission { node: PathBuf },
    /// Der Stecker ist weg, waehrend wir damit gearbeitet haben.
    Detached,
    /// Das Geraet ist bereits geschlossen.
    Closed,
    /// Etwas anderes aus dem Betriebssystem.
    Io(std::io::Error),
    /// Der Bericht passt nicht zum Protokoll.
    Protocol(ProtocolError),
}

impl fmt::Display for DeviceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DeviceError::NotFound(was) => write!(
                f,
                "llano V12 Ultra nicht gefunden. Ist er eingesteckt (USB {})? {was}",
                usb_id()
            ),
            DeviceError::Permission { node } => write!(
                f,
                "Keine Berechtigung fuer {}. {}",
                node.display(),
                PERMISSION_HINT
            ),
            DeviceError::Detached => write!(f, "Der Kuehler ist verschwunden (getrennt?)."),
            DeviceError::Closed => write!(f, "Der Kuehler ist bereits geschlossen."),
            DeviceError::Io(fehler) => write!(f, "Geraetezugriff: {fehler}"),
            DeviceError::Protocol(fehler) => write!(f, "{fehler}"),
        }
    }
}

impl std::error::Error for DeviceError {}

impl From<ProtocolError> for DeviceError {
    fn from(fehler: ProtocolError) -> Self {
        DeviceError::Protocol(fehler)
    }
}

/// Steht unter Linux dabei, wenn das Knaetchen zwar da, aber verschlossen ist.
pub const PERMISSION_HINT: &str = "Bitte die udev-Regel aus contrib/ installieren und \
                                   den Stecker erneut ziehen und wieder stecken.";

/// Die beiden Berichte, die das Geraet neben den Zustandsbefehlen kennt:
/// 0x80 bittet es, seinen Zustand zu veröffentlichen, 0x81 will die
/// Firmware-Nummer.
pub const STATUS_REQUEST: [u8; protocol::BODY_LEN] = [0x80, 0, 0, 0, 0, 0, 0];
pub const STATUS_VERSION: u8 = 0x81;

fn kennung_aus_umgebung(name: &str, standard: u16) -> u16 {
    match env::var(name) {
        Ok(text) => u16::from_str_radix(text.trim().trim_start_matches("0x"), 16)
            .or_else(|_| text.trim().parse::<u16>())
            .unwrap_or(standard),
        Err(_) => standard,
    }
}

/// Das Kennzahlenpaar, wie es auf der Schachtel steht: `374a:b101`.
pub fn usb_id() -> String {
    format!("{:04x}:{:04x}", vendor_id(), product_id())
}

pub fn vendor_id() -> u16 {
    kennung_aus_umgebung("LLANO_VENDOR_ID", protocol::VENDOR_ID)
}

pub fn product_id() -> u16 {
    kennung_aus_umgebung("LLANO_PRODUCT_ID", protocol::PRODUCT_ID)
}

/// Alle Kuehler, die dieses System erreichen kann.
pub fn find_paths() -> Vec<PathBuf> {
    backend::find_paths(vendor_id(), product_id())
}

/// Aufzaehlung fuer die Kommandozeile.
pub fn describe_nodes() -> Vec<backend::NodeInfo> {
    backend::describe_nodes(vendor_id(), product_id())
}

/// Welcher Geraetezugriff hier gebaut ist - die Selbstpruefung nennt ihn.
pub fn backend_name() -> &'static str {
    if cfg!(target_os = "linux") {
        "device_linux"
    } else {
        "noch nicht gebaut"
    }
}

/// Ein Kuehler, mit dem gearbeitet werden kann.
///
/// Das Protokoll bestaetigt kein Schreiben. Jeder Setzer liest deshalb den
/// Bericht zurueck und prueft, ob das Geraet den Wert uebernommen hat.
pub struct Pad {
    griff: backend::Handle,
    /// Weitere Kuehler desselben Typs; die Oberflaeche bietet sie zur Auswahl an.
    pub andere: Vec<PathBuf>,
}

impl Pad {
    /// Den ersten gefundenen Kuehler oeffnen, oder den genannten.
    pub fn open(node: Option<&Path>) -> Result<Pad, DeviceError> {
        match node {
            Some(pfad) => Ok(Pad {
                griff: backend::open_path(pfad)?,
                andere: Vec::new(),
            }),
            None => {
                let wege = find_paths();
                let erster = wege.first().ok_or(DeviceError::NotFound(String::new()))?;
                let griff = backend::open_path(erster)?;
                Ok(Pad {
                    griff,
                    andere: wege[1..].to_vec(),
                })
            }
        }
    }

    pub fn node(&self) -> &Path {
        self.griff.node()
    }

    /// Der Bericht, den ein Lesen zurueckgibt, wird dadurch erst brauchbar.
    ///
    /// Am Geraet gemessen: ein nacktes GET_FEATURE liefert zurueck, was die
    /// letzte Bitte war. Nach einer Versionsanfrage kam die Anfrage selbst mit
    /// geleerten Feldern - als Zustand unbrauchbar und gefaehrlich, weil code,
    /// der diesen Zustand weiterschreibt, dem Geraet Nullen schicken wuerde.
    pub fn request_status(&self) -> Result<(), DeviceError> {
        let summe = protocol::checksum(&STATUS_REQUEST)?;
        let mut bericht = [0u8; BUFFER_LEN];
        bericht[0] = 0x00;
        bericht[1..1 + protocol::BODY_LEN].copy_from_slice(&STATUS_REQUEST);
        bericht[BUFFER_LEN - 1] = summe;
        self.griff.write_feature(&bericht)?;
        Ok(())
    }

    /// Den Bericht lesen, unveraendert.
    pub fn read_raw(&self) -> Result<[u8; BUFFER_LEN], DeviceError> {
        self.griff.read_feature()
    }

    /// Den aktuellen Zustand lesen.
    ///
    /// Dreimal kurz wiederholen deckt den Wettlauf beim ersten Zugriff ab. Ein
    /// Bericht, der noch eine offene Versionsanfrage zurueckgibt, zaehlt nicht
    /// als Antwort: Der Geraetepuffer enthaelt dann die letzte Bitte und nicht
    /// den Zustand - und wer den weiterschreibt, schickt dem Geraet Nullen.
    pub fn read_state(&self, aktualisieren: bool) -> Result<State, DeviceError> {
        let letzter = DeviceError::Detached;
        let letzter = &mut Some(letzter);
        for _ in 0..3 {
            match self.versuch(aktualisieren) {
                Ok(zustand) => return Ok(zustand),
                Err(fehler) => *letzter = Some(fehler),
            }
        }
        Err(letzter.take().unwrap_or(DeviceError::Detached))
    }

    /// Ein Leseversuch, ohne das Wiederholen darueber.
    fn versuch(&self, aktualisieren: bool) -> Result<State, DeviceError> {
        if aktualisieren {
            self.request_status()?;
        }
        let zustand = State::parse(&self.read_raw()?)?;
        if zustand.mode == STATUS_VERSION {
            return Err(DeviceError::Protocol(ProtocolError::VersionRequest));
        }
        Ok(zustand)
    }

    /// Zustand schreiben und zuruecklesen.
    pub fn write_state(
        &self,
        stufe: f64,
        powered_on: bool,
        licht: &Lighting,
    ) -> Result<State, DeviceError> {
        self.griff
            .write_feature(&protocol::build_fan_report(stufe, powered_on, licht))?;
        State::parse(&self.read_raw()?).map_err(DeviceError::from)
    }

    /// Beleuchtung schreiben und zuruecklesen. Die Stufe muss angegeben
    /// werden, weil der Bericht sie mitfuehrt.
    pub fn write_light(
        &self,
        stufe: u8,
        powered_on: bool,
        licht: &Lighting,
    ) -> Result<State, DeviceError> {
        self.griff
            .write_feature(&protocol::build_light_report(stufe, powered_on, licht))?;
        State::parse(&self.read_raw()?).map_err(DeviceError::from)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn umgebung_ueberschreibt_die_kennung() {
        env::set_var("LLANO_VENDOR_ID", "0x1234");
        assert_eq!(vendor_id(), 0x1234);
        env::set_var("LLANO_VENDOR_ID", "14154");
        assert_eq!(vendor_id(), 14154);
        env::set_var("LLANO_VENDOR_ID", "falsch");
        assert_eq!(vendor_id(), protocol::VENDOR_ID);
        env::remove_var("LLANO_VENDOR_ID");
    }

    #[test]
    fn kennung_wird_wie_auf_der_schachtel_geschrieben() {
        env::remove_var("LLANO_VENDOR_ID");
        env::remove_var("LLANO_PRODUCT_ID");
        assert_eq!(usb_id(), "374a:b101");
    }

    #[test]
    fn bitten_um_zustand_ist_neun_byte_lang() {
        let summe = protocol::checksum(&STATUS_REQUEST).unwrap();
        assert_eq!(STATUS_REQUEST.len(), 7);
        assert_eq!(summe, 0x7F);
    }
}

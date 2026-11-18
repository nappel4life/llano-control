//! Die Sperrdatei: ein Prozess, ein Kühler.
//!
//! Das Geraet vertraegt keinen Zweiten. Die Python-Fassung legt dieselbe Datei
//! an (`llanotool/loop.py`), deshalb bemerken sich beide Fassungen gegenseitig:
//! Wer schreiben will, waehrend die Oberflaeche laeuft, bekommt die Meldung mit
//! der Nummer des anderen Prozesses statt zwei sich bekampfender Steuerungen.
//!
//! Unter Windows fehlt diese Fassung noch; dort meldet [`erwerben`] einen
//! deutlichen Fehler, statt ungeschuetzt zu schreiben.

use std::env;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, Write};
use std::path::PathBuf;

#[cfg(unix)]
use std::os::unix::io::AsRawFd;

/// Der Ordner, in dem die Datei liegt: nur dieser Benutzer darf dort schreiben.
pub fn laufzeit_ordner() -> PathBuf {
    let basis = env::var("XDG_RUNTIME_DIR")
        .ok()
        .filter(|text| !text.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/tmp"));
    basis.join("llano")
}

/// Der Weg zur Sperrdatei, wie die Python-Fassung ihn nimmt: eine Vorgabe aus
/// der Umgebung (`LLANO_LOCK`) oder die Datei im Laufzeitordner.
pub fn sperr_datei() -> PathBuf {
    let vorgabe = env::var("LLANO_LOCK").ok().filter(|text| !text.is_empty());
    sperr_datei_in(vorgabe.as_deref())
}

/// Dasselbe mit der Vorgabe als Angabe, damit eine Pruefung die Umgebung nicht
/// verbiegen muss.
pub fn sperr_datei_in(vorgabe: Option<&str>) -> PathBuf {
    match vorgabe {
        Some(text) if !text.is_empty() => PathBuf::from(text),
        _ => laufzeit_ordner().join("daemon.lock"),
    }
}

/// Die Sperrdatei gehoert einem anderen.
#[derive(Debug)]
pub struct Belegt {
    /// Prozessnummer des anderen, so weit sie aus der Datei zu lesen ist.
    pub anderer: Option<String>,
}

impl fmt::Display for Belegt {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Es steuert bereits etwas den Kuehler (PID {}). Er ist der einzige Besitzer \
             des Geraets - bitte ueber ihn steuern, oder zuerst beenden.",
            self.anderer.as_deref().unwrap_or("unbekannt")
        )
    }
}

impl std::error::Error for Belegt {}

/// Die gehaltene Sperrdatei. Beim Vergessen gibt sie sich frei.
#[derive(Debug)]
pub struct Sperre {
    datei: File,
}

impl Sperre {
    /// Die Nummer, die in der Datei steht - normalerweise die eigene.
    pub fn inhaber(&self) -> String {
        nummer(&self.datei).unwrap_or_else(|| "?".to_owned())
    }
}

impl Drop for Sperre {
    fn drop(&mut self) {
        entsperren(&self.datei);
    }
}

/// Exklusiv und ohne warten. [`Belegt`] wenn ein anderer schon haelt.
#[cfg(unix)]
pub fn erwerben() -> Result<Sperre, Belegt> {
    erwerben_in(&sperr_datei())
}

/// Dasselbe in eine angegebene Datei; so bleibt eine Pruefung von der echten
/// Sperrdatei der laufenden Oberflaeche fern.
#[cfg(unix)]
pub fn erwerben_in(pfad: &std::path::Path) -> Result<Sperre, Belegt> {
    if let Some(ordner) = pfad.parent() {
        fs::create_dir_all(ordner).map_err(|_| Belegt { anderer: None })?;
    }
    let mut datei = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(pfad)
        .map_err(|_| Belegt { anderer: None })?;

    // LOCK_EX | LOCK_NB: einer, und dabei nicht warten.
    if unsafe { libc::flock(datei.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err(Belegt {
            anderer: nummer(&datei),
        });
    }

    datei
        .rewind()
        .and_then(|_| datei.set_len(0))
        .and_then(|_| write!(datei, "{}", std::process::id()))
        .and_then(|_| datei.flush())
        .ok();
    Ok(Sperre { datei })
}

/// Ohne diese Fassung: Unter Windows sperrt bisher nur die Python-Fassung.
#[cfg(not(unix))]
pub fn erwerben_in(_pfad: &std::path::Path) -> Result<Sperre, Belegt> {
    Err(Belegt {
        anderer: Some(
            "der Windows-Zugriff ist in dieser Rust-Fassung noch nicht gebaut".to_owned(),
        ),
    })
}

#[cfg(not(unix))]
pub fn erwerben() -> Result<Sperre, Belegt> {
    Err(Belegt {
        anderer: Some(
            "der Windows-Zugriff ist in dieser Rust-Fassung noch nicht gebaut".to_owned(),
        ),
    })
}

#[cfg(unix)]
fn entsperren(datei: &File) {
    unsafe { libc::flock(datei.as_raw_fd(), libc::LOCK_UN) };
}

#[cfg(not(unix))]
fn entsperren(_datei: &File) {}

fn nummer(datei: &File) -> Option<String> {
    let mut quelle = datei.try_clone().ok()?;
    quelle.rewind().ok()?;
    let mut text = String::new();
    quelle.read_to_string(&mut text).ok()?;
    let text = text.trim().to_owned();
    (!text.is_empty()).then_some(text)
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    fn ziel(name: &str) -> PathBuf {
        env::temp_dir().join(format!("llano-sperr-test-{}-{name}", std::process::id()))
    }

    #[test]
    fn eine_sperr_datei_hoert_nur_einem() {
        let pfad = ziel("einer");
        {
            let erste = erwerben_in(&pfad).expect("die erste Sperre bekommt die Datei");
            assert_eq!(erste.inhaber(), std::process::id().to_string());

            // Derselbe Prozess ein zweites Mal: flock laesst das nicht zu, und
            // genau darauf kommt es an.
            assert!(
                erwerben_in(&pfad).is_err(),
                "ein zweiter Halt muss abgewiesen werden"
            );

            // Die Nummer in der Datei ist die eigene, nicht eine geratene.
            assert_ne!(erste.inhaber(), "?");
        }

        erwerben_in(&pfad).expect("nach der Freigabe muss es wieder gehen");
        let _ = fs::remove_file(&pfad);
    }

    #[test]
    fn der_weg_ohne_vorgabe_liegt_in_der_laufzeit() {
        assert!(sperr_datei_in(None).ends_with("llano/daemon.lock"));
        assert!(sperr_datei_in(Some("")).ends_with("llano/daemon.lock"));
    }

    #[test]
    fn eine_vorgabe_wird_genommen() {
        assert_eq!(
            sperr_datei_in(Some("/tmp/andere.lock")),
            PathBuf::from("/tmp/andere.lock")
        );
    }

    #[test]
    fn ohne_nummer_heisst_es_unbekannt() {
        let fehler = Belegt { anderer: None };
        assert!(fehler.to_string().contains("unbekannt"));
        assert!(fehler.to_string().contains("einzige Besitzer"));
    }
}

//! Geraetezugriff fuer Betriebssysteme, die noch nicht gebaut sind.
//!
//! Die Datei existsiert, damit der Quellbaum auch ausserhalb von Linux
//! durchlaeuft und nicht an einer fehlenden Datei scheitert. Sie findet
//! bewusst nichts: Der Windows-Zugriff ist in dieser Fassung noch nicht
//! uebertragen, die Python-Fassung ihn aber schon hat (llanotool/
//! device_windows.py) - dort laesst sich ablesen, welche Aufrufe noetig sind.

use std::path::{Path, PathBuf};

use crate::device::DeviceError;

/// Nie vorhanden, weil es hier keinen Geraetegriff geben kann.
#[derive(Debug)]
pub enum Handle {}

/// Ein Punkt fuer die Kommandozeile; bleibt in dieser Fassung leer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeInfo {
    pub node: PathBuf,
    pub lesbar: bool,
}

pub fn find_paths(_vendor: u16, _product: u16) -> Vec<PathBuf> {
    Vec::new()
}

pub fn describe_nodes(_vendor: u16, _product: u16) -> Vec<NodeInfo> {
    Vec::new()
}

pub fn open_path(node: &Path) -> Result<Handle, DeviceError> {
    Err(DeviceError::NotFound(format!(
        "dieses Betriebssystem ({}) kann der Kuehler in dieser Rust-Fassung noch \
         nicht ansteuern - die Python-Fassung kann es",
        std::env::consts::OS
    )))
}

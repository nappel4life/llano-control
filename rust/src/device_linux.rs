//! Geraetezugriff unter Linux: das hidraw-Knaetchen und zwei ioctls.
//!
//! Die zwei Befehle fuer Feature-Berichte werden von Hand zusammengebaut -
//! hidapi waere hier sogar die schlechtere Wahl, weil das Oeffnen eines
//! Geraets darueber unter Linux ein komplettes Neubeziehen des USB-Treibers
//! ausloest.
//!
//! Der Vertrag (finden, oeffnen, lesen, schreiben) steht in [`crate::device`];
//! unter Windows erledigt dieselbe Arbeit `device_windows.rs`.

use std::ffi::CString;
use std::fs;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::io::RawFd;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::device::{DeviceError, PERMISSION_HINT};
use crate::protocol::BUFFER_LEN;

const fn ioc(richtung: u64, art: u8, nummer: u8, groesse: u64) -> u64 {
    (richtung << 30) | ((art as u64) << 8) | (nummer as u64) | (groesse << 16)
}

/// Feature-Bericht schreiben: `_IOC(READ|WRITE, 'H', 0x06, 9)`.
pub const HIDIOCSFEATURE: u64 = ioc(3, b'H', 0x06, BUFFER_LEN as u64);
/// Feature-Bericht lesen: `_IOC(READ|WRITE, 'H', 0x07, 9)`.
pub const HIDIOCGFEATURE: u64 = ioc(3, b'H', 0x07, BUFFER_LEN as u64);

const HIDRAW_SYSFS: &str = "/sys/class/hidraw";

/// Der Pfad, ueber den ein Geraet laeuft, zum Beispiel `/dev/hidraw2`.
pub type Node = PathBuf;

fn uevent_paegt(inhalt: &str, vendor: u16, product: u16) -> bool {
    // Die Datei nennt das Geraet in einer von zwei Formen, je nach Kernel:
    // nummernartig in einer Zeile (HID_ID=0003:0000374A:0000B101), das ist der
    // Regelfall, oder verteilt auf zwei Felder (VID_374A und PID_B101).
    let text = inhalt.to_ascii_uppercase();
    let nummerisch = format!("{vendor:08X}:{product:08X}");
    if text.contains(&nummerisch) {
        return true;
    }
    text.contains(&format!("VID_{vendor:04X}")) && text.contains(&format!("PID_{product:04X}"))
}

/// Alle hidraw-Knaetchen dieses Geraets, in der Reihenfolge der Nummer.
pub fn find_paths(vendor: u16, product: u16) -> Vec<Node> {
    let mut gefunde = Vec::new();
    let eintraege = match fs::read_dir(HIDRAW_SYSFS) {
        Ok(eintraege) => eintraege,
        Err(_) => return gefunde, // kein hidraw auf diesem Rechner
    };
    let mut namen: Vec<String> = eintraege
        .filter_map(|eintrag| eintrag.ok())
        .map(|eintrag| eintrag.file_name().to_string_lossy().into_owned())
        .collect();
    namen.sort();

    for name in namen {
        let uevent = Path::new(HIDRAW_SYSFS).join(&name).join("device/uevent");
        let inhalt = match fs::read_to_string(&uevent) {
            Ok(inhalt) => inhalt,
            Err(_) => continue, // weggezogen, waehrend wir gelesen haben
        };
        if uevent_paegt(&inhalt, vendor, product) {
            let knoten = PathBuf::from("/dev/").join(&name);
            if !gefunde.contains(&knoten) {
                gefunde.push(knoten);
            }
        }
    }
    gefunde
}

/// Ein Punkt fuer die Kommandozeile: der Pfad und ob man ihn benutzen darf.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeInfo {
    pub node: Node,
    pub lesbar: bool,
}

pub fn describe_nodes(vendor: u16, product: u16) -> Vec<NodeInfo> {
    find_paths(vendor, product)
        .into_iter()
        .map(|node| NodeInfo {
            lesbar: access_ok(&node),
            node,
        })
        .collect()
}

fn access_ok(node: &Path) -> bool {
    let text = match CString::new(node.as_os_str().as_encoded_bytes()) {
        Ok(text) => text,
        Err(_) => return false,
    };
    // R_OK | W_OK
    unsafe { libc::access(text.as_ptr(), 6) == 0 }
}

/// Ein geoeffnetes Geraet. Beim Vergessen geht der Descriptor zu.
#[derive(Debug)]
pub struct Handle {
    descriptor: RawFd,
    node: Node,
    offen: bool,
}

impl Handle {
    pub fn node(&self) -> &Path {
        &self.node
    }

    pub fn is_open(&self) -> bool {
        self.offen
    }
}

impl Drop for Handle {
    fn drop(&mut self) {
        self.close();
    }
}

/// Ein Geraet oeffnen. Der Fehler sagt, was zu tun ist.
pub fn open_path(node: &Path) -> Result<Handle, DeviceError> {
    let text = CString::new(node.as_os_str().as_encoded_bytes())
        .map_err(|_| DeviceError::NotFound(node.display().to_string()))?;
    let descriptor = unsafe { libc::open(text.as_ptr(), libc::O_RDWR) };
    if descriptor < 0 {
        let fehler = io::Error::last_os_error();
        return Err(match fehler.raw_os_error() {
            Some(libc::ENOENT) => DeviceError::NotFound(node.display().to_string()),
            Some(libc::EACCES) | Some(libc::EPERM) => DeviceError::Permission {
                node: node.to_path_buf(),
            },
            Some(libc::ENXIO) => DeviceError::Detached,
            _ => DeviceError::Io(fehler),
        });
    }
    Ok(Handle {
        descriptor,
        node: node.to_path_buf(),
        offen: true,
    })
}

impl Handle {
    /// Den Feature-Bericht lesen: neun Byte inklusive fuehrender Null.
    pub fn read_feature(&self) -> Result<[u8; BUFFER_LEN], DeviceError> {
        self.prueft_offen()?;
        let mut puffer = [0u8; BUFFER_LEN];
        let rueckgabe = unsafe {
            libc::ioctl(
                self.descriptor,
                HIDIOCGFEATURE as libc::c_ulong,
                puffer.as_mut_ptr(),
            )
        };
        if rueckgabe < 0 {
            return Err(abzug(io::Error::last_os_error()));
        }
        Ok(puffer)
    }

    /// Neun Byte zurueck auf das Geraet.
    pub fn write_feature(&self, bericht: &[u8; BUFFER_LEN]) -> Result<(), DeviceError> {
        self.prueft_offen()?;
        let mut puffer = *bericht;
        let rueckgabe = unsafe {
            libc::ioctl(
                self.descriptor,
                HIDIOCSFEATURE as libc::c_ulong,
                puffer.as_mut_ptr(),
            )
        };
        if rueckgabe < 0 {
            return Err(abzug(io::Error::last_os_error()));
        }
        Ok(())
    }

    /// Ein Eingangsbericht, oder nichts, wenn das Geraet schweigt.
    pub fn read_input(&self, timeout: Duration) -> Result<Option<Vec<u8>>, DeviceError> {
        self.prueft_offen()?;
        let mut ereignis = libc::pollfd {
            fd: self.descriptor,
            events: libc::POLLIN,
            revents: 0,
        };
        let milli = i32::try_from(timeout.as_millis()).unwrap_or(i32::MAX);
        let wartet = unsafe { libc::poll(&mut ereignis, 1, milli) };
        if wartet < 0 {
            return Err(abzug(io::Error::last_os_error()));
        }
        if wartet == 0 {
            return Ok(None);
        }
        let mut puffer = vec![0u8; 64];
        let n = unsafe {
            libc::read(
                self.descriptor,
                puffer.as_mut_ptr().cast::<libc::c_void>(),
                puffer.len(),
            )
        };
        if n < 0 {
            return Err(abzug(io::Error::last_os_error()));
        }
        puffer.truncate(n as usize);
        Ok(Some(puffer))
    }

    /// Abschalten: mehrfach aufrufen ist erlaubt.
    pub fn close(&mut self) {
        if self.offen {
            unsafe { libc::close(self.descriptor) };
            self.offen = false;
        }
    }

    /// Die Geraeteknoten-Nummer, wie sie `llano status` zeigt.
    pub fn kennung(&self) -> Option<String> {
        let metadata = fs::metadata(&self.node).ok()?;
        Some(format!(
            "{}:{}",
            libc::major(metadata.rdev()),
            libc::minor(metadata.rdev())
        ))
    }

    fn prueft_offen(&self) -> Result<(), DeviceError> {
        if self.offen {
            Ok(())
        } else {
            Err(DeviceError::Closed)
        }
    }
}

/// Ein weggezogener Stecker aeussert sich je nach Kernel verschieden.
fn abzug(fehler: io::Error) -> DeviceError {
    match fehler.raw_os_error() {
        Some(libc::ENODEV) => DeviceError::Detached,
        Some(libc::EPIPE) => DeviceError::Detached,
        _ => DeviceError::Io(fehler),
    }
}

/// Der Hinweis, der bei fehlenden Rechten unter die Meldung gehoert.
pub fn permission_hint() -> &'static str {
    PERMISSION_HINT
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ioctl_nummern_stimmen_mit_der_python_fassung() {
        // Python: (3 << 30) | (ord('H') << 8) | nr | (9 << 16)
        assert_eq!(HIDIOCSFEATURE, 0xC009_4806);
        assert_eq!(HIDIOCGFEATURE, 0xC009_4807);
    }

    #[test]
    fn uevent_wird_erkannt() {
        let echt = "DRIVER=hid-generic\nHID_ID=0003:0000374A:0000B101\n\
                    HID_NAME=LLANO V12 ULTRA\nHID_PHYS=usb-0000:00:14.0-3/input0\n\
                    HID_UNIQ=\n";
        assert!(uevent_paegt(echt, 0x374A, 0xB101));
        assert!(!uevent_paegt(echt, 0x374A, 0xB102));
        assert!(!uevent_paegt("HID_NAME=Maus", 0x374A, 0xB101));
    }

    #[test]
    fn ein_geschlossener_griff_weigert_sich() {
        // Ohne Geraet in der Testumgebung bleibt nur der Weg ueber den Fehler.
        let ergebnis = open_path(Path::new("/dev/es-gibt-dieses-knaetchen-nicht"));
        assert!(
            matches!(ergebnis, Err(DeviceError::NotFound(_))),
            "ein fehlender Pfad muss mit NotFound ablehnen"
        );
    }
}

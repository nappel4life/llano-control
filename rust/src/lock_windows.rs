//! Die Sperrdatei unter Windows: `LockFileEx` statt `flock`.
//!
//! Der Grund fuer die Datei ist derselbe wie in [`crate::lock`]: Das Geraet
//! vertraegt keinen Zweiten, und die Python-Fassung legt dieselbe Datei an
//! (`llanotool/loop.py`), damit beide Fassungen sich bemerken. Was sich
//! unterscheidet, ist der eine Aufruf, der der Datei ihre Eigenschaft gibt:
//!
//! * Linux kennt `flock`, das die ganze Datei sperrt.
//! * Windows sperrt **Bereich fuer Bereich**. `LockFileEx` mit
//!   `LOCKFILE_EXCLUSIVE_LOCK` ist der Aufruf, der zu `LOCK_EX` gehoert, und
//!   `LOCKFILE_FAIL_IMMEDIATELY` ist sein `LOCK_NB`: Wer zu spaet kommt,
//!   wartet nicht, sondern hoert sofort auf - genau das erwartet [`crate::Belegt`].
//! * Gesperrt wird ein Byte am Anfang der Datei, wie die Python-Fassung es mit
//!   `msvcrt.locking(..., LK_NBLCK, 1)` tut. Beide Fassungen treffen sich auf
//!   demselben Byte, sonst sperrten sie aneinander vorbei.
//!
//! Die Sperre haelt an dem offenen Griff, nicht an der Datei: Der letzte
//! `CloseHandle` - und jeder Absturz, der den Prozess mitnimmt - gibt sie
//! frei. Einen Rueckholpfad fuer einen vergessenen Prozess braucht es deshalb
//! hier nicht, so wenig wie `flock` ihn braucht.
//!
//! Die Groessen der Structur sind unten mit `const` an den Header zurueck-
//! gebunden; ein `cargo check` auf dem Windows-Ziel faellt sonst nicht durch.

use std::ffi::c_void;
use std::fs::File;
use std::os::windows::io::AsRawHandle;

/// Exklusiv: ausser mir darf niemand in den Bereich schreiben.
const LOCKFILE_EXCLUSIVE_LOCK: u32 = 0x0000_0002;
/// Und ohne warten: die Antwort kommt sofort, auch wenn ein anderer haelt.
const LOCKFILE_FAIL_IMMEDIATELY: u32 = 0x0000_0001;

/// Der gesperrte Bereich: ein Byte am Anfang der Datei (siehe Kopftext).
const BEREICH_BYTE: u32 = 1;
/// Die Laenge passt in 32 Bit, die obere Halfte der Angabe bleibt leer.
const BEREICH_OBEN: u32 = 0;

/// Der Bereich wird in einer `OVERLAPPED`-Structur uebergeben - hier nur als
/// Bereichsangabe, die Arbeit selbst ist synchron.
///
/// Dieselbe Form wie in [`crate::device_windows`], und bewusst noch einmal
/// hingeschrieben: Die Sperre darf das Geraetemodul nicht brauchen, sonst
/// haengt ein Prozess, der nur die Sperrdatei anfassen will, plaetzlich an
/// `hid.dll`. Die zwei Werte unten sind je vier Byte, das geteilte Feld ist
/// zeigerbreit, damit alles an der Stelle des Headers zu stehen kommt.
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct Ueberlappung {
    #[allow(dead_code)] // Bereichsangabe, kein Ergebnis
    intern: u32,
    #[allow(dead_code)]
    intern_hoch: u32,
    /// `Offset`/`OffsetHigh`, zugleich der `Pointer`: der Anfang der Datei.
    verschiebung: usize,
    /// Bei dieser Verwendung unbenutzt, haelt die Structur nur an ihrer Stelle.
    #[allow(dead_code)]
    ereignis: *mut c_void,
}

const _: () = assert!(
    std::mem::size_of::<Ueberlappung>()
        == if cfg!(target_pointer_width = "64") {
            24
        } else {
            20
        },
    "die Bereichsangabe folgt dem OVERLAPPED-Kopf"
);

// Bereich, nicht asynchrone Arbeit: `LockFileEx` und `UnlockFileEx` sind
// normale Aufrufe, die erst zurueckkommen, wenn entschieden ist.
#[link(name = "kernel32")]
extern "system" {
    fn LockFileEx(
        datei: *mut c_void,
        flaggen: u32,
        vorrang: u32,
        niedere_byte: u32,
        obere_byte: u32,
        bereich: *mut Ueberlappung,
    ) -> i32;
    fn UnlockFileEx(
        datei: *mut c_void,
        vorrang: u32,
        niedere_byte: u32,
        obere_byte: u32,
        bereich: *mut Ueberlappung,
    ) -> i32;
}

/// Den Bereich exklusiv und ohne warten.
///
/// `true` heisst: der Bereich gehoert jetzt diesem Griff. `false` heisst, ein
/// anderer haelt ihn - oder die Datei laesst sich überhaupt nicht sperren,
/// etwa auf einem Netzlaufwerk; beides fuehrt bei [`crate::erwerben`] zur
/// Meldung, dass schon etwas steuert.
pub fn sperren(datei: &File) -> bool {
    let griff = datei.as_raw_handle();
    let mut bereich = Ueberlappung::default(); // Anfang der Datei, ein Byte
                                               // sicher: der Griff gehoert der offenen Datei und bleibt gueltig, solange
                                               // sie offen ist; `bereich` ist eine eigene Structur auf dem Stapel und
                                               // lebt den ganzen Aufrueber; der genannte Bereich (Anfang, ein Byte) liegt
                                               // in jeder Datei, die gerade erst angelegt wurde.
    let bekommen = unsafe {
        LockFileEx(
            griff,
            LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY,
            0,
            BEREICH_BYTE,
            BEREICH_OBEN,
            &mut bereich,
        )
    };
    bekommen != 0
}

/// Den Bereich wieder freigeben.
///
/// Ein eigenes Freigeben ist nur Hoeeflichkeit: Beim Schliessen der Datei faellt
/// die Sperre von allein. Die Python-Fassung hebt ihre Sperre aber ebenso auf,
/// und wer die Datei weiterreicht, soll sie ohne Sperre weiterreichen.
pub fn freigeben(datei: &File) {
    let griff = datei.as_raw_handle();
    let mut bereich = Ueberlappung::default();
    // sicher: derselbe Bereich wie beim Sperren und derselbe Grund, warum der
    // Griff gueltig ist; beim Freigeben sind keine Flaggen vorgesehen.
    unsafe { UnlockFileEx(griff, 0, BEREICH_BYTE, BEREICH_OBEN, &mut bereich) };
}

// ---------------------------------------------------------------- pruefung---

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn ziel(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "llano-sperr-windows-{}-{name}.lock",
            std::process::id()
        ))
    }

    fn anlegen(pfad: &std::path::Path) -> File {
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(pfad)
            .expect("eine Sperrdatei anlegen")
    }

    #[test]
    fn die_erste_sperre_bekommt_den_bereich() {
        let pfad = ziel("einer");
        let datei = anlegen(&pfad);
        assert!(sperren(&datei), "ein freier Bereich ist zu haben");
        freigeben(&datei);
        let _ = std::fs::remove_file(&pfad);
    }

    #[test]
    fn ein_zweiter_griff_weicht_aus() {
        // Genau darauf kommt es an: Ein zweiter Halt - hier ein zweiter Griff
        // auf dieselbe Datei, was Windows wie einen zweiten Prozess behandelt
        // - darf nicht durchkommen, und zwar ohne zu warten.
        let pfad = ziel("zwei");
        let erster = anlegen(&pfad);
        assert!(sperren(&erster));

        let zweiter = anlegen(&pfad);
        assert!(
            !sperren(&zweiter),
            "derselbe Bereich darf nicht zweigeteilt sein"
        );

        freigeben(&erster);
        assert!(sperren(&zweiter), "nach der Freigabe muss es wieder gehen");
        freigeben(&zweiter);
        let _ = std::fs::remove_file(&pfad);
    }

    #[test]
    fn eine_sperr_datei_hoert_nur_einem() {
        // Dasselbe mit der echten Sperre, inklusive der Nummer, die in der
        // Datei steht und die die Meldung nennt.
        let pfad = ziel("sperr");
        {
            let erste =
                crate::lock::erwerben_in(&pfad).expect("die erste Sperre bekommt die Datei");
            assert_eq!(erste.inhaber(), std::process::id().to_string());
            assert!(
                crate::lock::erwerben_in(&pfad).is_err(),
                "ein zweiter Halt muss abgewiesen werden"
            );
        }
        crate::lock::erwerben_in(&pfad).expect("nach der Freigabe muss es wieder gehen");
        let _ = std::fs::remove_file(&pfad);
    }
}

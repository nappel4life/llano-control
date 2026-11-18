//! Geraetezugriff unter Windows: Geraetschnittstellen aus setupapi,
//! Feature-Berichte aus `hid.dll`.
//!
//! Das Gegenstueck zu [`crate::device_linux`]: derselbe Vertrag (finden,
//! oeffnen, lesen, schreiben), ein ganz anderer Bus. Gebaut ist das hier nach
//! der Python-Fassung `llanotool/device_windows.py`, und zwar als Nachbau
//! ihrer *Aufrufreihenfolge* - die Fassung ist am Geraet nicht nachgemessen,
//! und dieselbe Zurueckhaltung gilt auch hier. Die Pruefungen am Ende der
//! Datei halten die Struct-Layouts fest; ein vertipptes Feld faellt dort auf
//! und nicht spaeter am Kuehler.
//!
//! # Was aufgerufen wird, und warum
//!
//! * Finden: `HidD_GetHidGuid` -> `SetupDiGetClassDevsW` (nur anwesende, nur
//!   Geraetschnittstellen) -> `SetupDiEnumDeviceInterfaces` ->
//!   `SetupDiGetDeviceInterfaceDetailW` (zweimal: erst die Groesse, dann der
//!   Text) -> `SetupDiDestroyDeviceInfoList`, auch dann, wenn unterwegs etwas
//!   fehlschlaegt.
//! * Oeffnen: `CreateFileW` mit Lese- *und* Schreibfreigabe, damit die
//!   Herstelleranwendung daneben laufen kann, und `OpenExisting` - wir wollen
//!   nichts erzeugen. Danach `HidD_GetAttributes` (ist das wirklich der
//!   Kuehler?) und `HidD_GetPreparsedData` + `HidP_GetCaps` (wie lang sind die
//!   Berichte?).
//! * Lesen und Schreiben: `HidD_GetFeature` und `HidD_SetFeature`, jeweils mit
//!   dem Puffer in Berichtslaenge.
//!
//! Alle Bibliotheken liegen im Betriebssystem (`hid`, `hidclass`, `setupapi`,
//! `kernel32`); eine zusatzliche Abhaengigkeit braucht dieses Modul nicht.
//!
//! # Die Erkennung sitzt im Pfad, nicht im Produktnamen
//!
//! Die Schnittstellenpfade tragen die Kennungen selbst im Text, in der Form
//! `vid_374a&pid_b101`. Deshalb sucht das Finden im Pfad und nicht im
//! Produktnamen oder in der Seriennummer: Beides braucht einen offenen Griff -
//! also genau den Zugriff, den ein anderes Programm gerade exclusiv halten
//! kann - die Seriennummer ist bei diesem Pad regelmaessig leer, und der
//! Produktname ist eine Herstellerangabe, die eine Firmware aendern kann. Der
//! Pfad ist zusaetzlich genau das, was spaeter `CreateFileW` haben will: die
//! Liste gibt also etwas Greifbares weiter und nicht nur einen Anzeigetext.
//! [`Handle::product_name`] gibt es trotzdem, fuer Aufzaehlungen.
//!
//! # Wo diese Fassung von der Python-Fassung abweicht
//!
//! Die Abweichungen sind Absicht und jeweils an der Stelle nachgelesen; die
//! Python-Fassung bleibt, wie sie ist:
//!
//! * [`ffi::HidpCaps`] hat die vollen 64 Byte. Die Python-Fassung deklariert
//!   nur die fnf ersten Felder (10 Byte), `HidP_GetCaps` schreibt aber den
//!   ganzen Satz - dort landeten 54 Byte hinter dem Puffer.
//! * `HidP_GetCaps` liegt in `hidclass.dll`, nicht in `hid.dll` wie der Rest
//!   der `Hid`-Aufrufe.
//! * [`ffi::Overlapped`] entspricht dem Header (24 Byte auf x64, `hEvent` an
//!   Stelle 16). Die Python-Fassung haelt `Internal`/`InternalHigh` fuer
//!   Zeiger und schiebt `hEvent` damit auf Stelle 32 - ihre Eingabemeldungen
//!   konnten deshalb nie ankommen.
//! * Ein Pfad ohne Abschlusszeichen wird nicht zurueckgegeben: ohne Abschluss
//!   ist er unbrauchbar, die Python-Fassung deklariert in dem Fall 4090 Byte
//!   Muell als Pfad.
//! * `ReadFile` kann eine Eingabemeldung auch sofort erfuellen. Dann gilt die
//!   Ueberlappungsstruktur als unbestimmt und wird nicht ausgewertet; die
//!   Python-Fassung wartet in diesem Fall auf ein Ereignis, das nie gesetzt
//!   wird.

use std::ffi::c_void;
use std::io;
use std::mem::size_of;
use std::os::windows::ffi::{OsStrExt, OsStringExt};
use std::path::{Path, PathBuf};
use std::ptr;
use std::time::Duration;

use crate::device::{self, DeviceError};
use crate::protocol::BUFFER_LEN;

/// Die Berichtslaengen, die angenommen werden, wenn das Geraet sie nicht
/// meldet: der Zustandsbericht des Kuehler und ein Eingangsbericht mit 64
/// Nutzbyte. Beides ist Vorschlag, kein Nachmessen - deshalb steht es hier
/// offen und nicht versteckt im Aufruf.
const BERICHTSRUECKFALL: usize = BUFFER_LEN;
const EINGABERUECKFALL: usize = 65;

/// Kleingeld der Windows-API, einmal hingeschrieben, damit die Aufrufe lesbar
/// bleiben. Die Namen sind die der Header (sie stehen in jeder Windows-
/// Unterlage so), die Erklaerungen auf Deutsch.
mod ffi {
    // Die Feld- und Aufrufnamen in diesem Modul sind die der Windows-Header,
    // nicht unsere eigenen: Ein Vergleich mit der Unterlage muss Wort fuer
    // Wort gehen. Deshalb die eine Ausnahme von der sonst geltenden
    // Schreibweise, und zwar nur innerhalb dieses Moduls.
    #![allow(non_snake_case)]

    use std::ffi::c_void;
    use std::mem::size_of;
    use std::ptr;

    /// `HANDLE`: ein Griff des Betriebssystems. Null und `-1` bedeuten
    /// Versagen, aber nicht bei jedem Aufruf dasselbe - die Aufrufer pruefen
    /// beides, weil `SetupDiGetClassDevsW` null meldet und `CreateFileW` -1.
    pub type Griff = *mut c_void;

    /// Der Wert, mit dem die Header ihren Erfolg melden: `TRUE` ist eine von
    /// null verschiedene Zahl, verglichen wird gegen null.
    pub fn gelungen(wert: i32) -> bool {
        wert != 0
    }

    /// Erfolgsmeldung von `HidP_GetCaps` laut `hidpi.h`
    /// (`HIDP_STATUS_SEVERITY | 0`). Diese Funktion liefert *keine* null
    /// zurueck, wenn alles gut gegangen ist.
    pub const HIDP_STATUS_SUCCESS: i32 = 0x0011_0000;

    // ---------------------------------------------------------------- flags--
    pub const GENERIC_READ: u32 = 0x8000_0000;
    pub const GENERIC_WRITE: u32 = 0x4000_0000;
    pub const FILE_SHARE_READ: u32 = 0x0000_0001;
    pub const FILE_SHARE_WRITE: u32 = 0x0000_0002;
    pub const OPEN_EXISTING: u32 = 3;
    /// Nur fuer den zweiten Griff der Eingabemeldungen; der Arbeitsgriff bleibt
    /// synchron, damit `HidD_GetFeature` ein ganz normaler Aufruf bleibt.
    pub const FILE_FLAG_OVERLAPPED: u32 = 0x4000_0000;
    /// Den Griff gibt `CreateFileW` zurueck, wenn es nicht oeffnen konnte.
    pub const INVALID_HANDLE_VALUE: Griff = -1isize as Griff;

    pub const DIGCF_PRESENT: u32 = 0x0000_0002;
    pub const DIGCF_DEVICEINTERFACE: u32 = 0x0000_0010;

    // -------------------------------------------------------------- fehler--
    pub const ERROR_FILE_NOT_FOUND: i32 = 2;
    pub const ERROR_PATH_NOT_FOUND: i32 = 3;
    pub const ERROR_ACCESS_DENIED: i32 = 5;
    pub const ERROR_GEN_FAILURE: i32 = 31;
    pub const ERROR_DEVICE_NOT_AVAILABLE: i32 = 433;
    pub const ERROR_IO_PENDING: i32 = 997;

    pub const WAIT_OBJECT_0: u32 = 0x0000_0000;

    // ---------------------------------------------------------------- typen--

    /// `GUID`: 16 Byte, auf beiden Zielen genauso aufgebaut.
    #[repr(C)]
    #[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
    pub struct Guid {
        pub Data1: u32,
        pub Data2: u16,
        pub Data3: u16,
        pub Data4: [u8; 8],
    }

    /// `SP_DEVICE_INTERFACE_DATA`: 32 Byte auf x64, 28 auf x86. `cbSize` sagt
    /// dem Treiber, welche Fassung des Kopfes er sieht, und bekommt deshalb
    /// die eigene Groesse - hier gibt es keinen Grund, sie zu raten.
    #[repr(C)]
    #[derive(Debug, Clone, Copy)]
    pub struct SpDeviceInterfaceData {
        pub cbSize: u32,
        pub InterfaceClassGuid: Guid,
        pub Flags: u32,
        pub Reserved: *mut c_void,
    }

    impl Default for SpDeviceInterfaceData {
        fn default() -> Self {
            SpDeviceInterfaceData {
                // Der Kopf sagt, wie gross er selbst ist; darauf besteht der
                // Treiber, bevor er den Rest anruert.
                cbSize: size_of::<SpDeviceInterfaceData>() as u32,
                InterfaceClassGuid: Guid::default(),
                Flags: 0,
                Reserved: ptr::null_mut(),
            }
        }
    }

    /// `SP_DEVICE_INTERFACE_DETAIL_DATA_W`: der beruechtigte Kopf.
    ///
    /// Die *Structur* ist auf beiden Zielen 8 Byte (4 Byte `cbSize`, ein
    /// `WCHAR`, auf ein Vielfaches von vier aufgerundet). Der Wert, den
    /// Windows in `cbSize` sehen will, ist auf 32-Bit-Zielen aber **6**: Die
    /// Rechnung der Header geht von 4 + `sizeof(WCHAR)` aus, das Padding von
    /// MSVC zaehlt dort nicht mit. Wer hier die Structurgroesse eintraegt,
    /// bekommt auf x86 die klassische Fehlermeldung `ERROR_INVALID_USER_BUFFER`.
    /// Die Python-Fassung loest das mit einer Zweiwegentscheidung nach
    /// Zeigerbreite; [`super::DETAIL_CBGROESSE`] ist dieselbe Entscheidung,
    /// nur mit erklaerendem Text.
    #[repr(C)]
    #[allow(dead_code)] // gebaut wird der Puffer von Hand; hier steht die Form
    pub struct SpDeviceInterfaceDetailDataW {
        pub cbSize: u32,
        /// Der eigentliche Text folgt hier; die Eins ist der Platzhalter der
        /// Header, nie die wirkliche Laenge.
        #[allow(dead_code)]
        pub DevicePath: [u16; 1],
    }

    /// `HIDD_ATTRIBUTES`: 12 Byte. `Size` muss die eigene Groesse nennen,
    /// sonst lehnt `HidD_GetAttributes` ab.
    #[repr(C)]
    #[derive(Debug, Clone, Copy)]
    pub struct HiddAttributes {
        pub Size: u32,
        pub VendorID: u16,
        pub ProductID: u16,
        #[allow(dead_code)] // wird nicht ausgewertet; die Kennungen reichen
        pub VersionNumber: u16,
    }

    impl Default for HiddAttributes {
        fn default() -> Self {
            HiddAttributes {
                Size: size_of::<HiddAttributes>() as u32,
                VendorID: 0,
                ProductID: 0,
                VersionNumber: 0,
            }
        }
    }

    /// `HIDP_CAPS` aus `hidpi.h`: 32 Kurzwerte, 64 Byte.
    ///
    /// Der ganze Satz muss sein, auch wenn nur fuenf Werte gelesen werden:
    /// `HidP_GetCaps` schreibt die Structur, wie sie im Header steht, und wer
    /// einen zu kleinen Puffer hinhaelt, schreibt hinter seinen eigenen Stapel
    /// hinein. Deshalb hier kein abgespeckter Kopf.
    #[repr(C)]
    #[allow(dead_code)] // gelesen werden nur die ersten fuenf Werte
    #[derive(Clone, Copy, Default)]
    pub struct HidpCaps {
        pub UsagePage: u16,
        pub Usage: u16,
        pub InputReportByteLength: u16,
        pub OutputReportByteLength: u16,
        pub FeatureReportByteLength: u16,
        pub Reserved: [u16; 17],
        pub NumberLinkCollectionNodes: u16,
        pub NumberInputButtonCaps: u16,
        pub NumberInputValueCaps: u16,
        pub NumberInputDataIndices: u16,
        pub NumberOutputButtonCaps: u16,
        pub NumberOutputValueCaps: u16,
        pub NumberOutputDataIndices: u16,
        pub NumberFeatureButtonCaps: u16,
        pub NumberFeatureValueCaps: u16,
        pub NumberFeatureDataIndices: u16,
    }

    /// `OVERLAPPED`: 24 Byte auf x64, 20 auf x86.
    ///
    /// Die zwei Fallen stecken in den ersten acht Bytes: `Internal` und
    /// `InternalHigh` sind `ULONG`, also *Zahlen* von je vier Byte - die
    /// Python-Fassung hilt sie fuer Zeiger und rueckt damit alles dahinter um
    /// acht Byte zurueck, ihr `hEvent` landete auf Stelle 32 statt 16. Und die
    /// beiden Werte fuer `Offset`/`OffsetHigh` teilen sich mit dem `Pointer`
    /// ein Feld (im Header ein anonymer Verbund); als `usize` hat diese Stelle
    /// auf beiden Zielen genau Zeigerbreite, womit `hEvent` auf 16 (x64) bzw.
    /// 12 (x86) zu stehen kommt. Fuer `ReadFile` ist die Structur die Bitte um
    /// ein Ereignis, fuer `LockFileEx` nur die Bereichsangabe.
    #[repr(C)]
    #[derive(Clone, Copy, Default)]
    pub struct Overlapped {
        #[allow(dead_code)] // fuellt das Betriebssystem aus; gebrauchen tun wir es nicht
        pub Internal: u32,
        #[allow(dead_code)]
        pub InternalHigh: u32,
        /// `Offset`/`OffsetHigh`, zugleich der `Pointer` - hier immer null.
        #[allow(dead_code)]
        pub verschiebung: usize,
        pub hEvent: Griff,
    }

    // ------------------------------------------------------------ pruefung---
    //
    // Die Groessen, die auch die Windows-Header festschreiben. Ein `const`
    // statt einer Pruefung zur Laufzeit: Der Befehl `cargo check --target
    // x86_64-pc-windows-msvc` liest das Ziel wirklich aus und scheitert schon
    // am Aufbau, wenn ein Feld eine andere Breite hat - ohne dass jemand ein
    // Windows mit angestecktem Kuehler braucht.
    const _: () = assert!(size_of::<Guid>() == 16, "GUID: vier, zwei, zwei, acht");
    const _: () = assert!(
        size_of::<SpDeviceInterfaceData>() == 32,
        "Kopf der Schnittstelle"
    );
    const _: () = assert!(
        size_of::<SpDeviceInterfaceDetailDataW>() == 8,
        "Detailkopf: 4 + 1 WCHAR, auf vier aufgerundet"
    );
    const _: () = assert!(size_of::<HiddAttributes>() == 12, "vier + drei Kurzwerte");
    const _: () = assert!(size_of::<HidpCaps>() == 64, "32 Kurzwerte, der ganze Satz");
    const _: () = assert!(
        size_of::<Overlapped>()
            == if cfg!(target_pointer_width = "64") {
                24
            } else {
                20
            },
        "zwei ULONG, ein geteiltes Feld, ein Griff"
    );
    const _: () = assert!(
        if cfg!(target_pointer_width = "64") {
            size_of::<usize>() == 8
        } else {
            size_of::<usize>() == 4
        },
        "die geteilte Stelle ist so breit wie ein Zeiger"
    );

    // ------------------------------------------------------------ aufrufe---

    // Die Geraetschnittstelle und ihre Berichte: hid.dll.
    #[link(name = "hid")]
    extern "system" {
        pub fn HidD_GetHidGuid(HidGuid: *mut Guid);
        pub fn HidD_GetAttributes(
            HidDeviceObjectHandle: Griff,
            Attributes: *mut HiddAttributes,
        ) -> i32;
        pub fn HidD_GetFeature(
            HidDeviceObjectHandle: Griff,
            ReportBuffer: *mut c_void,
            ReportBufferLength: u32,
        ) -> i32;
        pub fn HidD_SetFeature(
            HidDeviceObjectHandle: Griff,
            ReportBuffer: *mut c_void,
            ReportBufferLength: u32,
        ) -> i32;
        pub fn HidD_GetProductString(
            HidDeviceObjectHandle: Griff,
            Buffer: *mut c_void,
            BufferLength: u32,
        ) -> i32;
        pub fn HidD_GetPreparsedData(
            HidDeviceObjectHandle: Griff,
            PreparsedData: *mut *mut c_void,
        ) -> i32;
        pub fn HidD_FreePreparsedData(PreparsedData: *mut c_void) -> i32;
    }

    // Die Berichtslaengen liegen woanders im Betriebssystem als der Rest:
    // HidP_GetCaps gehoert zu hidclass.dll (hidclass.lib, Header hidpi.h).
    #[link(name = "hidclass")]
    extern "system" {
        pub fn HidP_GetCaps(PreparsedData: *mut c_void, Capabilities: *mut HidpCaps) -> i32;
    }

    // Das Aufzaehlen der Geraetschnittstellen: setupapi.dll.
    #[link(name = "setupapi")]
    extern "system" {
        pub fn SetupDiGetClassDevsW(
            ClassGuid: *const Guid,
            Enumerator: *const u16,
            hwndParent: Griff,
            Flags: u32,
        ) -> Griff;
        pub fn SetupDiEnumDeviceInterfaces(
            DeviceInfoSet: Griff,
            DeviceInfoData: *mut c_void,
            InterfaceClassGuid: *const Guid,
            MemberIndex: u32,
            DeviceInterfaceData: *mut SpDeviceInterfaceData,
        ) -> i32;
        pub fn SetupDiGetDeviceInterfaceDetailW(
            DeviceInfoSet: Griff,
            DeviceInterfaceData: *const SpDeviceInterfaceData,
            DeviceInterfaceDetailData: *mut c_void,
            DeviceInterfaceDetailDataSize: u32,
            RequiredSize: *mut u32,
            DeviceInfoData: *mut c_void,
        ) -> i32;
        pub fn SetupDiDestroyDeviceInfoList(DeviceInfoSet: Griff) -> i32;
    }

    // Oeffnen, schliessen und die eine asynchrone Lesung: kernel32.dll.
    #[link(name = "kernel32")]
    extern "system" {
        pub fn CreateFileW(
            lpFileName: *const u16,
            dwDesiredAccess: u32,
            dwShareMode: u32,
            lpSecurityAttributes: *mut c_void,
            dwCreationDisposition: u32,
            dwFlagsAndAttributes: u32,
            hTemplateFile: Griff,
        ) -> Griff;
        pub fn CloseHandle(hObject: Griff) -> i32;
        pub fn CreateEventW(
            lpEventAttributes: *mut c_void,
            bManualReset: i32,
            bInitialState: i32,
            lpName: *const u16,
        ) -> Griff;
        pub fn WaitForSingleObject(hHandle: Griff, dwMilliseconds: u32) -> u32;
        pub fn ReadFile(
            hFile: Griff,
            lpBuffer: *mut c_void,
            nNumberOfBytesToRead: u32,
            lpNumberOfBytesRead: *mut u32,
            lpOverlapped: *mut Overlapped,
        ) -> i32;
        pub fn GetOverlappedResult(
            hFile: Griff,
            lpOverlapped: *mut Overlapped,
            lpNumberOfBytesTransferred: *mut u32,
            bWait: i32,
        ) -> i32;
        pub fn CancelIo(hFile: Griff) -> i32;
    }
}

/// Was bei fehlenden Rechten dazu gesagt wird.
///
/// Der Hinweis in [`crate::device::PERMISSION_HINT`] verweist auf die
/// udev-Regel aus `contrib/` und damit auf eine Datei, die es auf Windows
/// nicht gibt; die Windows-Fassung steht deshalb hier und wird in die Meldung
/// geschrieben, die ohnehin vorgelesen wird.
pub const PERMISSION_HINT_WINDOWS: &str = "Die Windows-Oberflaeche des Herstellers \
                                          (MythCool) haelt das Geraet manchmal exclusiv - \
                                          bitte dort beenden und neu versuchen. Sonst helfen \
                                          ein neuer Stecker und, wenn das nichts aendert, \
                                          der Treiber im Geraetemanager.";

/// Die Groessenangabe, die `SetupDiGetDeviceInterfaceDetailW` in `cbSize`
/// sehen will: 8 auf 64-Bit-Zielen, 6 auf 32-Bit-Zielen - und damit auf dem
/// kleineren Ziel gerade *nicht* die Structurgroesse (siehe
/// [`ffi::SpDeviceInterfaceDetailDataW`]).
const DETAIL_CBGROESSE: u32 = if cfg!(target_pointer_width = "64") {
    8
} else {
    // 4 Byte Kopf + ein WCHAR; das Padding der Structur zaehlt nicht mit.
    6
};

/// Der Puffer fuer einen Schnittstellenpfad, mindestens so gross wie die
/// Python-Fassung ihn nimmt. Laengere Pfade sind erlaubt: genommen wird das
/// Grossere aus Angabe und Vorschlag.
const DETAIL_PUFFER_BYTES: usize = 4096;

/// Ein Punkt fuer die Kommandozeile: der Pfad und ob man ihn benutzen darf.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeInfo {
    pub node: PathBuf,
    pub lesbar: bool,
}

/// Alle Kuehler, die dieses Windows sieht - in der Reihenfolge der
/// Aufzaehlung, jeder Pfad genau einmal.
pub fn find_paths(vendor: u16, product: u16) -> Vec<PathBuf> {
    let mut gefunde = Vec::new();
    for pfad in schnittstellen_wege() {
        if passt_zum_kuehler(&pfad, vendor, product) && !gefunde.contains(&pfad) {
            gefunde.push(pfad);
        }
    }
    gefunde
}

/// Aufzaehlung fuer die Kommandozeile: ein Pfad ist brauchbar, wenn er sich
/// oeffnen laesst. Der Griff wird nicht behalten - [`Handle`] schliesst sich
/// beim Vergessen von selbst, das ist das `try/finally` der Python-Fassung.
pub fn describe_nodes(vendor: u16, product: u16) -> Vec<NodeInfo> {
    find_paths(vendor, product)
        .into_iter()
        .map(|node| NodeInfo {
            lesbar: open_path(&node).is_ok(),
            node,
        })
        .collect()
}

/// Der Hinweis, der bei fehlenden Rechten unter die Meldung gehoert.
pub fn permission_hint() -> &'static str {
    PERMISSION_HINT_WINDOWS
}

// ------------------------------------------------------------ aufzaehlung---

/// Die Windows-Klasse der HID-Geraetschnittstellen, vom Betriebssystem
/// erfragt und nicht geraten (`{4d1e55b2-f16f-11cf-88cb-001111000030}`).
fn hid_klasse() -> ffi::Guid {
    let mut klasse = ffi::Guid::default();
    // sicher: die Ubergabeadresse zeigt auf ein eigenes, gueltiges Guid; der
    // Aufruf schreibt nur hinein und kann nicht scheitern.
    unsafe { ffi::HidD_GetHidGuid(&mut klasse) };
    klasse
}

/// Haelt die Aufzaehlungsmenge und gibt sie garantiert zurueck - auch dann,
/// wenn unterwegs etwas panaert. Das ist das `finally` der Python-Fassung.
struct MengenWachter {
    menge: ffi::Griff,
}

impl Drop for MengenWachter {
    fn drop(&mut self) {
        // sicher: die Menge wurde vorher erfolgreich erzeugt und ist noch
        // nicht freigegeben; der Wachter existiert genau einmal und raeumt beim
        // Untergehen auf, also kann dieser Aufruf nicht zweimal passieren.
        unsafe { ffi::SetupDiDestroyDeviceInfoList(self.menge) };
    }
}

/// Jeder anwesende HID-Schnittstellenpfad, in der Reihenfolge der
/// Aufzaehlung.
///
/// Ein Geraet mit mehreren Schnittstellen meldet einen Pfad pro
/// Schnittstelle; die Auswahl nach den Kennungen passiert danach in
/// [`passt_zum_kuehler`].
fn schnittstellen_wege() -> Vec<PathBuf> {
    let klasse = hid_klasse();
    // sicher: `klasse` lebt bis zum Ende des Aufrufs; die beiden Zeiger, die
    // hier null sind, bedeuten "keine Vorgabe" und "kein Elternfenster".
    let menge = unsafe {
        ffi::SetupDiGetClassDevsW(
            &klasse,
            ptr::null(),
            ptr::null_mut(),
            ffi::DIGCF_PRESENT | ffi::DIGCF_DEVICEINTERFACE,
        )
    };
    if menge.is_null() || menge == ffi::INVALID_HANDLE_VALUE {
        return Vec::new();
    }
    let _menge = MengenWachter { menge };

    let mut wege = Vec::new();
    let mut stelle = 0u32;
    loop {
        let mut daten = ffi::SpDeviceInterfaceData::default();
        // sicher: Menge und Guid leben noch, `daten` ist eine eigene Structur,
        // deren `cbSize` beim Erzeugen gesetzt wurde.
        let bekommen = unsafe {
            ffi::SetupDiEnumDeviceInterfaces(menge, ptr::null_mut(), &klasse, stelle, &mut daten)
        };
        if !ffi::gelungen(bekommen) {
            // Ab hier ist nichts weiter zu holen: `ERROR_NO_MORE_ITEMS` beendet
            // die Liste, und jeder andere Fehler stammt von einem Treiber, der
            // nicht redet. Beides heisst Aufhoeren, wie in der Python-Fassung.
            break;
        }
        if let Some(pfad) = schnittstellen_details(menge, &daten) {
            wege.push(pfad);
        }
        stelle += 1;
    }
    wege
}

/// Der Pfad zu einer Schnittstelle.
///
/// Zweimal derselbe Aufruf: ohne Puffer kommt `ERROR_INSUFFICIENT_BUFFER` und
/// die gebrauchte Groesse, mit Puffer der Text. Der erste Aufruf wird
/// absichtlich nicht ausgewertet - entschieden wird ueber den zweiten, und
/// dessen Fehler ist der, der etwas ueber den Pfad sagt.
fn schnittstellen_details(
    menge: ffi::Griff,
    daten: &ffi::SpDeviceInterfaceData,
) -> Option<PathBuf> {
    // sicher: `daten` zeigt auf eine lebende, vom Treiber erzeugte Structur;
    // der Puffer darf null sein, weil nur die Groesse interessiert.
    let mut noetig = 0u32;
    unsafe {
        ffi::SetupDiGetDeviceInterfaceDetailW(
            menge,
            daten,
            ptr::null_mut(),
            0,
            &mut noetig,
            ptr::null_mut(),
        )
    };

    let groesse = (noetig as usize).max(DETAIL_PUFFER_BYTES);
    // Ein Wortpuffer, damit die Groessenangabe an einer passend ausgerichteten
    // Stelle steht und der Text dahinter trotzdem als `u16` lesbar bleibt.
    let mut puffer = vec![0u32; groesse.div_ceil(4)];
    let brauchbar = groesse.min(puffer.len() * size_of::<u32>());
    if brauchbar <= size_of::<u32>() {
        return None; // kein Platz fuer Kopf und auch nur ein Zeichen
    }
    let anfang = puffer.as_mut_ptr().cast::<u8>();
    // sicher: der Kopf passt in den Puffer (`brauchbar` ist gross genug
    // geprueft), und die Groessenangabe ist die, die Windows auf diesem Ziel
    // erwartet.
    unsafe { ptr::write_unaligned(anfang.cast::<u32>(), DETAIL_CBGROESSE) };

    // sicher: Puffer und Groesse gehoeren zusammen, `noetig` wird nur
    // zurueckgeschrieben, und der weggelassene Geraetdatensatz durfen null.
    let bekommen = unsafe {
        ffi::SetupDiGetDeviceInterfaceDetailW(
            menge,
            daten,
            anfang.cast::<c_void>(),
            brauchbar as u32,
            &mut noetig,
            ptr::null_mut(),
        )
    };
    if !ffi::gelungen(bekommen) {
        return None;
    }

    // sicher: hinter dem Kopf stehen hochstens `brauchbar - 4` Bytes, und der
    // Treiber schliesst den Text mit einem Nullzeichen ab.
    let zeichen = unsafe { anfang.add(size_of::<u32>()).cast::<u16>() };
    let platz = (brauchbar - size_of::<u32>()) / size_of::<u16>();
    let mut breite = 0usize;
    while breite < platz {
        // sicher: `breite < platz` haelt die Adresse innerhalb des Puffers.
        if unsafe { *zeichen.add(breite) } == 0 {
            break;
        }
        breite += 1;
    }
    if breite == platz {
        return None; // kein Abschlusszeichen: dieser Pfad ist nicht lesbar
    }
    // sicher: die Zeichen liegen innerhalb des Puffers und sind geschrieben.
    let weit = unsafe { std::slice::from_raw_parts(zeichen, breite) };
    Some(PathBuf::from(std::ffi::OsString::from_wide(weit)))
}

/// Stecken die Kennungen im Schnittstellenpfad?
///
/// So sieht ein Pfad aus (gekuerzt):
/// `\\?\hid#vid_374a&pid_b101&mi_00#7&2c1e&0&0000#{4d1e55b2-...}`. Gesucht
/// wird zuerst die Herstellerkennung und danach die Produktkennung *hinter*
/// ihr, damit eine Produktkennung von einer anderen Schnittstelle nicht
/// zufaellig trifft.
fn passt_zum_kuehler(pfad: &Path, vendor: u16, product: u16) -> bool {
    let text = pfad.to_string_lossy().to_ascii_lowercase();
    let hersteller = format!("vid_{vendor:04x}");
    let produkt = format!("pid_{product:04x}");
    match text.find(&hersteller) {
        Some(stelle) => text[stelle..].contains(&produkt),
        None => false,
    }
}

// ---------------------------------------------------------------- oeffnen---

/// Ein Pfad fuer `CreateFileW`: breit und mit Abschlusszeichen.
///
/// `Err(())` gibt es fuer Pfade mit eingebettetem Nullzeichen; die kann
/// Windows nicht darstellen, und erraten wird lieber keiner.
fn verbreitern(pfad: &Path) -> Result<Vec<u16>, ()> {
    let mut weit: Vec<u16> = pfad.as_os_str().encode_wide().collect();
    if weit.contains(&0) {
        return Err(());
    }
    weit.push(0);
    Ok(weit)
}

/// Ein Geraet oeffnen. `ueberlappt` braucht nur der zweite Griff fuer
/// Eingabemeldungen; der Arbeitsgriff bleibt synchron.
fn offnen(node: &Path, ueberlappt: bool) -> Result<ffi::Griff, DeviceError> {
    let weit = verbreitern(node).map_err(|()| DeviceError::NotFound(node.display().to_string()))?;
    let gewollt = ffi::GENERIC_READ | ffi::GENERIC_WRITE;
    let freigabe = ffi::FILE_SHARE_READ | ffi::FILE_SHARE_WRITE;
    let flaggen = if ueberlappt {
        ffi::FILE_FLAG_OVERLAPPED
    } else {
        0
    };
    // sicher: `weit` ist ein nullbeendeter, gueltiger weiter Pfad und bleibt
    // bis zum Ende des Aufrufs am Leben; auf Sicherheitsangaben und eine
    // Vorlage wird verzichtet, beide Zeiger durfen null sein.
    let griff = unsafe {
        ffi::CreateFileW(
            weit.as_ptr(),
            gewollt,
            freigabe,
            ptr::null_mut(),
            ffi::OPEN_EXISTING,
            flaggen,
            ptr::null_mut(),
        )
    };
    if griff.is_null() || griff == ffi::INVALID_HANDLE_VALUE {
        return Err(eroeffnungsfehler(node));
    }
    Ok(griff)
}

/// Was zum fehlgeschlagenen Oeffnen gesagt wird.
///
/// Die Variante [`DeviceError::Permission`] bleibt hier unbenutzt: ihre
/// Meldung haengt den Linux-Hinweis auf die udev-Regel an. Der Windows-Hinweis
/// kommt deshalb in den Text, der ohnehin vorgelesen wird.
fn eroeffnungsfehler(node: &Path) -> DeviceError {
    let fehler = io::Error::last_os_error();
    match fehler.raw_os_error().unwrap_or(0) {
        ffi::ERROR_FILE_NOT_FOUND | ffi::ERROR_PATH_NOT_FOUND => {
            DeviceError::NotFound(node.display().to_string())
        }
        ffi::ERROR_ACCESS_DENIED => DeviceError::NotFound(format!(
            "Kein Zugriff auf den Kuehler ({}). {PERMISSION_HINT_WINDOWS}",
            node.display()
        )),
        anderes => DeviceError::Io(io::Error::from_raw_os_error(anderes)),
    }
}

/// Nachsehen, ob der offene Griff wirklich der Kuehler ist.
///
/// Die Kennungen kommen aus [`crate::device`], damit die
/// Umgebungsueberschreibung genau einmal da steht und nicht hier nachgebaut
/// wird.
fn kennung_pruefen(griff: ffi::Griff) -> Result<(), DeviceError> {
    let mut attribute = ffi::HiddAttributes::default();
    // sicher: `griff` gehoert dem Anrufer und ist gueltig, `attribute` nennt in
    // `Size` seine eigene Groesse, wie der Aufruf es verlangt.
    if !ffi::gelungen(unsafe { ffi::HidD_GetAttributes(griff, &mut attribute) }) {
        // Nichts gelernt - aber der Pfad, ueber den wir hierher gekommen sind,
        // hat schon nach genau diesen Kennungen gesucht.
        return Ok(());
    }
    if (attribute.VendorID, attribute.ProductID) != (device::vendor_id(), device::product_id()) {
        return Err(DeviceError::NotFound(format!(
            "{:04x}:{:04x} ist kein llano V12 Ultra ({}).",
            attribute.VendorID,
            attribute.ProductID,
            device::usb_id()
        )));
    }
    Ok(())
}

/// Wie lang die Berichte dieses Geraets sind, in Byte, das Byte fuer die
/// Berichtskennung mitgezaehlt - so, wie die Aufrufe die Laenge sehen wollen.
fn berichtslaengen(griff: ffi::Griff) -> (usize, usize) {
    let mut vorab: *mut c_void = ptr::null_mut();
    // sicher: gueltiger Griff, die Ubergabeadresse zeigt auf ein eigenes Feld.
    if !ffi::gelungen(unsafe { ffi::HidD_GetPreparsedData(griff, &mut vorab) }) || vorab.is_null() {
        return (BERICHTSRUECKFALL, EINGABERUECKFALL);
    }
    let mut kappen = ffi::HidpCaps::default();
    // sicher: gueltige Vorabauswertung, und eine Structur in voller
    // Headerlaenge; geschrieben wird ausschliesslich in diese Structur.
    let status = unsafe { ffi::HidP_GetCaps(vorab, &mut kappen) };
    // sicher: die Vorabauswertung gehoert uns, bis sie freigegeben wird, und
    // danach wird sie nicht wieder angefasst.
    unsafe { ffi::HidD_FreePreparsedData(vorab) };
    if status != ffi::HIDP_STATUS_SUCCESS {
        return (BERICHTSRUECKFALL, EINGABERUECKFALL);
    }
    (
        vorgeschlagen(kappen.FeatureReportByteLength as usize, BERICHTSRUECKFALL),
        vorgeschlagen(kappen.InputReportByteLength as usize, EINGABERUECKFALL),
    )
}

/// Ein Wert, den das Geraet gemeldet hat - oder der Vorschlag, wenn es nichts
/// gemeldet hat (dieses Geraet meldet 0, wenn es nichts weiss).
fn vorgeschlagen(gemeldet: usize, rueckfall: usize) -> usize {
    if gemeldet == 0 {
        rueckfall
    } else {
        gemeldet
    }
}

/// Ein geoeffneter Kuehler, mit dem, was beim Oeffnen ueber ihn bekannt wurde.
#[derive(Debug)]
pub struct Handle {
    /// `HANDLE` aus `CreateFileW`; der Besitz liegt bei dieser Structur.
    griff: ffi::Griff,
    node: PathBuf,
    /// Laenge des Feature-Berichts, wie das Geraet sie meldet.
    berichtslaenge: usize,
    /// Laenge eines Eingangsberichts, wie das Geraet sie meldet.
    eingabe_laenge: usize,
    offen: bool,
}

/// Ein Geraet oeffnen und nachsehen, was es fuer eins ist.
///
/// Der Betriebssystemgriff wird sofort zurueckgegeben, wenn die Pruefung
/// ablehnt: Ein Geraet, das man nicht anfassen darf, soll man auch nicht halten.
pub fn open_path(node: &Path) -> Result<Handle, DeviceError> {
    let griff = offnen(node, false)?;
    let gelernt = || -> Result<(usize, usize), DeviceError> {
        kennung_pruefen(griff)?;
        Ok(berichtslaengen(griff))
    };
    match gelernt() {
        Ok((berichtslaenge, eingabe_laenge)) => Ok(Handle {
            griff,
            node: node.to_path_buf(),
            berichtslaenge,
            eingabe_laenge,
            offen: true,
        }),
        Err(fehler) => {
            // sicher: der Griff stammt aus dem `offnen` direkt darueber und ist
            // noch ungeoeffnet geschlossen worden; der Fehler wird weitergereicht.
            unsafe { ffi::CloseHandle(griff) };
            Err(fehler)
        }
    }
}

impl Handle {
    pub fn node(&self) -> &Path {
        &self.node
    }

    pub fn is_open(&self) -> bool {
        self.offen
    }

    /// Die Berichtslaenge, die beim Oeffnen vom Geraet abgelesen wurde.
    pub fn berichtslaenge(&self) -> usize {
        self.berichtslaenge
    }

    /// Den Feature-Bericht lesen.
    ///
    /// Der Puffer ist so lang, wie das Geraet es verlangt, mindestens aber
    /// [`BUFFER_LEN`]: das fuehrende Nullbyte ist die Berichtskennung, die es
    /// bei diesem Pad nicht gibt, und hinten sitzt das Summenbyte - deshalb
    /// sieben Koerperbyte, neun Byte Puffer. Zurueck kommen, wie in der
    /// Python-Fassung, die ersten [`BUFFER_LEN`] Byte.
    pub fn read_feature(&self) -> Result<[u8; BUFFER_LEN], DeviceError> {
        self.prueft_offen()?;
        let laenge = self.berichtslaenge.max(BUFFER_LEN);
        let mut puffer = vec![0u8; laenge];
        // sicher: der Griff gehoert dieser Structur und ist gueltig, der Puffer
        // ist mindestens so lang wie die angegebene Laenge, und sein erstes
        // Byte (Berichtskennung 0) ist durch das Nullfuellen gesetzt.
        let bekommen = unsafe {
            ffi::HidD_GetFeature(
                self.griff,
                puffer.as_mut_ptr().cast::<c_void>(),
                laenge as u32,
            )
        };
        if !ffi::gelungen(bekommen) {
            return Err(ausfall("Lesen des Statusberichts"));
        }
        let mut bericht = [0u8; BUFFER_LEN];
        // sicher: der Puffer ist mit Absicht mindestens `BUFFER_LEN` Byte lang.
        bericht.copy_from_slice(&puffer[..BUFFER_LEN]);
        Ok(bericht)
    }

    /// Neun Byte zurueck auf das Geraet, bis zur Berichtslaenge des Geraets mit
    /// Nullen aufgefuellt.
    pub fn write_feature(&self, bericht: &[u8; BUFFER_LEN]) -> Result<(), DeviceError> {
        self.prueft_offen()?;
        let laenge = self.berichtslaenge;
        if laenge < BUFFER_LEN {
            // Ohne die sieben Koerperbyte, das fuehrende Nullbyte und die
            // Summe laesst sich nichts hinschreiben; die Python-Fassung lehnt
            // an derselben Stelle ebenso.
            return Err(DeviceError::NotFound(format!(
                "Der Kuehler meldet nur {laenge} Byte Berichtslaenge, noetig sind {BUFFER_LEN}."
            )));
        }
        let mut puffer = vec![0u8; laenge];
        // sicher: `laenge >= BUFFER_LEN` ist direkt darueber geprueft.
        puffer[..BUFFER_LEN].copy_from_slice(bericht);
        // sicher: gueltiger Griff, Puffer lang genug, das erste Byte ist die
        // Berichtskennung 0.
        let bekommen = unsafe {
            ffi::HidD_SetFeature(
                self.griff,
                puffer.as_mut_ptr().cast::<c_void>(),
                laenge as u32,
            )
        };
        if !ffi::gelungen(bekommen) {
            return Err(ausfall("Schreiben auf den Kuehler"));
        }
        Ok(())
    }

    /// Ein Eingangsbericht, oder nichts, wenn das Geraet schweigt.
    ///
    /// Das Geraet kennt Eingangsberichte mit 64 Byte, in denen nichts
    /// Bekanntes steckt; gebraucht wird das nur fuer die Firmwareanfrage. Der
    /// Arbeitsgriff ist synchron, und ein synchrones `ReadFile` wuerde bis zum
    /// Abzug des Steckers sitzen - fuer diese eine Lesung wird deshalb ein
    /// zweiter Griff mit Ueberlappungsarbeit geoeffnet und auf sein Ereignis
    /// gewartet. Bestens wie unter Linux: nichts gekommen ist keine
    /// Fehlmeldung. Unter Linux kennt uebrigens nur dieses Backend
    /// Eingabemeldungen, Windows kennt sie mit diesem Aufruf.
    pub fn read_input(&self, timeout: Duration) -> Result<Option<Vec<u8>>, DeviceError> {
        self.prueft_offen()?;
        let groesse = self.eingabe_laenge.max(EINGABERUECKFALL);
        // Der zweite Griff ist Absicht (siehe oben). Bekommt man ihn nicht -
        // etwa weil ein anderes Programm exclusiv haelt -, ist die Antwort
        // "nichts gekommen" und nicht "fehler".
        let leser = match offnen(&self.node, true) {
            Ok(griff) => griff,
            Err(DeviceError::NotFound(_)) | Err(DeviceError::Io(_)) => return Ok(None),
            Err(fehler) => return Err(fehler),
        };
        // sicher: der Griff ist frisch geoeffnet und wird beim Untergehen des
        // Wuertergnaues genau einmal geschlossen.
        let arbeit = Ueberlappungsarbeit { leser };
        Ok(arbeit.lese(groesse, timeout))
    }

    /// Der Produktname, wie das Geraet ihn nennt - fuer Aufzaehlungen, nicht
    /// fuer die Erkennung (Grund: siehe Modul-Kopftext).
    pub fn product_name(&self) -> Option<String> {
        if !self.offen {
            return None;
        }
        let mut puffer = vec![0u16; 128]; // 256 Byte, wie die Python-Fassung
                                          // sicher: gueltiger Griff, und der Puffer fasst die angegebene Byte-
                                          // zahl; gelesen wird nur bis zum Abschlusszeichen.
        if !ffi::gelungen(unsafe {
            ffi::HidD_GetProductString(
                self.griff,
                puffer.as_mut_ptr().cast::<c_void>(),
                (puffer.len() * size_of::<u16>()) as u32,
            )
        }) {
            return None;
        }
        let ende = puffer.iter().position(|&z| z == 0).unwrap_or(puffer.len());
        let text = String::from_utf16_lossy(&puffer[..ende]);
        let text = text.trim().to_owned();
        (!text.is_empty()).then_some(text)
    }

    /// Abschalten: mehrfach aufrufen ist erlaubt.
    pub fn close(&mut self) {
        if self.offen {
            // sicher: der Griff wurde von `CreateFileW` erzeugt und ist noch
            // nicht geschlossen; `offen` wird unmittelbar danach gesetzt.
            unsafe { ffi::CloseHandle(self.griff) };
            self.offen = false;
        }
    }

    fn prueft_offen(&self) -> Result<(), DeviceError> {
        if self.offen {
            Ok(())
        } else {
            Err(DeviceError::Closed)
        }
    }
}

impl Drop for Handle {
    fn drop(&mut self) {
        self.close();
    }
}

/// Der Betriebssystemgriff gilt prozessweit, und geschlossen wird genau
/// einmal - der `offen`-Schalter hindert ein zweites Mal daran.
///
/// Die Annahme ist dieselbe, die unter Linux fuer einen Dateidescriptor gilt:
/// Der Griff gehoert diesem Prozess, und keine zweite Structur schliesst ihn.
unsafe impl Send for Handle {}

/// Der zweite Griff fuer Eingabemeldungen; beim Untergehen wird er geschlossen.
struct Ueberlappungsarbeit {
    leser: ffi::Griff,
}

impl Ueberlappungsarbeit {
    /// Eine Eingabemeldung, oder `None`, wenn nichts angekommen ist.
    fn lese(&self, groesse: usize, timeout: Duration) -> Option<Vec<u8>> {
        let mut puffer = vec![0u8; groesse];
        let mut ueberlappt = ffi::Overlapped::default();
        // sicher: das Ereignis gehoert bis zum `CloseHandle` weiter unten diese
        // Funktion, und solange bleibt auch die Ueberlappungsstruktur am Leben.
        // Die beiden Nullen: von selbst zurueckgesetzt, anfangs nicht gesetzt.
        let ereignis = unsafe { ffi::CreateEventW(ptr::null_mut(), 0, 0, ptr::null()) };
        if ereignis.is_null() {
            return None; // kein Ereignis, also auch keine asynchrone Lesung
        }
        ueberlappt.hEvent = ereignis;

        let mut getan = 0u32;
        // sicher: Griff, Puffer, Ueberlappungsstruktur und Ereignis gehoeren
        // zusammen und bleiben bis zum Abschluss (oder zur Abbestellung) hier.
        let gelesen = unsafe {
            ffi::ReadFile(
                self.leser,
                puffer.as_mut_ptr().cast::<c_void>(),
                groesse as u32,
                &mut getan,
                &mut ueberlappt,
            )
        };
        let fehler = io::Error::last_os_error();

        let fertig = if gelesen != 0 {
            // Das Geraet hat schon erfuellt. Die Ueberlappungsstruktur gilt in
            // diesem Fall als unbestimmt und wird nicht ausgewertet; die Zahl
            // der Byte steht in `getan`.
            true
        } else if fehler.raw_os_error().unwrap_or(0) == ffi::ERROR_IO_PENDING {
            let milli = u32::try_from(timeout.as_millis())
                .unwrap_or(u32::MAX)
                .max(50);
            // sicher: das Ereignis ist ein gueltiges Objekt dieses Prozesses.
            let angekommen =
                unsafe { ffi::WaitForSingleObject(ereignis, milli) } == ffi::WAIT_OBJECT_0;
            if !angekommen {
                // sicher: abbestellt wird nur die Arbeit dieses Griffes, die
                // von diesem Thread aus begonnen wurde.
                unsafe { ffi::CancelIo(self.leser) };
                false
            } else {
                // sicher: die Arbeit ist beendet, die Zahl darf abgeholt
                // werden; ohne erneutes Warten, das Ereignis sagt es schon.
                (unsafe { ffi::GetOverlappedResult(self.leser, &mut ueberlappt, &mut getan, 0) })
                    != 0
            }
        } else {
            false
        };

        // sicher: das Ereignis gehoert dieser Funktion und wird genau einmal
        // geschlossen.
        unsafe { ffi::CloseHandle(ereignis) };

        if !fertig || (getan as usize) > groesse {
            return None;
        }
        puffer.truncate(getan as usize);
        Some(puffer)
    }
}

impl Drop for Ueberlappungsarbeit {
    fn drop(&mut self) {
        // sicher: der Griff stammt aus `CreateFileW` und wird hier genau einmal
        // geschlossen; eine laufende Arbeit hat der Benutzer vorher abbestellt.
        unsafe { ffi::CloseHandle(self.leser) };
    }
}

/// Wohin ein fehlgeschlagener Bericht gehoert: abgezogen wie `abzug()` unter
/// Linux, damit "Stecher weg" und "kein Zugriff" verschiedene Antworten sind.
fn ausfall(meldung: &str) -> DeviceError {
    let fehler = io::Error::last_os_error();
    match fehler.raw_os_error().unwrap_or(0) {
        ffi::ERROR_GEN_FAILURE
        | ffi::ERROR_DEVICE_NOT_AVAILABLE
        | ffi::ERROR_FILE_NOT_FOUND
        | ffi::ERROR_PATH_NOT_FOUND => DeviceError::Detached,
        ffi::ERROR_ACCESS_DENIED => DeviceError::NotFound(format!(
            "{meldung} nicht moeglich, kein Zugriff. {PERMISSION_HINT_WINDOWS}"
        )),
        _ => DeviceError::Io(fehler),
    }
}

// ---------------------------------------------------------------- pruefung---

/// Die Layouts sind der eine Ort, an dem ein Vertipper laut werden muss: Auf
/// einem Windows-Rechner mit anderem Layout stimmt entweder ein Aufruf nicht
/// oder das Geraet antwortet nicht. Deshalb steht hier jede Groesse, die auch
/// die Windows-Header festschreiben. Diese Pruefungen laufen nur auf dem
/// Windows-Ziel - die ganze Datei wird dafuer gebaut.
#[cfg(test)]
mod tests {
    use super::*;

    fn griff_test(offen: bool, berichtslaenge: usize) -> Handle {
        Handle {
            // Absichtlich kein echter Griff: diese Pruefungen halten den
            // Weg *vor* dem ersten Zugriff auf das Geraet fest.
            griff: ffi::INVALID_HANDLE_VALUE,
            node: PathBuf::from(r"\\?\hid#vid_374a&pid_b101#0#0000"),
            berichtslaenge,
            eingabe_laenge: 65,
            offen,
        }
    }

    #[test]
    fn die_groessen_der_header_stimmen() {
        assert_eq!(size_of::<ffi::Guid>(), 16);
        assert_eq!(size_of::<ffi::SpDeviceInterfaceData>(), 32);
        assert_eq!(size_of::<ffi::SpDeviceInterfaceDetailDataW>(), 8);
        assert_eq!(size_of::<ffi::HiddAttributes>(), 12);
        assert_eq!(size_of::<ffi::HidpCaps>(), 64);
        assert_eq!(size_of::<ffi::Overlapped>(), 24);
    }

    #[test]
    fn die_groessenangaben_sind_die_der_header() {
        // Diese beiden darf man verwechseln, und genau deshalb stehen sie hier
        // getrennt: Die Structur ist 8 Byte, verlangt wird auf 64 Bit
        // derselbe Wert, auf 32 Bit aber 6.
        assert_eq!(size_of::<ffi::SpDeviceInterfaceDetailDataW>(), 8);
        if cfg!(target_pointer_width = "64") {
            assert_eq!(DETAIL_CBGROESSE, 8);
        } else {
            assert_eq!(DETAIL_CBGROESSE, 6);
        }
        let kopf = ffi::SpDeviceInterfaceData::default();
        assert_eq!(kopf.cbSize, size_of::<ffi::SpDeviceInterfaceData>() as u32);
        let attribute = ffi::HiddAttributes::default();
        assert_eq!(attribute.Size, size_of::<ffi::HiddAttributes>() as u32);
    }

    #[test]
    fn das_ereignis_steht_an_der_stelle_des_headers() {
        // Hinter dem geteilten Feld: auf 64 Bit an Stelle 16, auf 32 Bit an
        // Stelle 12. Die Python-Fassung schreibt an Stelle 32.
        let ueberlappt = ffi::Overlapped::default();
        let anfang = &ueberlappt as *const _ as usize;
        let stelle = &ueberlappt.hEvent as *const _ as usize;
        let erwartet = if cfg!(target_pointer_width = "64") {
            16
        } else {
            12
        };
        assert_eq!(stelle - anfang, erwartet);
    }

    #[test]
    fn ein_schnittstellenpfad_wird_erkannt() {
        let pfad = Path::new(
            r"\\?\hid#vid_374a&pid_b101&mi_00#7&2c1e&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}",
        );
        assert!(passt_zum_kuehler(pfad, 0x374A, 0xB101));
        assert!(!passt_zum_kuehler(pfad, 0x374A, 0xB102));
        assert!(!passt_zum_kuehler(
            Path::new(r"\\?\hid#vid_045e&pid_b101#1&0#0000"),
            0x374A,
            0xB101
        ));
        // Die Produktkennung *vor* der Herstellerkennung zaehlt nicht.
        assert!(!passt_zum_kuehler(
            Path::new(r"\\?\hid#pid_b101&vid_374a#1&0#0000"),
            0x374A,
            0xB101
        ));
    }

    #[test]
    fn jeder_pfad_bekommt_sein_abschlusszeichen() {
        let weit = verbreitern(Path::new(r"\\?\hid#vid_374a")).unwrap();
        assert_eq!(*weit.last().unwrap(), 0);
        assert!(!weit[..weit.len() - 1].contains(&0));
    }

    #[test]
    fn ein_pfad_mit_nullzeichen_wird_abgelehnt() {
        let kaputt = PathBuf::from(std::ffi::OsString::from_wide(&[0x5c, 0x00, 0x3f]));
        assert!(verbreitern(&kaputt).is_err());
    }

    #[test]
    fn ein_geschlossener_griff_weigert_sich() {
        let mut griff = griff_test(false, BUFFER_LEN);
        assert!(matches!(griff.read_feature(), Err(DeviceError::Closed)));
        assert!(matches!(
            griff.write_feature(&[0u8; BUFFER_LEN]),
            Err(DeviceError::Closed)
        ));
        assert!(!griff.is_open());
        griff.close(); // mehrfach aufrufen ist erlaubt
        assert!(!griff.is_open());
    }

    #[test]
    fn ein_zu_kurzer_bericht_wird_abgewiesen() {
        let mut griff = griff_test(true, BUFFER_LEN - 1);
        // Der Griff wird nicht angefasst: vorher ist die Laenge dran.
        let ergebnis = griff.write_feature(&[0u8; BUFFER_LEN]);
        assert!(
            matches!(&ergebnis, Err(DeviceError::NotFound(meldung))
                      if meldung.contains("Berichtslaenge")),
            "stattdessen: {ergebnis:?}"
        );
        griff.close();
    }

    #[test]
    fn nichts_gefunden_ist_kein_fehler() {
        // Ohne eingesteckten Kuehler ist die Liste leer, und ein erfundener
        // Pfad wird abgelehnt - beides ohne Geraet in der Testumgebung pruefbar.
        for pfad in find_paths(0x374A, 0xB101) {
            assert!(passt_zum_kuehler(&pfad, 0x374A, 0xB101));
        }
        let ergebnis = open_path(Path::new(r"\\?\hid#vid_374a&pid_b101#0#0000000000000000"));
        assert!(ergebnis.is_err(), "ein erfundener Pfad muss ablehnen");
    }

    #[test]
    fn ohne_wissen_gelten_die_vorschlaege() {
        assert_eq!(vorgeschlagen(0, BERICHTSRUECKFALL), BUFFER_LEN);
        assert_eq!(vorgeschlagen(64, EINGABERUECKFALL), 64);
    }
}

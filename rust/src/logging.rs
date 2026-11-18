//! Die Protokollzeilen des Dienstes - dieselben, die `llano daemon` schreibt.
//!
//! Wer den Dienst startet, liest mit: `journalctl`, eine Konsole, ein
//! Terminalfenster. Deshalb ist das Format nicht neu erfunden, sondern das der
//! Python-Fassung (`%H:%M:%S PEGEL   Text`), damit beide Fassungen in
//! derselben Datei und vor denselben Augen gleich aussehen.

use std::io::Write;

/// Der Pegel, den die Python-Fassung fuer Meldungen dieser Art benutzt.
pub const INFO: &str = "INFO";
/// Und fuer die, die einen Grund haben, nachzusehen.
pub const WARN: &str = "WARNING";

/// Eine Zeile auf dem Fehlerkanal, damit `llano-rs daemon ... > protokoll.txt`
/// die Meldungen nicht mit den Ausgaben vermischt.
pub fn zeile(pegel: &str, text: &str) {
    let stderr = std::io::stderr();
    let mut griff = stderr.lock();
    // Ein kaputtes Terminal darf einen kuehlenden Lüfter nicht zum Stehen
    // bringen; deshalb wird ein Schreibfehler hier ignoriert.
    let _ = writeln!(griff, "{} {:<7} {}", uhrzeit(), pegel, text);
}

/// Stunde, Minute, Sekunde wie in der Python-Fassung - in der Ortszeit des
/// Rechners, weil Menschen die Zeilen lesen.
#[cfg(unix)]
pub fn uhrzeit() -> String {
    let sekunden = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|frist| frist.as_secs() as libc::time_t)
        .unwrap_or(0);
    let mut zeit = libc::tm {
        tm_sec: 0,
        tm_min: 0,
        tm_hour: 0,
        tm_mday: 0,
        tm_mon: 0,
        tm_year: 0,
        tm_wday: 0,
        tm_yday: 0,
        tm_isdst: 0,
        tm_gmtoff: 0,
        tm_zone: std::ptr::null(),
    };
    // `localtime_r` ist die ablaufssichere Variante und braucht keinen Puffer,
    // den zwei Threads zugleich anfassen.
    unsafe { libc::localtime_r(&sekunden, &mut zeit) };
    format!("{:02}:{:02}:{:02}", zeit.tm_hour, zeit.tm_min, zeit.tm_sec)
}

/// Die Windows-Uhr: `GetLocalTime` fuellt diese sechzehn Bayt, fertig.
///
/// Der erste Versuch lief ueber `localtime_s`, und der Windows-Bauwagen
/// meldete einen nicht aufloesbaren Namen. `localtime_s` ist naemlich keine
/// exportierte Funktion, sondern ein Vorgang im Header, der je nach
/// Voreinstellung auf `_localtime64_s` hinauslaeuft - und die Struktur dahinter
/// ist die des C-Bausatzes, deren Felder hier niemand nachzaehlen will.
/// `GetLocalTime` gehoert zu kernel32, ist in der Header-Sammlung dokumentiert
/// und nennt Stunde, Minute und Sekunde in dieser Reihenfolge.
#[cfg(not(unix))]
pub fn uhrzeit() -> String {
    let mut zeit = Ortszeit::leer();
    unsafe { GetLocalTime(&mut zeit) };
    format!("{:02}:{:02}:{:02}", zeit.stunde, zeit.minute, zeit.sekunde)
}

#[cfg(not(unix))]
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Ortszeit {
    jahr: u16,
    monat: u16,
    wochentag: u16,
    tag: u16,
    stunde: u16,
    minute: u16,
    sekunde: u16,
    tausendstel: u16,
}

#[cfg(not(unix))]
impl Ortszeit {
    fn leer() -> Self {
        Self {
            jahr: 0,
            monat: 0,
            wochentag: 0,
            tag: 0,
            stunde: 0,
            minute: 0,
            sekunde: 0,
            tausendstel: 0,
        }
    }
}

#[cfg(not(unix))]
extern "system" {
    fn GetLocalTime(zeit: *mut Ortszeit);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn die_uhrzeit_hat_die_form_der_python_fassung() {
        let text = uhrzeit();
        let ziffern: Vec<char> = text.chars().collect();
        assert_eq!(ziffern.len(), 8, "erwartet HH:MM:SS, bekommen {text}");
        assert_eq!(ziffern[2], ':');
        assert_eq!(ziffern[5], ':');
        assert!(ziffern
            .iter()
            .enumerate()
            .all(|(stelle, ziffer)| stelle == 2 || stelle == 5 || ziffer.is_ascii_digit()));
    }

    #[cfg(not(unix))]
    #[test]
    fn die_ortszeit_ist_sechzehn_bayt() {
        // SYSTEMTIME: acht Kurzahlen, ohne Polsterung, in der Reihenfolge des
        // Headers. Wer die Felder umhaengt, kriegt Minuten in der Stunde.
        assert_eq!(std::mem::size_of::<Ortszeit>(), 16);
    }

    #[test]
    fn der_pegel_wie_bisher_gefuellt() {
        assert_eq!(format!("{:<7}", INFO), "INFO   ");
        assert_eq!(format!("{:<7}", WARN), "WARNING");
    }
}

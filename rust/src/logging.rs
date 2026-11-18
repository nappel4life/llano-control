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
pub fn uhrzeit() -> String {
    let sekunden = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|frist| frist.as_secs() as libc::time_t)
        .unwrap_or(0);
    zerlege(sekunden)
}

#[cfg(unix)]
fn zerlege(sekunden: libc::time_t) -> String {
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

#[cfg(not(unix))]
fn zerlege(sekunden: libc::time_t) -> String {
    // `localtime_s` will das Ergebnis zuerst und die Quelle danach; es gibt eine
    // Fehlerzahl zurueck statt zu zeigen, wenn etwas nicht passt. Ohne Erfolg
    // bleibt immerhin die Weltzeit, die immer noch besser ist als nichts.
    let mut zeit: libc::tm = unsafe { std::mem::zeroed() };
    let quellzeit = sekunden;
    let erfolg = unsafe { localtime_s(&mut zeit, &quellzeit) };
    if erfolg != 0 {
        let tage = sekunden.div_euclid(86_400).rem_euclid(86_400);
        return format!("{:02}:{:02}:{:02}", tage / 3600, tage / 60 % 60, tage % 60);
    }
    format!("{:02}:{:02}:{:02}", zeit.tm_hour, zeit.tm_min, zeit.tm_sec)
}

#[cfg(not(unix))]
extern "system" {
    fn localtime_s(aus: *mut libc::tm, quelle: *const libc::time_t) -> i32;
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

    #[test]
    fn der_pegel_wie_bisher_gefuellt() {
        assert_eq!(format!("{:<7}", INFO), "INFO   ");
        assert_eq!(format!("{:<7}", WARN), "WARNING");
    }
}

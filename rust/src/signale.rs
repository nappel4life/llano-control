//! Auf das Ende hoeren, ohne den Lüfter dabei zu vergessen.
//!
//! Abmelden und Herunterfahren schicken `SIGTERM`, im Terminal drückt jemand
//! `Strg+C`. Ein Dienst, der dabei einfach stirbt, lässt einen Kühlpad stehen,
//! der gerade auf einer Stufe läuft, die nur für diesen einen Moment galt - die
//! Python-Fassung schaltet in dem Fall aus, und dasselbe erwartet hier jemand,
//! der beide Fassungen benutzt.
//!
//! Rust kann Signale nicht in einer Schleife "abholen"; ein Handler setzt
//! deshalb nur ein Flag, und der Dienst prüft es zwischen den Runden. Der
//! Dienst schläft in kleinen Stücken, damit ein Signal nach höchstens einer
//! Viertelsekunde ankommt - so lang wartet auch die Python-Fassung.

use std::sync::atomic::{AtomicBool, Ordering};

static BEENDET: AtomicBool = AtomicBool::new(false);

/// Jemand hat beendet wollen.
pub fn beendet() -> bool {
    BEENDET.load(Ordering::SeqCst)
}

/// Vergessen, dass jemand beendet wollte - für die Prüfungen.
pub fn zuruecksetzen() {
    BEENDET.store(false, Ordering::SeqCst);
}

/// Die Handler einsetzen. Unter Windows gibt es `SIGTERM` nicht in dieser
/// Form; dort sorgt die Konsole selbst für das Ende, und der Dienst merkt es
/// am geschlossenen Fenster - ein Hinweis in der Doku, mehr nicht.
#[cfg(unix)]
pub fn hoeren() {
    extern "C" fn merke(_nummer: i32) {
        // Ein Signalhandler darf fast nichts: ein Flag setzen ist das
        // Vertrauenswuerdigste, was hier bleibt.
        BEENDET.store(true, Ordering::SeqCst);
    }
    unsafe {
        libc::signal(libc::SIGTERM, merke as *const () as libc::sighandler_t);
        libc::signal(libc::SIGINT, merke as *const () as libc::sighandler_t);
    }
}

/// Ohne dieses Signal: Der Dienst laeuft, bis er von aussen beendet wird.
#[cfg(not(unix))]
pub fn hoeren() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ein_merkmal_und_nichts_dazwischen() {
        zuruecksetzen();
        assert!(!beendet());
        BEENDET.store(true, Ordering::SeqCst);
        assert!(
            beendet(),
            "ein gesetztes Signal darf nicht ueberhoert werden"
        );
        zuruecksetzen();
        assert!(!beendet());
    }
}

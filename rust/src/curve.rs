//! Die Lüfterkurve: geradlinig zwischen den Punkten, mit einem Verzug beim
//! Herunter.
//!
//! Die Herstelleranwendung verbindet die Stützstellen geradlinig und rundet das
//! Ergebnis; genau das ist [`interpolieren`], bitgleich zur Python-Fassung, weil
//! beide dasselbe Rundungsverfahren benutzen. Das ist hier kein Detail: Python
//! rundet zur nächsten geraden Zahl, wenn es genau in der Mitte liegt
//! (`round(0.5) == 0`, `round(1.5) == 2`), Rust würde von Haus aus von der Null
//! wegrunden. Ein Punkt auf der halben Prozentstufe würde sonst in der einen
//! Fassung eine Stufe höher landen als in der anderen - und niemand fände es.
//!
//! Obendrauf sitzt [`Kurvenfolger`]: Ein Lüfter, der an einer Stützstelle
//! auf und ab pumpt, nervt mehr als einer, der kurz wärmer bleibt. Deshalb darf
//! die Stufe sofort hoch, aber erst wieder herunter, wenn die Temperatur um
//! [`Einstellungen::hysterese`](config::Einstellungen::hysterese) Grad unter den
//! Punkt gefallen ist, der die Erhöhung ausgelöst hat.

use crate::config::Punkt;

/// Die Stufe, die die Kurve für diese Temperatur vorgibt.
///
/// Ohne Punkte gibt es nichts zu fragen; die Aufrufer haben dann die
/// Standardkurve eingesetzt, [`kurve_oder_standard`](config::kurve_oder_standard)
/// sorgt dafür, dass diese nie leer ankommt.
pub fn interpolieren(kurve: &[Punkt], grad: f64) -> Option<u8> {
    if kurve.is_empty() {
        return None;
    }
    let erste = kurve.first()?;
    let letzte = kurve.last()?;
    if grad <= erste.0 {
        return begrenzt(erste.1 as f64).ok();
    }
    if grad >= letzte.0 {
        return begrenzt(letzte.1 as f64).ok();
    }
    for paar in kurve.windows(2) {
        let (start, ende) = (paar[0], paar[1]);
        if start.0 <= grad && grad < ende.0 {
            if ende.0 == start.0 {
                return begrenzt(start.1 as f64).ok();
            }
            let anteil = (grad - start.0) / (ende.0 - start.0) * (ende.1 - start.1) as f64;
            return begrenzt(start.1 as f64 + anteil).ok();
        }
    }
    begrenzt(letzte.1 as f64).ok()
}

/// Auf eine Stufe zwischen 1 und 100 bringen, mit dem Runden der Python-Fassung.
fn begrenzt(stufe: f64) -> Result<u8, ()> {
    let gerundet = stufe.round_ties_even();
    if !gerundet.is_finite() {
        return Err(());
    }
    Ok(gerundet_klemmen(gerundet))
}

fn gerundet_klemmen(gerundet: f64) -> u8 {
    // Python: max(1, min(100, int(round(x))))
    gerundet.clamp(1.0, 100.0) as u8
}

/// Aus einer Folge von Temperaturen eine Folge von Stufen machen.
#[derive(Debug, Clone)]
pub struct Kurvenfolger {
    kurve: Vec<Punkt>,
    hysterese: f64,
    angewandt: Option<u8>,
    anker: Option<f64>,
}

impl Kurvenfolger {
    /// Mit derselben Kurve anfangen, die auch in der Datei steht.
    pub fn neu(kurve: &[Punkt], hysterese: f64) -> Self {
        Self {
            kurve: kurve.to_vec(),
            hysterese,
            angewandt: None,
            anker: None,
        }
    }

    /// Die Stufe, die für diese Messung jetzt gilt.
    pub fn aktualisieren(&mut self, grad: f64) -> u8 {
        let ziel = interpolieren(&self.kurve, grad).unwrap_or(1);
        let halten = match (self.angewandt, self.anker) {
            // Die erste Messung setzt beides.
            (None, _) | (_, None) => true,
            // Lauter ist sofort erlaubt.
            (Some(bisher), _) => ziel > bisher,
        };
        let tiefer = self
            .anker
            .is_some_and(|punkt| grad <= punkt - self.hysterese);
        if halten || tiefer {
            self.angewandt = Some(ziel);
            self.anker = Some(grad);
        }
        self.angewandt.unwrap_or(1)
    }

    /// Die Kurve hat sich geändert; der alte Anker gilt nicht mehr.
    pub fn neu_verbinden(&mut self, kurve: &[Punkt], hysterese: f64) {
        self.kurve = kurve.to_vec();
        self.hysterese = hysterese;
        self.zuruecksetzen();
    }

    /// Vergessen, was zuletzt galt - nach einem Neustart des Geräts zum Beispiel.
    pub fn zuruecksetzen(&mut self) {
        self.angewandt = None;
        self.anker = None;
    }

    /// Die Stufe, die beim letzten Aufruf herauskam, ohne eine neue Messung.
    pub fn letzter_vorschlag(&self) -> Option<u8> {
        self.angewandt
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kurve() -> Vec<Punkt> {
        vec![
            (45.0, 20),
            (55.0, 35),
            (65.0, 50),
            (75.0, 70),
            (85.0, 90),
            (92.0, 100),
        ]
    }

    #[test]
    fn ausserhalb_der_punkte_gilt_der_naechste_endwert() {
        let kurve = kurve();
        assert_eq!(interpolieren(&kurve, 20.0), Some(20));
        assert_eq!(interpolieren(&kurve, 45.0), Some(20));
        assert_eq!(interpolieren(&kurve, 200.0), Some(100));
        assert_eq!(interpolieren(&[], 60.0), None);
    }

    #[test]
    fn zwischen_den_punkten_geradlinig() {
        let kurve = kurve();
        assert_eq!(interpolieren(&kurve, 50.0), Some(28));
        assert_eq!(interpolieren(&kurve, 55.0), Some(35));
        assert_eq!(interpolieren(&kurve, 60.0), Some(42));
        assert_eq!(interpolieren(&kurve, 90.0), Some(97));
    }

    #[test]
    fn die_halbe_stufe_rundet_wie_python() {
        // 25,5 -> 26, 26,5 -> 26: Python rundet zur geraden Zahl. Wuerde diese
        // Fassung von der Null weg runden, waere das zweite 27.
        let kurve = vec![(40.0, 25), (42.0, 28)];
        assert_eq!(interpolieren(&kurve, 40.5), Some(26), "25,75");
        assert_eq!(interpolieren(&kurve, 41.0), Some(26), "26,5 -> gerade");
        assert_eq!(interpolieren(&kurve, 41.5), Some(27), "27,25");
        let gerade = vec![(40.0, 26), (42.0, 27)];
        assert_eq!(interpolieren(&gerade, 41.0), Some(26), "26,5 -> gerade");
    }

    #[test]
    fn laut_sofort_leise_erst_viel_spaeter() {
        let mut folger = Kurvenfolger::neu(&kurve(), 3.0);
        assert_eq!(folger.aktualisieren(60.0), 42, "erste Messung gilt");
        assert_eq!(folger.aktualisieren(70.0), 60, "waerder: sofort hoch");
        assert_eq!(
            folger.aktualisieren(68.0),
            60,
            "zwei Grad tiefer reicht nicht zum Herunter"
        );
        assert_eq!(folger.aktualisieren(66.0), 52, "vier Grad tiefer sehr wohl");
        assert_eq!(folger.letzter_vorschlag(), Some(52));
    }

    #[test]
    fn ein_neuer_anker_vergisst_das_bisherige() {
        let mut folger = Kurvenfolger::neu(&kurve(), 3.0);
        folger.aktualisieren(80.0);
        folger.zuruecksetzen();
        assert_eq!(folger.letzter_vorschlag(), None);
        assert_eq!(folger.aktualisieren(45.0), 20, "von vorn angefangen");
    }

    #[test]
    fn eine_neue_kurve_wird_ohne_altlast_uebernommen() {
        let mut folger = Kurvenfolger::neu(&kurve(), 3.0);
        folger.aktualisieren(85.0);
        folger.neu_verbinden(&[(40.0, 5), (50.0, 10)], 1.0);
        assert_eq!(folger.letzter_vorschlag(), None);
        assert_eq!(folger.aktualisieren(50.0), 10);
    }

    #[test]
    fn ohne_hysterese_darf_es_sofort_wieder_runter() {
        let mut folger = Kurvenfolger::neu(&kurve(), 0.0);
        folger.aktualisieren(75.0);
        assert_eq!(folger.aktualisieren(60.0), 42);
    }
}

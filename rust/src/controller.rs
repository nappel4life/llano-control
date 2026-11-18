//! Die Steuerung: aus Temperaturen eine Lüfterstufe machen, ohne dem Gerät
//! auf die Füße zu treten.
//!
//! Das ist das Gegenstück zu `llanotool/loop.py`. Übernommen ist nicht die
//! Form, sondern das Verhalten - inklusive dreier Dinge, die am Gerät abgelesen
//! sind und die sich nicht ausdenken lassen:
//!
//! 1. Jeder Bericht trägt die Beleuchtung mit. Wer nur die Stufe schreibt,
//!    löscht Farbe und Effekt; deshalb wird immer beides geschickt.
//! 2. Das Gerät kennt keine Regelung für zwei Absender. Ein zweiter Prozess
//!    schreibt dieselben Bytes anders zurück, und beide verlieren. Deshalb hält
//!    die [Sperrdatei](crate::lock) alles vom Gerät fern, was nicht der Dienst
//!    ist, und die [Oberfläche](crate::lock::erwerben) merkt sich dasselbe.
//! 3. Das Schreiben selbst kostet das Gerät nichts, aber ein Lüfter, der bei
//!    jeder Messung umschaltet, ist hörbar. Deshalb zwei Hürden: genug
//!    Unterschied und genug Abstand seit dem letzten Bericht.
//!
//! Was fehlt, ist das Fenster - das bleibt in Qt und spricht dieselbe
//! [Einstellungsdatei](crate::config) an.

use std::collections::BTreeMap;
use std::path::Path;
use std::time::{Duration, Instant};

use crate::config::{self, Einstellungen, Punkt};
use crate::curve::{self, Kurvenfolger};
use crate::device::{DeviceError, Pad};
use crate::lock::Sperre;
use crate::logging;
use crate::protocol::Lighting;
use crate::protocol::State;
use crate::sensors;

/// So lange lässt die Steuerung das Gerät in Ruhe, nachdem es nicht geantwortet
/// hat - wie die Python-Fassung.
const WIEDER_VERBINDEN_NACH: Duration = Duration::from_secs(5);

/// Was ein Umlauf ergeben hat; die Kommandozeile und das Protokoll leben davon.
#[derive(Debug, Clone)]
pub struct Umlauf {
    /// War das Gerät ansprechbar?
    pub verbunden: bool,
    /// Der Weg, über den es gesprochen hat.
    pub knoten: Option<String>,
    /// Die Temperatur, nach der die Kurve sich gerichtet hat.
    pub bezug: Option<f64>,
    /// Alle Messstellen, die der Rechner hergab.
    pub temperaturen: BTreeMap<String, f64>,
    /// Die Stufe, die die Kurve verlangt.
    pub ziel: Option<u8>,
    /// Was das Gerät zuletzt zurückgemeldet hat.
    pub bericht: Option<State>,
    /// `auto` oder etwas anderes.
    pub modus: String,
    /// Die letzte Meldung des Geräts, falls es eine gab.
    pub fehler: Option<String>,
}

/// Besitzer des Geräts, der Temperaturen und der Einstellungen.
pub struct Steuerung {
    /// Der Stand, mit dem gerade gearbeitet wird.
    pub einstellungen: Einstellungen,
    /// Ein bestimmter Gerätweg, statt selbst zu suchen. Die Kommandozeile
    /// bietet `--node` an, und die Prüfungen setzen einen Weg, den es nicht
    /// gibt - sonst würde eine Prüfung auf dem Rechner eines Entwicklers
    /// plotting am echten Kühler machen.
    pub knoten_wunsch: Option<std::path::PathBuf>,
    folger: Kurvenfolger,
    pad: Option<Pad>,
    wieder_ab: Option<Instant>,
    letzter_bericht: Option<State>,
    ziel: Option<u8>,
    letzte_schreibzeit: Option<Instant>,
    licht_stand: Option<(bool, u8, u8, u8, u8)>,
    temperaturen: BTreeMap<String, f64>,
    fehler: Option<String>,
}

impl Steuerung {
    /// Eine Steuerung, die noch nichts gesehen hat.
    pub fn neu(einstellungen: Einstellungen) -> Self {
        let folger = Kurvenfolger::neu(&einstellungen.kurve, einstellungen.hysterese);
        Self {
            einstellungen,
            knoten_wunsch: None,
            folger,
            pad: None,
            wieder_ab: None,
            letzter_bericht: None,
            ziel: None,
            letzte_schreibzeit: None,
            licht_stand: None,
            temperaturen: BTreeMap::new(),
            fehler: None,
        }
    }

    /// Das Gerät, wenn es zu erreichen ist.
    ///
    /// Ein Fehlversuch wird nicht wiederholt, sondern in fünf Sekunden erneut
    /// versucht: Ein Kühlpad, das gerade ein- oder ausgesteckt wird, darf ein
    /// Programm nicht in eine Endlosschleife aus Fehlermeldungen stürzen.
    pub fn verbinden(&mut self) -> bool {
        if self.pad.is_some() {
            return true;
        }
        if self.wieder_ab.is_some_and(|zeit| Instant::now() < zeit) {
            return false;
        }
        match Pad::open(self.knoten_wunsch.as_deref()) {
            Ok(pad) => {
                logging::zeile(
                    logging::INFO,
                    &format!("gekoppelt an {}", pad.node().display()),
                );
                self.pad = Some(pad);
                self.folger.zuruecksetzen();
                self.licht_stand = None;
                self.wieder_ab = None;
                self.fehler = None;
                true
            }
            Err(fehler) => {
                let meldung = fehler.to_string();
                if self.fehler.as_deref() != Some(meldung.as_str()) {
                    logging::zeile(logging::WARN, &meldung);
                }
                self.fehler = Some(meldung);
                self.wieder_ab = Some(Instant::now() + WIEDER_VERBINDEN_NACH);
                false
            }
        }
    }

    /// Das Gerät loslassen; die Stufe bleibt, wie sie ist.
    pub fn trennen(&mut self) {
        self.pad = None;
        self.letzter_bericht = None;
    }

    /// Der Weg, über den gerade gesprochen wird.
    pub fn knoten(&self) -> Option<&Path> {
        self.pad.as_ref().map(Pad::node)
    }

    /// Die Temperaturen dieses Rechners, in der Reihenfolge der Oberfläche.
    pub fn temperaturen_lesen(&mut self) {
        self.temperaturen = sensors::lesen();
    }

    /// Die Temperatur, nach der die Kurve sich richtet: die wärmste der
    /// eingestellten Messstellen.
    ///
    /// Sind keine davon da - anderes Notebook, Modul nicht geladen -, fällt die
    /// Steuerung auf die wärmste Messung überhaupt zurück. Stillstehen wäre die
    /// schlechtere Wahl: Der Lüfter bliebe auf einer Stufe, die für eine
    /// Temperatur gilt, die es auf diesem Rechner gar nicht gibt.
    pub fn bezugstemperatur(&self) -> Option<f64> {
        let gewaehlte: Vec<f64> = self
            .einstellungen
            .messstellen
            .iter()
            .filter_map(|schluessel| self.temperaturen.get(schluessel).copied())
            .collect();
        let waermste = |werte: &[f64]| {
            werte
                .iter()
                .copied()
                .fold(None, |bisher: Option<f64>, wert| {
                    Some(bisher.map_or(wert, |alt| alt.max(wert)))
                })
        };
        if let Some(grad) = waermste(&gewaehlte) {
            return Some(grad);
        }
        waermste(&self.temperaturen.values().copied().collect::<Vec<f64>>())
    }

    /// Die Stufe, die die Einstellungen gerade verlangen.
    ///
    /// `frisch` sagt, ob der Kurve eine neue Messung angeboten wird. Ohne
    /// frische Messung wird nur nachgesehen, nicht entschieden - sonst zählte
    /// dieselbe Temperatur zweimal als Bewegung und die Hysterese verfiele.
    pub fn gewuenschte_stufe(&mut self, frisch: bool) -> u8 {
        if self.einstellungen.modus != "auto" {
            let stufe = manuelle_stufe(self.einstellungen.manuelle_stufe);
            self.ziel = Some(stufe);
            return stufe;
        }
        let Some(grad) = self.bezugstemperatur() else {
            // Keine Messstelle: Das Gerät mag machen, was es gerade tut.
            return self
                .ziel
                .unwrap_or_else(|| manuelle_stufe(self.einstellungen.manuelle_stufe));
        };
        let stufe = if frisch {
            self.folger.aktualisieren(grad)
        } else {
            kurve_fuer(grad, &self.einstellungen.kurve)
        };
        self.ziel = Some(stufe);
        stufe
    }

    /// Die berechnete Stufe auf das Gerät bringen, wenn sie wirklich anders ist.
    pub fn stufe_anwenden(&mut self, kraft: bool) -> Option<u8> {
        if !self.verbinden() {
            return None;
        }
        let gewollt = self.gewuenschte_stufe(true);
        // Die beiden Huerden der Python-Fassung: genug Unterschied ...
        let mindest = self.einstellungen.stufe_mindest_schritt.max(0.0) as i16;
        #[allow(clippy::unnecessary_map_or)] // `is_none_or` ware erst ab 1.82
        let bewegen = self.letzter_bericht.map_or(true, |zustand| {
            (i16::from(gewollt) - i16::from(zustand.fan_speed)).abs() >= mindest
        });
        #[allow(clippy::unnecessary_map_or)] // `is_none_or` ware erst ab 1.82
        let abgekuehlt = self.letzte_schreibzeit.map_or(true, |zuletzt| {
            Instant::now().duration_since(zuletzt)
                >= Duration::from_secs_f64(self.einstellungen.schreib_abstand.max(0.0))
        });
        if !(kraft || bewegen) || !(kraft || abgekuehlt) {
            return Some(gewollt);
        }

        let Some(bericht) = self.bericht_fuer_schreibarbeit() else {
            return Some(gewollt);
        };
        let licht = beleuchtung_von(&bericht);
        let ergebnis = self
            .pad
            .as_ref()
            .map(|pad| pad.write_state(f64::from(gewollt), bericht.powered_on, &licht));
        match ergebnis {
            Some(Ok(neu)) => {
                self.letzter_bericht = Some(neu);
                self.letzte_schreibzeit = Some(Instant::now());
                self.fehler = None;
                logging::zeile(
                    logging::INFO,
                    &format!(
                        "Luefter {gewollt}% (Temperatur {:.1} degC)",
                        self.bezugstemperatur().unwrap_or(-1.0)
                    ),
                );
            }
            Some(Err(fehler)) => self.melde_geraet(&fehler.to_string()),
            None => self.melde_geraet("kein Geraet verbunden"),
        }
        Some(gewollt)
    }

    /// Die Beleuchtung aus der Datei auf das Gerät bringen, aber nur, wenn sie
    /// sich seit dem letzten Mal geändert hat.
    pub fn licht_anwenden(&mut self, kraft: bool) -> Option<()> {
        let stand = (
            self.einstellungen.licht.an,
            self.einstellungen.licht.farbe,
            self.einstellungen.licht.effekt,
            self.einstellungen.licht.takt,
            self.einstellungen.licht.helligkeit,
        );
        if !kraft && self.licht_stand == Some(stand) {
            return None;
        }
        if !self.verbinden() {
            return None;
        }
        let bericht = self.bericht_fuer_schreibarbeit()?;
        let licht = Lighting {
            color: self.einstellungen.licht.farbe,
            effect: self.einstellungen.licht.effekt,
            effect_speed: self.einstellungen.licht.takt,
            brightness: self.einstellungen.licht.helligkeit,
            light_on: self.einstellungen.licht.an,
        };
        // Die Stufe wird mitgenommen, wie sie ist - ohne sie stünde der Lüfter
        // nach jedem Farbwechsel still.
        let ergebnis = self
            .pad
            .as_ref()
            .map(|pad| pad.write_light(bericht.fan_speed, bericht.powered_on, &licht));
        match ergebnis {
            Some(Ok(neu)) => {
                self.letzter_bericht = Some(neu);
                self.licht_stand = Some(stand);
                self.fehler = None;
                logging::zeile(
                    logging::INFO,
                    &format!(
                        "LEDs: {} / {} / Helligkeit {}",
                        licht.color, licht.effect, licht.brightness
                    ),
                );
                Some(())
            }
            Some(Err(fehler)) => {
                self.melde_geraet(&fehler.to_string());
                None
            }
            None => {
                self.melde_geraet("kein Geraet verbunden");
                None
            }
        }
    }

    /// Der Hauptschalter des Geräts, ohne Farbe und Stufe anzufassen.
    ///
    /// `leise` ist für die automatischen Momente: Ein Zufall, dass das Gerät
    /// gerade nicht da ist, soll einen Programmstart nicht wie einen Fehler
    /// aussehen lassen.
    pub fn strom(&mut self, an: bool, leise: bool) -> bool {
        if !self.verbinden() {
            if !leise {
                logging::zeile(
                    logging::WARN,
                    "Kuehler nicht erreichbar, Schalten uebersprungen",
                );
            }
            return false;
        }
        let Some(bericht) = self.bericht_fuer_schreibarbeit() else {
            if !leise {
                logging::zeile(logging::WARN, "Kuehler meldet keinen Zustand zurueck");
            }
            return false;
        };
        let licht = beleuchtung_von(&bericht);
        let stufe = bericht.fan_speed;
        let ergebnis = self
            .pad
            .as_ref()
            .map(|pad| pad.write_light(stufe, an, &licht));
        match ergebnis {
            Some(Ok(neu)) => {
                self.letzter_bericht = Some(neu);
                self.letzte_schreibzeit = Some(Instant::now());
                self.fehler = None;
                logging::zeile(
                    logging::INFO,
                    if an {
                        "Kuehler eingeschaltet"
                    } else {
                        "Kuehler ausgeschaltet"
                    },
                );
                true
            }
            Some(Err(fehler)) => {
                let meldung = fehler.to_string();
                self.fehler = Some(meldung.clone());
                if !leise {
                    logging::zeile(
                        logging::WARN,
                        &format!("Schalten fehlgeschlagen: {meldung}"),
                    );
                }
                false
            }
            None => false,
        }
    }

    /// Ein Umlauf: lesen, entscheiden, schreiben.
    pub fn umlauf(&mut self) -> Umlauf {
        let verbunden = self.verbinden();
        self.temperaturen_lesen();
        let bezug = self.bezugstemperatur();

        if verbunden {
            match self.lesen() {
                Ok(bericht) => {
                    self.letzter_bericht = Some(bericht);
                    self.fehler = None;
                }
                Err(fehler) => self.melde_geraet(&fehler.to_string()),
            }
        }

        self.licht_anwenden(false);
        let ziel = self.gewuenschte_stufe(true);
        if verbunden {
            self.stufe_anwenden(false);
        }

        Umlauf {
            verbunden,
            knoten: self.knoten().map(|pfad| pfad.display().to_string()),
            bezug,
            temperaturen: self.temperaturen.clone(),
            ziel: Some(ziel),
            bericht: self.letzter_bericht,
            modus: self.einstellungen.modus.clone(),
            fehler: self.fehler.clone(),
        }
    }

    /// Der Dienst: anschalten, Beleuchtung setzen, dann rundenweise arbeiten.
    ///
    /// `solange` wird vor jeder Runde gefragt und heisst "bitte weitermachen" -
    /// die Umkehrung von "jemand will beendet haben". Wer hier die Richtungen
    /// vertauscht, bekommt einen Dienst, der beim Start fertig ist, ohne es zu
    /// sagen; die Pruefung unten haelt genau das fest.
    pub fn laufen(
        &mut self,
        sperre: &Sperre,
        solange: &dyn Fn() -> bool,
        anzeige: &dyn Fn(&Umlauf),
    ) {
        let _ = sperre;
        if self.einstellungen.beim_start_an {
            // Ein Kühlpad, das beim letzten Herunterfahren ausging, bleibt aus,
            // bis es jemand wieder anschaltet - warum nicht wir.
            self.strom(true, true);
        }
        self.licht_anwenden(true);
        while solange() {
            let umlauf = self.umlauf();
            anzeige(&umlauf);
            let pause = Duration::from_secs_f64(self.einstellungen.poll_sekunden.max(1.0));
            std::thread::sleep(pause);
        }
        self.zu_ende();
    }

    /// Zu Ende bringen, was versprochen ist: ausschalten, wenn die Datei das
    /// will, und dann loslassen.
    pub fn zu_ende(&mut self) {
        if self.einstellungen.beim_ende_aus {
            self.strom(false, true);
        }
        self.trennen();
    }

    /// Die Einstellungen neu aus der Datei holen. Eine andere Kurve vergisst
    /// ihren alten Anker, sonst hinge die Stufe an einer Temperatur von eben.
    pub fn einstellungen_nachlesen(&mut self) -> Option<String> {
        let (frisch, warnung) = config::laden();
        let anders = frisch.kurve != self.einstellungen.kurve
            || frisch.hysterese != self.einstellungen.hysterese;
        self.einstellungen = frisch;
        if anders {
            self.folger
                .neu_verbinden(&self.einstellungen.kurve, self.einstellungen.hysterese);
        }
        warnung
    }

    /// Die Einstellungen, wie sie in der Datei stehen, ohne sie zu übernehmen.
    pub fn stand_der_datei(&self) -> (Einstellungen, Option<String>) {
        config::laden()
    }

    fn bericht_fuer_schreibarbeit(&mut self) -> Option<State> {
        if let Some(bericht) = &self.letzter_bericht {
            return Some(*bericht);
        }
        // Vor jedem Schreiben muss der aktuelle Stand bekannt sein: Beide
        // Berichte tragen Stufe und Beleuchtung, und was nicht dabeisteht,
        // stellt das Gerät auf seine eigenen Werte.
        let bericht = self.lesen().ok()?;
        self.letzter_bericht = Some(bericht);
        Some(bericht)
    }

    fn lesen(&self) -> Result<State, DeviceError> {
        self.pad
            .as_ref()
            .ok_or(DeviceError::Detached)?
            .read_state(true)
    }

    /// Ein Gerät, das nicht antwortet, ist erst einmal fünf Sekunden lang fort.
    /// Gesagt wird das nur, wenn sich die Meldung von der letzten unterscheidet.
    fn melde_geraet(&mut self, meldung: &str) {
        if self.fehler.as_deref() != Some(meldung) {
            logging::zeile(logging::WARN, meldung);
        }
        self.fehler = Some(meldung.to_owned());
        self.trennen();
        self.wieder_ab = Some(Instant::now() + WIEDER_VERBINDEN_NACH);
    }
}

/// Die Stufe, die bei "manuell" gilt: begrenzen wie die Python-Fassung.
fn manuelle_stufe(wert: f64) -> u8 {
    // Python: max(1, min(100, int(wert))). `int` schneidet ab, rundet nicht.
    (wert as i64).clamp(1, 100) as u8
}

/// Die Kurve für eine Temperatur, ohne Entscheidung und ohne Gedächtnis.
fn kurve_fuer(grad: f64, kurve: &[Punkt]) -> u8 {
    curve::interpolieren(kurve, grad).unwrap_or(1)
}

/// Die Beleuchtung, die ein Bericht gerade zeigt.
pub fn beleuchtung_von(bericht: &State) -> Lighting {
    Lighting {
        color: bericht.color,
        effect: bericht.effect,
        effect_speed: bericht.effect_speed,
        brightness: bericht.brightness,
        light_on: bericht.light_on,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Eine Sperrdatei nur fuer diese Pruefung, damit die der laufenden
    /// Oberflaeche in Ruhe bleibt.
    fn eigene_sperrdatei(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "llano-{}-{}-{:?}",
            name,
            std::process::id(),
            std::thread::current().name().unwrap_or("x")
        ))
    }

    fn messungen(werte: &[(&str, f64)]) -> BTreeMap<String, f64> {
        werte
            .iter()
            .map(|(name, grad)| ((*name).to_owned(), *grad))
            .collect()
    }

    #[test]
    fn der_dienst_hoert_auf_wenn_jemand_beendet_haben_will() {
        // Ein Geraet gibt es hier nicht, und das ist Absicht: Es zaehlt nur,
        // wie oft die Runde laeuft und dass am Ende aufgeraeumt wird.
        let mut steuerung = Steuerung::neu(Einstellungen {
            poll_sekunden: 0.0,
            beim_start_an: false,
            beim_ende_aus: false,
            modus: "manual".to_owned(),
            manuelle_stufe: 20.0,
            ..Einstellungen::default()
        });
        steuerung.knoten_wunsch = Some(std::path::PathBuf::from("/dev/llano-gibt-es-nicht"));
        let ziel = eigene_sperrdatei("dienst");
        let sperre =
            crate::lock::erwerben_in(&ziel).expect("eine eigene Sperrdatei fuer diese Pruefung");

        let runden = std::cell::Cell::new(0);
        let anrufe = std::cell::Cell::new(0);
        steuerung.laufen(&sperre, &|| runden.get() < 3, &|_| {
            runden.set(runden.get() + 1);
            anrufe.set(anrufe.get() + 1);
        });
        assert_eq!(anrufe.get(), 3, "drei Runden, dann ist gut");
        assert!(
            steuerung.letzter_bericht.is_none(),
            "ohne Geraet wird auch nichts erfunden"
        );
        let _ = std::fs::remove_file(&ziel);
    }

    #[test]
    fn ein_sofortiges_ende_laeuft_keine_runde() {
        let mut steuerung = Steuerung::neu(Einstellungen {
            poll_sekunden: 0.0,
            beim_start_an: false,
            beim_ende_aus: false,
            ..Einstellungen::default()
        });
        steuerung.knoten_wunsch = Some(std::path::PathBuf::from("/dev/llano-gibt-es-nicht"));
        let ziel = eigene_sperrdatei("sofort");
        let sperre = crate::lock::erwerben_in(&ziel).expect("eigene Sperrdatei");
        let runden = std::cell::Cell::new(0);
        steuerung.laufen(&sperre, &|| false, &|_| runden.set(runden.get() + 1));
        assert_eq!(
            runden.get(),
            0,
            "ein Ende vor der ersten Runde ist ein Ende"
        );
        let _ = std::fs::remove_file(&ziel);
    }

    #[test]
    fn manuelle_stufe_ohne_rundung() {
        assert_eq!(manuelle_stufe(44.9), 44, "abgeschnitten wie in Python");
        assert_eq!(manuelle_stufe(0.0), 1);
        assert_eq!(manuelle_stufe(-5.0), 1);
        assert_eq!(manuelle_stufe(900.0), 100);
    }

    #[test]
    fn die_waermste_eingestellte_messstelle_gewinnt() {
        let steuerung = Steuerung::neu(Einstellungen {
            messstellen: vec!["a:1".to_owned(), "b:2".to_owned()],
            ..Einstellungen::default()
        });
        let mut steuerung = steuerung;
        steuerung.temperaturen = messungen(&[("a:1", 44.0), ("b:2", 61.0), ("c:3", 90.0)]);
        assert_eq!(steuerung.bezugstemperatur(), Some(61.0));
    }

    #[test]
    fn eine_verschwundene_messstelle_friert_nichts_ein() {
        let mut steuerung = Steuerung::neu(Einstellungen {
            messstellen: vec!["weg:1".to_owned()],
            ..Einstellungen::default()
        });
        steuerung.temperaturen = messungen(&[("a:1", 44.0), ("b:2", 61.0)]);
        assert_eq!(
            steuerung.bezugstemperatur(),
            Some(61.0),
            "sonst waere die Kurve blind"
        );
    }

    #[test]
    fn ohne_messstelle_gibt_es_keinen_bezug() {
        let steuerung = Steuerung::neu(Einstellungen::default());
        assert_eq!(steuerung.bezugstemperatur(), None);
    }

    #[test]
    fn die_manuelle_stufe_kennt_kein_geraet() {
        let mut steuerung = Steuerung::neu(Einstellungen {
            modus: "manual".to_owned(),
            manuelle_stufe: 37.0,
            ..Einstellungen::default()
        });
        assert_eq!(steuerung.gewuenschte_stufe(true), 37);
        assert_eq!(steuerung.ziel, Some(37));
    }

    #[test]
    fn ohne_temperatur_bleibt_die_geplante_stufe() {
        let mut steuerung = Steuerung::neu(Einstellungen {
            manuelle_stufe: 24.0,
            ..Einstellungen::default()
        });
        assert_eq!(
            steuerung.gewuenschte_stufe(true),
            24,
            "Anfang aus der Datei"
        );
        steuerung.ziel = Some(66);
        assert_eq!(steuerung.gewuenschte_stufe(true), 66, "danach die geplante");
    }

    #[test]
    fn eine_frische_messung_zaehlt_als_bewegung() {
        let mut steuerung = Steuerung::neu(Einstellungen {
            kurve: vec![(40.0, 10), (60.0, 60)],
            hysterese: 3.0,
            ..Einstellungen::default()
        });
        steuerung.temperaturen = messungen(&[("x:1", 60.0)]);
        assert_eq!(steuerung.gewuenschte_stufe(true), 60);

        // Zwei Grad tiefer: die Hysterese von drei Grad haelt die Stufe oben.
        steuerung.temperaturen = messungen(&[("x:1", 58.0)]);
        assert_eq!(
            steuerung.gewuenschte_stufe(true),
            60,
            "zwei Grad tiefer bei drei Grad Hysterese ist zu wenig"
        );

        // Und ohne frische Messung wird ueberhaupt nicht entschieden, sondern
        // nur nachgesehen, was die Kurve gerade hergibt.
        steuerung.temperaturen = messungen(&[("x:1", 50.0)]);
        assert_eq!(
            steuerung.gewuenschte_stufe(false),
            35,
            "ohne frische Messung wird nur nachgesehen"
        );

        steuerung.temperaturen = messungen(&[("x:1", 54.0)]);
        assert_eq!(
            steuerung.gewuenschte_stufe(true),
            45,
            "sechs Grad tiefer: jetzt darf es herunter"
        );
    }

    #[test]
    fn ein_umlauf_ohne_geraet_meldet_das_statt_zu_verzweifeln() {
        let mut steuerung = Steuerung::neu(Einstellungen {
            modus: "manual".to_owned(),
            manuelle_stufe: 30.0,
            ..Einstellungen::default()
        });
        // Ein Weg, den es nicht gibt: derselbe Fall wie auf einem Rechner ohne
        // Geraet oder ohne Recht daran. Ausdruecklich ein unwirksamer Weg - ohne
        // ihn wuerde diese Pruefung auf dem Rechner eines Entwicklers den
        // echten Kuehler umstellen.
        steuerung.knoten_wunsch = Some(std::path::PathBuf::from("/dev/llano-gibt-es-nicht"));
        let umlauf = steuerung.umlauf();
        assert!(!umlauf.verbunden);
        assert_eq!(umlauf.ziel, Some(30));
        assert_eq!(umlauf.modus, "manual");
    }
}

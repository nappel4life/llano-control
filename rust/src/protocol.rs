//! Byte-Ebene des llano V12 Ultra Notebookkühlers (USB `374a:b101`).
//!
//! Das Geraet zeigt ein einziges Hersteller-HID-App mit drei Berichten und ohne
//! Berichtskennung: ein Feature-Bericht mit sieben Nutzbyte, dazu ein
//! Eingangs- und ein Ausgangsbericht mit je 64 Byte, in denen nichts
//! Bekanntes steckt. Ganze Steuerung laeuft also ueber den Feature-Bericht,
//! und weil es keine Berichtskennung gibt, verlangt der Kernel voran ein
//! Nullbyte - jeder Puffer hier ist neun Byte lang.
//!
//! Zwei Dinge hat das Nachmessen am Geraet ergeben, und beide sind hier
//! eingebaut:
//!
//! 1. Jeder Bericht traegt **beides**, Lufterstufe und Beleuchtung. Ein
//!    Bericht, der die Farbe nur mit Nullen mitschickt, loescht sie am Geraet.
//!    Wer nur die Stufe aendert, muss deshalb die Beleuchtung wiederholen, die
//!    bleiben soll.
//! 2. Das Geraet beantwortet eine Abfrage nur einmal; vor dem Lesen gehoert ein
//!    Statusbericht vorausgeschickt (siehe [`STATUS_REQUEST`] in
//!    [`crate::device`]).
//!
//! Dieses Modul ist reine Rechenarbeit: kein Ein- und Ausgabe, keine
//! Abhaengigkeiten. Die gleichen Byte-Folien wie die Python-Fassung prueft
//! `tests/vektoren.rs` gegen `tests/byte-vektoren.json`.

use std::fmt;

/// Hersteller-Kennung des Kuehlers.
pub const VENDOR_ID: u16 = 0x374A;
/// Produkt-Kennung des Kuehlers.
pub const PRODUCT_ID: u16 = 0xB101;

/// Nutzbyte eines Berichts ohne fuehrende Berichtskennung und ohne Summe.
pub const BODY_LEN: usize = 7;
/// Groesse eines Puffers, wie ihn Kernel und Treiber sehen.
pub const BUFFER_LEN: usize = BODY_LEN + 2;

/// Wert fuer das erste Koerperbyte: Bericht zur Beleuchtung.
pub const CMD_LIGHT: u8 = 0x00;
/// Wert fuer das erste Koerperbyte: Bericht zum Lufter.
pub const CMD_FAN: u8 = 0x01;

/// Die kleinste Stufe, auf die das Geraet hoert.
pub const FAN_MIN: u8 = 1;
/// Die groesste Stufe.
pub const FAN_MAX: u8 = 100;

/// In diesem Bit sagt das Geraet "Beleuchtung aus", der Effekt bleibt stehen.
pub const LIGHT_OFF_FLAG: u8 = 0x80;

/// Farbnamen, so wie die Herstellersoftware sie nennt.
pub fn color_name(color: u8) -> String {
    match color {
        0 => "rot".to_owned(),
        1 => "hellblau".to_owned(),
        2 => "gruen".to_owned(),
        3 => "lila".to_owned(),
        4 => "orange".to_owned(),
        other => format!("unbekannt({other})"),
    }
}

/// Effektnamen, ebenso uebernommen.
pub fn effect_name(effect: u8) -> String {
    match effect {
        0 => "durchgehend".to_owned(),
        1 => "atmend".to_owned(),
        2 => "regenbogen".to_owned(),
        3 => "lauflicht".to_owned(),
        4 => "zonen".to_owned(),
        other => format!("unbekannt({other})"),
    }
}

/// Was an der Beleuchtung gelten soll. Steht als eigener Satz zusammen,
/// weil jeder Bericht sie enthaelt - auch der fuer den Lufter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Lighting {
    pub color: u8,
    pub effect: u8,
    pub effect_speed: u8,
    pub brightness: u8,
    pub light_on: bool,
}

impl Default for Lighting {
    fn default() -> Self {
        Lighting {
            color: 0,
            effect: 0,
            effect_speed: 0,
            brightness: 0xFF,
            light_on: true,
        }
    }
}

/// Warum ein Bericht nicht gebaut oder nicht gelesen werden konnte.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProtocolError {
    /// Der Korper fuer die Summenberechnung hat die falsche Laenge.
    BodyLength { got: usize },
    /// Ein gelesener Bericht ist zu kurz.
    TooShort { got: usize, want: usize },
    /// Die Summe im Bericht passt nicht zum Korper.
    Checksum { expected: u8, got: u8 },
    /// Das Geraet hat eine fruehere Versionsanfrage noch nicht abgearbeitet.
    VersionRequest,
}

impl fmt::Display for ProtocolError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ProtocolError::BodyLength { got } => {
                write!(f, "Berichtskorper muss {BODY_LEN} Byte haben, waren {got}")
            }
            ProtocolError::TooShort { got, want } => {
                write!(f, "Bericht muss {want} Byte haben, waren {got}")
            }
            ProtocolError::Checksum { expected, got } => write!(
                f,
                "Summe passt nicht: erwartet 0x{expected:02x}, gelesen 0x{got:02x}"
            ),
            ProtocolError::VersionRequest => {
                write!(
                    f,
                    "das Geraet meldet eine Versionsanfrage statt eines Zustands"
                )
            }
        }
    }
}

impl std::error::Error for ProtocolError {}

/// Summenbyte: die Ergänzung der Byte-Summe auf 255.
pub fn checksum(body: &[u8]) -> Result<u8, ProtocolError> {
    if body.len() != BODY_LEN {
        return Err(ProtocolError::BodyLength { got: body.len() });
    }
    let summe: u32 = body.iter().map(|&b| u32::from(b)).sum();
    Ok((0xFF - (summe & 0xFF)) as u8)
}

/// Gewuenschte Stufe in den Bereich bringen, auf den das Geraet hoert.
///
/// Die Python-Fassung rundet kaufmaennisch; fuer die gebrochenen Zahlen, die
/// dort vorkommen (Temperaturkurve), ist das nie genau eine halbe Stufe,
/// deshalb unterscheiden sich die beiden Fassungen hier nicht.
pub fn clamp_fan(value: f64) -> u8 {
    let gerundet = value.round();
    if gerundet < f64::from(FAN_MIN) {
        FAN_MIN
    } else if gerundet > f64::from(FAN_MAX) {
        FAN_MAX
    } else {
        gerundet as u8
    }
}

fn frame(body: [u8; BODY_LEN]) -> [u8; BUFFER_LEN] {
    let mut bericht = [0u8; BUFFER_LEN];
    bericht[0] = 0x00; // Berichtskennung: es gibt keine
    bericht[1..1 + BODY_LEN].copy_from_slice(&body);
    bericht[BUFFER_LEN - 1] = checksum(&body).unwrap_or(0xFF);
    bericht
}

/// Bericht mit allem, was das Geraet weiss.
///
/// Die Stufen werden auf 0..100 begrenzt, weil der Beleuchtungsbefehl die
/// Stufe mitfuehrt und 0 dort "Luefter aus" bedeutet - mehr als 100 kennt das
/// Geraet nicht.
pub fn build_state(
    mode: u8,
    fan_speed: u8,
    powered_on: bool,
    light: &Lighting,
) -> [u8; BUFFER_LEN] {
    let effekt = if light.light_on {
        light.effect
    } else {
        light.effect | LIGHT_OFF_FLAG
    };
    frame([
        mode,
        fan_speed.min(FAN_MAX),
        if powered_on { 0x00 } else { 0x01 },
        effekt,
        light.color,
        light.effect_speed,
        light.brightness,
    ])
}

/// Stufe setzen und dabei die Beleuchtung wiederholen, die bleiben soll.
pub fn build_fan_report(speed: f64, powered_on: bool, light: &Lighting) -> [u8; BUFFER_LEN] {
    build_state(CMD_FAN, clamp_fan(speed), powered_on, light)
}

/// Beleuchtung setzen. Die Stufe muss dazugestellt werden: Der
/// Beleuchtungsbefehl traegt sie ebenfalls, und eine Null dort bleibt stehen.
pub fn build_light_report(fan_speed: u8, powered_on: bool, light: &Lighting) -> [u8; BUFFER_LEN] {
    build_state(CMD_LIGHT, fan_speed, powered_on, light)
}

/// Was ein gelesener Bericht erzaehlt.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct State {
    /// 0 fuer Beleuchtungs-, 1 fuer Stufenbericht; das Rad des Geraets meldet 0x88.
    pub mode: u8,
    pub fan_speed: u8,
    pub powered_on: bool,
    pub light_on: bool,
    pub effect: u8,
    pub color: u8,
    pub effect_speed: u8,
    pub brightness: u8,
}

impl State {
    /// Bericht lesen, inklusive Pruefung der Summe.
    pub fn parse(raw: &[u8]) -> Result<State, ProtocolError> {
        if raw.len() < BUFFER_LEN {
            return Err(ProtocolError::TooShort {
                got: raw.len(),
                want: BUFFER_LEN,
            });
        }
        let body = &raw[1..1 + BODY_LEN];
        let erwartet = checksum(body)?;
        let gelesen = raw[BUFFER_LEN - 1];
        if erwartet != gelesen {
            return Err(ProtocolError::Checksum {
                expected: erwartet,
                got: gelesen,
            });
        }
        Ok(State {
            mode: body[0],
            fan_speed: body[1],
            powered_on: body[2] == 0x00,
            light_on: body[3] < LIGHT_OFF_FLAG,
            effect: body[3] & !LIGHT_OFF_FLAG,
            color: body[4],
            effect_speed: body[5],
            brightness: body[6],
        })
    }

    /// Die Zahl, die auf der Anzeige des Kuehlers steht.
    ///
    /// Das Geraet rechnet in fuenfundzwanzig Stufen zu je hundert Umdrehungen,
    /// bei 300 beginnend.
    pub fn rpm_display(&self) -> u16 {
        let stufe = (f64::from(self.fan_speed.min(FAN_MAX)) - 1.0) * 25.0 / 99.0;
        let stufe = stufe.round().max(0.0) as u16;
        300 + stufe * 100
    }

    pub fn color_name(&self) -> String {
        color_name(self.color)
    }

    pub fn effect_name(&self) -> String {
        effect_name(self.effect)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summe_ueber_sieben_byte() {
        assert_eq!(checksum(&[0x01, 0x01, 0, 0, 0, 0, 0xFF]).unwrap(), 0xFE);
        assert_eq!(checksum(&[0, 0, 0, 0, 0, 0, 0]).unwrap(), 0xFF);
    }

    #[test]
    fn summe_verlangt_sieben_byte() {
        assert_eq!(
            checksum(&[0x01, 0x02]),
            Err(ProtocolError::BodyLength { got: 2 })
        );
    }

    #[test]
    fn stufe_wird_eingegrenzt() {
        assert_eq!(clamp_fan(-20.0), FAN_MIN);
        assert_eq!(clamp_fan(0.0), FAN_MIN);
        assert_eq!(clamp_fan(37.4), 37);
        assert_eq!(clamp_fan(37.6), 38);
        assert_eq!(clamp_fan(400.0), FAN_MAX);
    }

    #[test]
    fn beleuchtung_ohne_flag_ist_aus() {
        let licht = Lighting {
            color: 2,
            effect: 1,
            light_on: false,
            ..Lighting::default()
        };
        let bericht = build_light_report(30, true, &licht);
        assert_eq!(bericht[4], 1 | LIGHT_OFF_FLAG);
        let zustand = State::parse(&bericht).unwrap();
        assert!(!zustand.light_on);
        assert_eq!(zustand.effect, 1, "der Effekt bleibt ablesbar");
    }

    #[test]
    fn geschriebener_bericht_liest_sich_selbst() {
        let licht = Lighting {
            color: 3,
            effect: 2,
            effect_speed: 1,
            brightness: 128,
            light_on: true,
        };
        let bericht = build_fan_report(66.0, false, &licht);
        let zustand = State::parse(&bericht).unwrap();
        assert_eq!(zustand.fan_speed, 66);
        assert!(!zustand.powered_on);
        assert_eq!(zustand.color, 3);
        assert_eq!(zustand.effect_speed, 1);
        assert_eq!(zustand.brightness, 128);
    }

    #[test]
    fn kaputte_berichte_werden_abgewiesen() {
        let mut bericht = build_fan_report(40.0, true, &Lighting::default());
        bericht[8] ^= 0xFF;
        assert!(matches!(
            State::parse(&bericht),
            Err(ProtocolError::Checksum { .. })
        ));
        assert!(matches!(
            State::parse(&bericht[..7]),
            Err(ProtocolError::TooShort { .. })
        ));
    }

    #[test]
    fn anzeige_zahlt_wie_das_geraet() {
        let mut zustand = State::parse(&build_fan_report(1.0, true, &Lighting::default())).unwrap();
        assert_eq!(zustand.rpm_display(), 300);
        zustand.fan_speed = 100;
        assert_eq!(zustand.rpm_display(), 2800);
        zustand.fan_speed = 50;
        assert_eq!(zustand.rpm_display(), 1500);
    }
}

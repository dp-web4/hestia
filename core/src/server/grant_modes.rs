//! What a scope grant lets its holder DO at the path it reaches: read, write, execute, delete.
//!
//! dp, 2026-10-19 (#1345): *"scope grants should be granular: r / w / e / d."* Until this, a
//! grant carried reach and nothing else (#1098 §2), so a grant an operator meant as read-only
//! was also a write grant, and #1098 measured exactly that on a being (a recursive forum grant
//! let `memory_write` into the forum). The governance-snapshot read that dp's 2026-10-19
//! directive makes a default for every member needs a read grant to MEAN read.
//!
//! **Default is all four**, and that is a compatibility rule, not a recommendation: every grant
//! written before this field existed was effectively rwed, so it deserialises as rwed and
//! nothing an operator already granted silently narrows. A new grant narrower than that is an
//! explicit choice the operator reads and makes.
//!
//! **Spelling** is the letters in the fixed order `r w e d`, e.g. `"r"`, `"rw"`, `"rwed"`. One
//! canonical spelling per set, so two records holding the same modes compare and digest
//! equal however they were typed.

use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// A non-empty subset of {read, write, execute, delete}.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Modes(u8);

/// One mode. The bit values are internal; the letter is the wire form.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Mode {
    Read,
    Write,
    Execute,
    Delete,
}

impl Mode {
    pub const ALL: [Mode; 4] = [Mode::Read, Mode::Write, Mode::Execute, Mode::Delete];

    const fn bit(self) -> u8 {
        match self {
            Mode::Read => 0b0001,
            Mode::Write => 0b0010,
            Mode::Execute => 0b0100,
            Mode::Delete => 0b1000,
        }
    }

    pub const fn letter(self) -> char {
        match self {
            Mode::Read => 'r',
            Mode::Write => 'w',
            Mode::Execute => 'e',
            Mode::Delete => 'd',
        }
    }

    pub const fn word(self) -> &'static str {
        match self {
            Mode::Read => "read",
            Mode::Write => "write",
            Mode::Execute => "execute",
            Mode::Delete => "delete",
        }
    }

    fn from_letter(c: char) -> Option<Mode> {
        match c {
            'r' => Some(Mode::Read),
            'w' => Some(Mode::Write),
            'e' => Some(Mode::Execute),
            'd' => Some(Mode::Delete),
            _ => None,
        }
    }
}

impl Modes {
    /// Every mode: what an unmoded (pre-#1345) grant meant, and the default.
    pub const ALL: Modes = Modes(0b1111);
    /// Read only: the governance-snapshot shape.
    pub const READ: Modes = Modes(0b0001);

    pub const fn is_all(self) -> bool {
        self.0 == Self::ALL.0
    }

    pub const fn contains(self, m: Mode) -> bool {
        self.0 & m.bit() != 0
    }

    /// `self` grants everything `other` does (and possibly more).
    pub const fn includes(self, other: Modes) -> bool {
        self.0 & other.0 == other.0
    }

    /// Would replacing `before` with `self` let the holder do anything it could not?
    /// A change that adds even one mode WIDENS, whatever it removes.
    pub const fn widens(self, before: Modes) -> bool {
        self.0 & !before.0 != 0
    }

    /// Everything either grants: what several grants covering one path add up to.
    pub const fn union(self, other: Modes) -> Modes {
        Modes(self.0 | other.0)
    }

    pub fn iter(self) -> impl Iterator<Item = Mode> {
        Mode::ALL.into_iter().filter(move |m| self.contains(*m))
    }

    /// Parse the canonical spelling, or any order of the same letters. Refuses empty, unknown
    /// letters and repeats: each of those is a typo an operator should see, not a guess.
    pub fn parse(s: &str) -> Result<Modes, String> {
        let s = s.trim();
        if s.is_empty() {
            return Err("modes must name at least one of r, w, e, d".into());
        }
        let mut bits = 0u8;
        for c in s.chars() {
            let m = Mode::from_letter(c)
                .ok_or_else(|| format!("unknown mode '{c}' in \"{s}\" (use r, w, e, d)"))?;
            if bits & m.bit() != 0 {
                return Err(format!("mode '{c}' repeated in \"{s}\""));
            }
            bits |= m.bit();
        }
        Ok(Modes(bits))
    }

    /// The canonical spelling: letters in `r w e d` order.
    pub fn as_letters(self) -> String {
        self.iter().map(Mode::letter).collect()
    }
}

impl Default for Modes {
    fn default() -> Self {
        Modes::ALL
    }
}

impl std::fmt::Display for Modes {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.as_letters())
    }
}

impl Serialize for Modes {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(&self.as_letters())
    }
}

impl<'de> Deserialize<'de> for Modes {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let s = String::deserialize(d)?;
        Modes::parse(&s).map_err(serde::de::Error::custom)
    }
}

/// `skip_serializing_if` helper: an all-modes grant is written exactly as it was before #1345.
pub fn is_all(m: &Modes) -> bool {
    m.is_all()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spelling_is_canonical_whatever_the_input_order() {
        assert_eq!(Modes::parse("dwr").unwrap().as_letters(), "rwd");
        assert_eq!(Modes::parse("rwed").unwrap(), Modes::ALL);
        assert_eq!(Modes::parse("r").unwrap(), Modes::READ);
    }

    #[test]
    fn empty_unknown_and_repeated_are_refused() {
        assert!(Modes::parse("").is_err());
        assert!(Modes::parse("rx").is_err());
        assert!(Modes::parse("rr").is_err());
    }

    #[test]
    fn widening_is_any_added_mode() {
        let r = Modes::READ;
        let rw = Modes::parse("rw").unwrap();
        let rd = Modes::parse("rd").unwrap();
        assert!(rw.widens(r));
        assert!(!r.widens(rw));
        // swapping w for d removes one and adds one: still a widening
        assert!(rd.widens(rw));
        assert!(!Modes::ALL.widens(Modes::ALL));
    }

    #[test]
    fn default_and_serde_round_trip() {
        assert_eq!(Modes::default(), Modes::ALL);
        let j = serde_json::to_string(&Modes::parse("re").unwrap()).unwrap();
        assert_eq!(j, "\"re\"");
        let back: Modes = serde_json::from_str(&j).unwrap();
        assert_eq!(back.as_letters(), "re");
        assert!(serde_json::from_str::<Modes>("\"\"").is_err());
    }
}

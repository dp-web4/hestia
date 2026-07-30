//! Proving that the SOVEREIGN said yes — on a box where every member shares its UID.
//!
//! dp, 2026-07-30: *"ok, so give me a way to say yes, and know it was me that said it."*
//!
//! # Why nothing that already existed answers this
//!
//! hestia is assurance profile **A1**: a cooperative gate, no OS isolation, every member running
//! as the same user as the operator (HST-009). The genesis operator's private key is written to
//! disk at mode 0600 — the daemon prints *"private key written to … (0600) — load it into your
//! operator client."* At the same UID, mode 0600 separates nobody from anybody. So an operator
//! LCT signature made on this box proves **this box**, not **dp**. Every channel that shipped
//! before this one — the operator HTTP session, the dev-override bearer token, a local CLI
//! reading `HESTIA_HOME` — has the same property: it authenticates *access to the filesystem*,
//! which is precisely the thing that is not scarce here.
//!
//! The only thing on this machine that a member does not have is **something dp knows and never
//! writes down**.
//!
//! # What this is, precisely
//!
//! A phrase dp chooses, verified against an Argon2id hash. The hash is stored; the phrase never
//! is. A member can read the hash file — it is deliberately not secret, because pretending a
//! world-readable box has a secret file is the fiction this module exists to stop telling — and
//! reading it yields nothing without inverting Argon2id.
//!
//! So the record can finally say something it could not before: **this approval was made by
//! someone who knew the sovereign phrase.** That is a claim about a person, not about a machine.
//!
//! # What it is NOT — the honest ceiling
//!
//! This raises the cost of impersonation; it does not make it impossible, and a design that
//! claimed otherwise would be exactly the reassuring bit that is identical to the null state.
//!
//! * A member at the same UID can replace or wrap `~/.local/bin/hestia` and capture the phrase
//!   as it is typed. Note that the hestia BINARY is not in the gate's `_GOVERNANCE_FILES`, so
//!   that substitution is not currently even alerted on. That is a real gap and it is named here
//!   rather than left for a reader to discover.
//! * A member can read this module and learn the verification shape. That costs nothing: the
//!   security is in the phrase, not in the mechanism being unknown.
//! * Offline brute force against the stored hash is possible for anyone who can read the file,
//!   which is everyone. Argon2id is what makes that expensive rather than trivial, which is why
//!   a plain SHA-256 of the phrase would have been close to worthless here.
//!
//! What it genuinely buys: the bar moves from **read a file** to **subvert a binary or capture a
//! keystroke**. The first is invisible and free. The second is a deliberate, loud act — and
//! deliberate-versus-accidental is the distinction this fleet keeps failing to make. Everything
//! before this could be done by accident, by a member with a stale env var and no intent.
//!
//! The real fix is a second UID or off-box signing (A2/A3). This is the A1 rung, and it should be
//! replaced rather than defended.

use argon2::password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString};
use argon2::Argon2;

/// Minimum length. Not a policy flourish: the stored hash is world-readable, so a short phrase is
/// an offline dictionary attack with a head start, and Argon2id cannot rescue four characters.
pub const MIN_PHRASE_LEN: usize = 12;

#[derive(Debug, PartialEq, Eq)]
pub enum PhraseError {
    /// Shorter than `MIN_PHRASE_LEN`.
    TooShort(usize),
    /// No phrase has been enrolled, so nothing can be verified. Fail CLOSED: an unset phrase
    /// must never read as "anything is accepted", which is how an absent control becomes an
    /// open door.
    NotEnrolled,
    /// The stored hash is unparseable — corrupted or truncated. Also fail closed, and say which
    /// of the two it is rather than blaming the caller's phrase.
    CorruptRecord,
    /// The phrase did not match.
    Mismatch,
}

impl std::fmt::Display for PhraseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PhraseError::TooShort(n) => write!(
                f,
                "sovereign phrase must be at least {MIN_PHRASE_LEN} characters (got {n}) — the \
                 stored hash is world-readable, so a short phrase is an offline dictionary attack"
            ),
            PhraseError::NotEnrolled => write!(
                f,
                "no sovereign phrase is enrolled — refusing. An unset control must never read as \
                 'accept anything'. Enrol one with `hestia sovereign set-phrase`"
            ),
            PhraseError::CorruptRecord => write!(
                f,
                "the stored sovereign phrase record is unreadable — refusing rather than \
                 guessing. Re-enrol with `hestia sovereign set-phrase`"
            ),
            PhraseError::Mismatch => write!(f, "sovereign phrase did not match"),
        }
    }
}

/// Hash a phrase for storage. Argon2id with the crate defaults and a fresh random salt.
pub fn enrol(phrase: &str) -> Result<String, PhraseError> {
    let n = phrase.chars().count();
    if n < MIN_PHRASE_LEN {
        return Err(PhraseError::TooShort(n));
    }
    // OsRng, not a seeded or time-derived source: a predictable salt turns a per-install cost
    // into a one-off precomputation across the fleet.
    let salt = SaltString::generate(&mut argon2::password_hash::rand_core::OsRng);
    Argon2::default()
        .hash_password(phrase.as_bytes(), &salt)
        .map(|h| h.to_string())
        .map_err(|_| PhraseError::CorruptRecord)
}

/// Verify a candidate against a stored record.
///
/// `stored` is `None` when nothing is enrolled, which is an error and never a pass. Every branch
/// that is not an exact match returns an error, so there is no path where an unusual input is
/// treated as success.
pub fn verify(stored: Option<&str>, candidate: &str) -> Result<(), PhraseError> {
    let stored = stored.map(str::trim).filter(|s| !s.is_empty());
    let Some(stored) = stored else {
        return Err(PhraseError::NotEnrolled);
    };
    let parsed = PasswordHash::new(stored).map_err(|_| PhraseError::CorruptRecord)?;
    // A TRUNCATED record still parses: the PHC string keeps its algorithm and params and simply
    // loses its hash segment, and `verify_password` then fails the same way a wrong phrase does.
    // Reported as Mismatch, that tells the sovereign to re-type when the real answer is re-enrol
    // — a true statement ("this did not verify") standing in for the useful one. Caught by the
    // test that expected CorruptRecord and got Mismatch.
    if parsed.hash.is_none() {
        return Err(PhraseError::CorruptRecord);
    }
    Argon2::default()
        .verify_password(candidate.as_bytes(), &parsed)
        .map_err(|_| PhraseError::Mismatch)
}

/// Read the phrase from a TTY, and **never** from the environment.
///
/// The existing `cli::prompt_passphrase` accepts `HESTIA_PASSPHRASE` as an override, which is
/// correct for unlocking the vault in a systemd unit and catastrophic here: the service already
/// reads that variable from a file on disk, so honouring an env override would hand back exactly
/// the filesystem-access bypass this module exists to remove. Any member could export it.
///
/// So: TTY only. If there is no TTY there is no sovereign present, and the answer is no.
pub fn prompt_sovereign_phrase(prompt: &str) -> Result<String, String> {
    if !std::io::IsTerminal::is_terminal(&std::io::stdin()) {
        return Err(
            "no TTY — the sovereign phrase is never read from the environment or from a pipe, \
             because a member can set both. An approval with nobody present is not an approval."
                .to_string(),
        );
    }
    rpassword::prompt_password(prompt).map_err(|e| format!("reading sovereign phrase: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const GOOD: &str = "correct horse battery staple";

    #[test]
    fn a_correct_phrase_verifies_and_a_wrong_one_does_not() {
        let rec = enrol(GOOD).expect("enrol");
        assert!(verify(Some(&rec), GOOD).is_ok());
        assert_eq!(verify(Some(&rec), "wrong phrase entirely").unwrap_err(), PhraseError::Mismatch);
    }

    #[test]
    fn an_unenrolled_phrase_refuses_rather_than_accepting_anything() {
        // The whole failure class this fleet keeps meeting: an absent control rendering as a
        // pass. If this ever returns Ok, every governance write is approvable by anyone.
        assert_eq!(verify(None, GOOD).unwrap_err(), PhraseError::NotEnrolled);
        assert_eq!(verify(Some(""), GOOD).unwrap_err(), PhraseError::NotEnrolled);
        assert_eq!(verify(Some("   "), GOOD).unwrap_err(), PhraseError::NotEnrolled);
    }

    #[test]
    fn a_corrupt_record_refuses_and_says_which_problem_it_is() {
        // Distinct from Mismatch on purpose: blaming the operator's phrase for a truncated file
        // sends them to re-type instead of to re-enrol.
        assert_eq!(verify(Some("not-a-hash"), GOOD).unwrap_err(), PhraseError::CorruptRecord);
        let rec = enrol(GOOD).unwrap();
        let truncated = &rec[..rec.len() / 2];
        assert_eq!(verify(Some(truncated), GOOD).unwrap_err(), PhraseError::CorruptRecord);
    }

    #[test]
    fn the_empty_candidate_is_never_a_pass() {
        let rec = enrol(GOOD).unwrap();
        assert_eq!(verify(Some(&rec), "").unwrap_err(), PhraseError::Mismatch);
    }

    #[test]
    fn short_phrases_are_refused_at_enrolment() {
        assert_eq!(enrol("short").unwrap_err(), PhraseError::TooShort(5));
        assert_eq!(enrol("").unwrap_err(), PhraseError::TooShort(0));
        assert!(enrol("a".repeat(MIN_PHRASE_LEN).as_str()).is_ok());
    }

    #[test]
    fn the_stored_record_does_not_contain_the_phrase() {
        // It is world-readable by design; that is only acceptable if it leaks nothing.
        let rec = enrol(GOOD).unwrap();
        assert!(!rec.contains(GOOD));
        assert!(!rec.contains("correct"));
        assert!(rec.starts_with("$argon2id$"), "must be argon2id, not a bare digest: {rec}");
    }

    #[test]
    fn two_enrolments_of_the_same_phrase_differ() {
        // A fresh salt each time. Identical records across the fleet would let one cracked
        // install answer for every other.
        assert_ne!(enrol(GOOD).unwrap(), enrol(GOOD).unwrap());
    }
}

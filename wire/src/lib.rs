//! Wire formats the Hestia **daemon** and the Hestia **app** must produce byte-identically.
//!
//! ## Why this crate exists
//!
//! Sprint A shipped `canonical_session_transcript` **twice** — once in
//! `app/src-tauri/src/identity.rs` and once in `core/src/server/operator_auth.rs` — because
//! the app cannot import the governance core and the daemon cannot import the app. Two
//! implementations of one wire format, guarded by a copied golden vector.
//!
//! That guard works: the vector was pinned, and when a third implementation was written
//! independently it hashed to the same value on the first run. But a copied vector detects
//! drift; it does not prevent it, and the two copies were already at risk of diverging the
//! first time someone added a field to one side.
//!
//! This repo has paid for that shape repeatedly — five gate implementations of one policy,
//! two design-token sets from one brand, a shared policy core imported by two harnesses and
//! deployed to none. **One source consumed twice** is the standing answer, and this crate is
//! that answer applied to the session transcript.
//!
//! ## Why not `web4-core`
//!
//! Both crates already depend on `web4-core`, so it was the tempting home. It is the wrong
//! layer: `hestia:operator-session:v1` is a **Hestia protocol detail**, and the canonical
//! Web4 crate should not carry one implementation's session format. Layering matters more
//! than the convenience of an existing dependency.
//!
//! ## Scope, so this does not become a dumping ground
//!
//! Only formats that **both** the app and the daemon must agree on byte-for-byte. Anything
//! one side alone parses belongs to that side. No policy, no governance, no I/O — encoding
//! only, so this crate stays trivially auditable.

#![forbid(unsafe_code)]

/// Domain separator for the operator-session transcript.
///
/// Changing this string, the field order, or a field's spelling is a **v2 wire change** and
/// breaks every existing client. The golden vector below exists to make that break loud.
pub const SESSION_TRANSCRIPT_DOMAIN: &str = "hestia:operator-session:v1";

/// The composed identities an operator session binds, as they appear in the transcript.
///
/// Borrowed rather than owned: the daemon holds these in `OperatorProvenance` and the app in
/// `SessionComposition`, and neither should have to clone into a third shape to sign.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SessionTranscriptFields<'a> {
    pub actor: &'a str,
    pub actor_public_key: &'a str,
    pub principal: &'a str,
    pub via_device: &'a str,
    pub device_public_key: &'a str,
    pub office: &'a str,
    pub authority: &'a str,
}

/// The exact bytes every signature on an operator-session request covers.
///
/// **Domain-separated** so a signature over these bytes cannot be replayed as a signature
/// over anything else, and **length-delimited** so adjacent fields cannot be re-cut into the
/// same byte string — without the length prefix, moving a character from `actor` into
/// `actor_public_key` would produce an identical transcript and the signature would then
/// cover a different composition than the one recorded.
pub fn canonical_session_transcript(challenge: &str, f: &SessionTranscriptFields<'_>) -> Vec<u8> {
    let fields = [
        ("challenge", challenge),
        ("actor", f.actor),
        ("actor_public_key", f.actor_public_key),
        ("principal", f.principal),
        ("via_device", f.via_device),
        ("device_public_key", f.device_public_key),
        ("office", f.office),
        ("authority", f.authority),
    ];
    let mut out = format!("{SESSION_TRANSCRIPT_DOMAIN}\n").into_bytes();
    for (name, value) in fields {
        out.extend_from_slice(format!("{name}:{}\n", value.len()).as_bytes());
        out.extend_from_slice(value.as_bytes());
        out.push(b'\n');
    }
    out
}

/// Domain separator for the act-digest preimage (Sprint B1).
///
/// Same contract as [`SESSION_TRANSCRIPT_DOMAIN`]: changing this string or the framing below
/// is a **v2 wire change**. Once B2's chain holds signatures over v1 digests, editing v1
/// silently unverifies every recorded act — bump the version instead.
pub const ACT_DIGEST_DOMAIN: &str = "hestia:act-digest:v1";

/// The exact bytes an act signature's digest covers — the B1 half of the signing contract
/// that B2's chain column and B4's verifier build against.
///
/// The caller supplies the act's canonical JSON **with the `witnesses` field cleared** (so N
/// independent marks on one act all cover the same bytes — the rule `witness_act::act_digest`
/// established). That clearing has to happen where the `Act` type lives; this crate stays
/// dependency-free and frames only the bytes it is handed. **Domain-separated** so a
/// signature over an act digest cannot be replayed as a signature over a session transcript
/// or anything else, and **length-delimited** for the same reason the transcript is: the
/// frame states how many bytes it covers instead of trusting the payload to end where the
/// signer thought it did.
///
/// The digest itself is sha256 of these bytes, hex-encoded — the hashing stays with the
/// callers (as with [`canonical_session_transcript`]) so this crate remains encoding only.
pub fn canonical_act_digest_preimage(act_json_without_witnesses: &[u8]) -> Vec<u8> {
    let mut out = format!("{ACT_DIGEST_DOMAIN}\n").into_bytes();
    out.extend_from_slice(format!("act:{}\n", act_json_without_witnesses.len()).as_bytes());
    out.extend_from_slice(act_json_without_witnesses);
    out.push(b'\n');
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};

    fn sha256_hex(b: &[u8]) -> String {
        hex::encode(Sha256::digest(b))
    }

    fn sample() -> SessionTranscriptFields<'static> {
        SessionTranscriptFields {
            actor: "lct:web4:mb32:bactor",
            actor_public_key: "1111111111111111111111111111111111111111111111111111111111111111",
            principal: "lct:web4:mb32:bprincipal",
            via_device: "lct:web4:mb32:bdevice",
            device_public_key: "2222222222222222222222222222222222222222222222222222222222222222",
            office: "role:constellation:sovereign",
            authority: "operator-session:abc",
        }
    }

    /// **The vector that made consolidation safe.** It was pinned independently by the app
    /// and the daemon before this crate existed; both agreed. Moving the code here must not
    /// change the bytes, and this asserts it did not.
    ///
    /// If this fails, the format changed. **Bump the domain to v2 deliberately — never edit
    /// this constant to make the test pass**, because every deployed client signs the old
    /// bytes and would silently stop verifying.
    #[test]
    fn the_golden_vector_is_unchanged_by_consolidation() {
        assert_eq!(
            sha256_hex(&canonical_session_transcript("abc", &sample())),
            "0524720396a6a9be07c5fa62e9e736e1d1302d59e37d7daf3609d8f87bd492a1",
        );
    }

    #[test]
    fn it_is_domain_separated_and_length_delimited() {
        let text = String::from_utf8(canonical_session_transcript("abc", &sample())).unwrap();
        assert!(text.starts_with("hestia:operator-session:v1\nchallenge:3\nabc\n"));
    }

    /// The property the length prefixes exist for.
    #[test]
    fn field_boundaries_cannot_be_shifted() {
        let a = SessionTranscriptFields {
            actor: "xy",
            actor_public_key: "z",
            ..sample()
        };
        let b = SessionTranscriptFields {
            actor: "x",
            actor_public_key: "yz",
            ..sample()
        };
        assert_ne!(
            canonical_session_transcript("c", &a),
            canonical_session_transcript("c", &b),
            "moving a byte across a field boundary must change the transcript"
        );
    }

    /// A different challenge must never produce the same bytes — the anti-replay property
    /// the whole challenge/response flow rests on.
    #[test]
    fn the_challenge_is_bound() {
        assert_ne!(
            canonical_session_transcript("aa", &sample()),
            canonical_session_transcript("ab", &sample()),
        );
    }

    /// **The B1↔B2 vector.** Pinned when the format was defined; the app's signer, the
    /// daemon's verifier, and any independent implementation must all reproduce it. If this
    /// fails, the format changed — bump [`ACT_DIGEST_DOMAIN`] to v2 deliberately, never edit
    /// this constant, because B2's chain holds signatures over the old bytes from genesis.
    #[test]
    fn the_act_digest_golden_vector() {
        let act_json = br#"{"act_id":"b1","actor_lct":"lct:web4:mb32:bactor","witnesses":[]}"#;
        assert_eq!(
            sha256_hex(&canonical_act_digest_preimage(act_json)),
            "9f3f64f491602844e5158ae2d213a6ef39be5087915216327c5445985a9051ac",
        );
    }

    #[test]
    fn the_act_preimage_is_domain_separated_and_length_delimited() {
        let text = String::from_utf8(canonical_act_digest_preimage(b"xyz")).unwrap();
        assert_eq!(text, "hestia:act-digest:v1\nact:3\nxyz\n");
        // A signature over an act digest can never be a signature over a transcript.
        assert_ne!(ACT_DIGEST_DOMAIN, SESSION_TRANSCRIPT_DOMAIN);
    }
}

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
//! that answer applied to byte-level contracts shared across Hestia components.
//!
//! ## Why not `web4-core`
//!
//! Both crates already depend on `web4-core`, so it was the tempting home. It is the wrong
//! layer: Hestia's signature framing is a **Hestia protocol detail**, and the canonical Web4
//! crate should not carry one implementation's byte format. Layering matters more than the
//! convenience of an existing dependency.
//!
//! ## Scope, so this does not become a dumping ground
//!
//! Only formats that two independently-built Hestia components must agree on byte-for-byte.
//! Anything one side alone parses belongs to that side. No policy, no governance, no I/O —
//! encoding only, so this crate stays trivially auditable.

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

/// Domain separator for the v1 digest of a witnessed Web4 Act.
///
/// The **field list below is the versioned contract**. It deliberately does not inherit the
/// serialization of `web4_core::act::Act`: adding/reordering a field in that foreign Rust
/// struct must not silently invalidate signatures already recorded by Hestia. A semantic
/// change to these signed fields is a v2 wire change.
pub const ACT_DIGEST_DOMAIN: &str = "hestia:act-digest:v1";

/// Semantic fields covered by an Act v1 digest.
///
/// All normalization happens at the Web4 `Act` boundary. This crate owns only the exact
/// strings and their order, keeping the wire contract dependency-free and reproducible in
/// any language. `witnesses` is absent by construction: attaching witness marks never changes
/// the bytes previous witnesses signed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ActDigestV1Fields<'a> {
    pub act_id: &'a str,
    pub actor_lct: &'a str,
    pub address_kind: &'a str,
    pub address_value: &'a str,
    pub kind: &'a str,
    pub consequence: &'a str,
    pub substance_uri: &'a str,
    pub substance_content_hash: &'a str,
    pub substance_medium: &'a str,
    pub at: &'a str,
}

/// Exact preimage bytes for `sha256` of a v1 Web4 Act witness digest.
///
/// Every field is UTF-8 and length-delimited in bytes. No JSON, escaping, map ordering, or
/// implementation-specific serializer participates in the signature contract.
pub fn canonical_act_digest_preimage(f: &ActDigestV1Fields<'_>) -> Vec<u8> {
    let fields = [
        ("act_id", f.act_id),
        ("actor_lct", f.actor_lct),
        ("address_kind", f.address_kind),
        ("address_value", f.address_value),
        ("kind", f.kind),
        ("consequence", f.consequence),
        ("substance_uri", f.substance_uri),
        ("substance_content_hash", f.substance_content_hash),
        ("substance_medium", f.substance_medium),
        ("at", f.at),
    ];
    let mut out = format!("{ACT_DIGEST_DOMAIN}\n").into_bytes();
    for (name, value) in fields {
        out.extend_from_slice(format!("{name}:{}\n", value.len()).as_bytes());
        out.extend_from_slice(value.as_bytes());
        out.push(b'\n');
    }
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

    fn sample_act() -> ActDigestV1Fields<'static> {
        ActDigestV1Fields {
            act_id: "00000000-0000-0000-0000-000000000001",
            actor_lct: "00000000-0000-0000-0000-000000000002",
            address_kind: "peer",
            address_value: "00000000-0000-0000-0000-000000000003",
            kind: "handoff",
            consequence: "reversible",
            substance_uri: "forum/handoff",
            substance_content_hash: "abc123",
            substance_medium: "forum",
            at: "2026-06-20T12:00:00.000000000Z",
        }
    }

    /// Full v1 semantic vector. Independent implementations can reproduce this with only
    /// UTF-8, byte lengths, and SHA-256 — no Rust/serde behavior is part of the contract.
    #[test]
    fn the_act_digest_golden_vector_is_language_independent() {
        assert_eq!(
            sha256_hex(&canonical_act_digest_preimage(&sample_act())),
            "475c29316bbd129c83bf1cdf0af5577c0710b5564f0a9b849fec1dddd4a75b01",
        );
    }

    #[test]
    fn the_act_digest_is_domain_separated_and_boundary_safe() {
        assert_ne!(ACT_DIGEST_DOMAIN, SESSION_TRANSCRIPT_DOMAIN);
        let a = ActDigestV1Fields {
            kind: "xy",
            substance_uri: "z",
            ..sample_act()
        };
        let b = ActDigestV1Fields {
            kind: "x",
            substance_uri: "yz",
            ..sample_act()
        };
        assert_ne!(
            canonical_act_digest_preimage(&a),
            canonical_act_digest_preimage(&b),
            "moving bytes across semantic fields must change the preimage"
        );
    }
}

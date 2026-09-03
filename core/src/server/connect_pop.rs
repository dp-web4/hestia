//! Proof-of-possession at connect — PRD_FLEET §4.2 class 2, PRD_ASSURANCE FR-1
//! (the "hinge"), hestia #824 / #832.
//!
//! Today `hestia_connect` attributes a session to whatever `plugin_id` the
//! caller typed. For hooked seats that is tolerable (the operator drove the
//! hook); for an autonomous principal whose acts accrue trust it is the
//! "aspirational identity" gap: the being's whole witness chain rests on an
//! assertion. This module converts that assertion into evidence with one
//! signature.
//!
//! **Shape.** Two calls, the same nonce discipline as the operator surface
//! (`operator_auth::ChallengeStore`):
//!
//! 1. `hestia_connect_challenge { lct_id }` → the daemon mints 32 random bytes,
//!    binds them to the CLAIMED canonical id, and returns the exact bytes to
//!    sign (`message`), so a non-Rust client (SAGE's `being_gate_client.py`)
//!    reproduces nothing — it signs what it was handed.
//! 2. `hestia_connect { …, proof: { lct_id, public_key, challenge_nonce,
//!    signature } }` → the daemon consumes the nonce (single use, TTL-bounded),
//!    re-derives the id from the presented key, verifies the Ed25519 signature
//!    over the domain-separated message, and only then mints the session with
//!    `identity_basis = proof_of_possession` and `principal_lct_id` set.
//!
//! **Why the id needs no separate registry lookup.** The canonical id IS the
//! key (`web4_core::derive_lct_id`: `sha256(pubkey)` under `lct:web4:mb32:`), so
//! a presented key that derives to the claimed id is, by construction, the key
//! the registry pinned for that id — a forged id is not expressible. What the
//! signature adds is *possession*: the caller holds the seed behind that key,
//! now, for this nonce. Together: "this is the being the registry knows, and it
//! is here."
//!
//! **Pins (fail-closed downgrade, #824).** The first successful proof for a
//! `plugin_id` PINS that label to the proven canonical id, durably in the vault.
//! From then on a connect under that label MUST carry a proof for that id:
//! no proof → `hestia.connect_pop_required`; a proof for a different id →
//! `hestia.connect_pop_principal_mismatch`. A strongly-enrolled principal never
//! silently degrades to an asserted one, and its label cannot be squatted by a
//! later caller. The first sight is the honest weak point (trust-on-first-proof,
//! the same posture `member_registry::ensure_member` already takes for custodial
//! members); an operator pre-pin command is the follow-up, not this change.
//!
//! **Every refusal is witnessed (cbp review on #907, 2026-09-03).** A refused
//! proof leaves state bit-identical apart from the burnt nonce — and until that
//! review it left the *event* bit-identical too: seven refusal codes, each
//! rendered only as an error envelope handed to the party that just failed the
//! check. The one that matters most, `connect_pop_principal_mismatch`, is the
//! label-squat attempt the pin exists to stop, and its only record was the
//! response delivered to the squatter. So the handler appends a
//! `connect_refused` chain entry carrying `(code, plugin_id, claimed_lct_id,
//! pinned_lct_id)` BEFORE returning any refusal, and the envelope carries the
//! entry hash so a reader can join the two without trusting the caller's copy.
//! Absence must be witnessed by someone other than the absent party: the
//! refused caller is not that someone.
//!
//! **What this does NOT do.** It does not authenticate hooked/custodial seats
//! (§4.2 class 1) or paired channels (class 3), and it does not make hestia A2.
//! An unpinned label still connects asserted, exactly as before — the
//! compatibility posture #824 asks for, with the basis reported on the session
//! and on every outcome entry so the two cannot be mistaken for one another.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashMap};
use web4_core::{PublicKey, SignatureBytes, derive_lct_id};

/// Domain separator for the connect proof. Bumping the wire form is a `v2`.
pub const CONNECT_POP_DOMAIN: &str = "web4:hestia:connect:v1";

/// How long a minted challenge may be redeemed. The client signs immediately;
/// the window covers a slow first Ollama tick, not a queue.
pub const CONNECT_POP_TTL_SECS: u64 = 120;

/// Vault document holding `plugin_id → canonical lct_id` pins.
pub const POP_PINS_NAMESPACE: &str = "members";
pub const POP_PINS_DOC: &str = "pop_pins";
pub const POP_PINS_LEGACY_FILE: &str = "pop_pins.json";

/// How a session's principal was established. Reported on the connect response
/// and carried onto every outcome chain entry (#824: "identity basis used on
/// that call/session"), so an asserted session and a proven one are never
/// indistinguishable downstream.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdentityBasis {
    /// `plugin_id` was typed by the caller and nothing proved it (A1, legacy).
    Asserted,
    /// The caller signed a daemon-issued nonce with the key its canonical id
    /// derives from (§4.2 class 2).
    ProofOfPossession,
}

impl IdentityBasis {
    pub fn as_str(self) -> &'static str {
        match self {
            IdentityBasis::Asserted => "asserted",
            IdentityBasis::ProofOfPossession => "proof_of_possession",
        }
    }
}

/// The exact bytes the principal signs. Newline-separated and domain-prefixed
/// like `Lct::binding_message`, so a verifier in any language reconstructs it
/// from three strings — and the challenge response hands it over verbatim
/// anyway, so a client need not reconstruct it at all.
pub fn pop_message(lct_id: &str, nonce_hex: &str) -> Vec<u8> {
    format!("{CONNECT_POP_DOMAIN}\n{lct_id}\n{nonce_hex}").into_bytes()
}

/// Issued-but-unredeemed connect challenges. Each nonce is bound to the id it
/// was minted for: a nonce minted for A cannot be redeemed with a proof for B,
/// even by the holder of B's key, which keeps the challenge log honest about
/// who asked. Single-use and TTL-bounded like the operator store; `now` is
/// passed in (unix seconds) so expiry is testable without a clock.
#[derive(Debug, Default)]
pub struct PopChallengeStore {
    issued: HashMap<String, (String, u64)>,
}

impl PopChallengeStore {
    pub fn issue(&mut self, lct_id: &str, now: u64) -> String {
        use rand::RngCore;
        let mut buf = [0u8; 32];
        rand::rngs::OsRng.fill_bytes(&mut buf);
        let nonce = hex::encode(buf);
        self.issued.insert(nonce.clone(), (lct_id.to_string(), now));
        nonce
    }

    /// Consume a nonce. Removed on every path — a replay fails the second time
    /// and an expired one is cleared. Returns the id it was minted for iff it
    /// was issued and is unexpired.
    pub fn consume(&mut self, nonce: &str, now: u64, ttl_secs: u64) -> Option<String> {
        let (lct_id, issued_at) = self.issued.remove(nonce)?;
        (now.saturating_sub(issued_at) <= ttl_secs).then_some(lct_id)
    }

    pub fn gc(&mut self, now: u64, ttl_secs: u64) {
        self.issued
            .retain(|_, (_, issued_at)| now.saturating_sub(*issued_at) <= ttl_secs);
    }

    pub fn len(&self) -> usize {
        self.issued.len()
    }

    pub fn is_empty(&self) -> bool {
        self.issued.is_empty()
    }
}

/// A verified proof: the canonical id and the key it derives from.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerifiedPrincipal {
    pub lct_id: String,
    pub public_key_hex: String,
}

/// Why a proof was refused — an error code the caller can match on plus the
/// sentence that names the cause. Every arm consumes the nonce first (O:
/// a refused proof leaves no redeemable challenge behind).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PopRefusal {
    pub code: &'static str,
    pub message: String,
    /// The canonical id the proof claimed, when the proof got far enough to
    /// name one. This is what the durable row is FOR: a `principal_mismatch`
    /// with no claimed id would witness that a squat happened but not who
    /// tried it.
    pub claimed_lct_id: Option<String>,
    /// The id the label is pinned to, when a pin was involved in the refusal.
    pub pinned_lct_id: Option<String>,
}

impl PopRefusal {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            claimed_lct_id: None,
            pinned_lct_id: None,
        }
    }

    fn claiming(mut self, lct_id: impl Into<String>) -> Self {
        self.claimed_lct_id = Some(lct_id.into());
        self
    }

    fn pinned(mut self, lct_id: impl Into<String>) -> Self {
        self.pinned_lct_id = Some(lct_id.into());
        self
    }
}

fn field<'a>(proof: &'a Value, name: &str) -> Result<&'a str, PopRefusal> {
    proof
        .get(name)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            PopRefusal::new(
                "hestia.connect_pop_malformed",
                format!("proof.{name} is required (non-empty string)"),
            )
        })
}

/// Verify a `proof` object against the challenge store. Consumes the nonce
/// whatever the outcome. Pure over its inputs apart from that consumption:
/// no session, registry or vault side effect happens here (order: policy
/// decision dominates every side effect).
pub fn verify_proof(
    store: &mut PopChallengeStore,
    proof: &Value,
    now: u64,
    ttl_secs: u64,
) -> Result<VerifiedPrincipal, PopRefusal> {
    if !proof.is_object() {
        return Err(PopRefusal::new(
            "hestia.connect_pop_malformed",
            "proof must be an object { lct_id, public_key, challenge_nonce, signature }",
        ));
    }
    let lct_id = field(proof, "lct_id")?;
    // From here every refusal names the id the caller claimed: the durable row
    // must say WHO was refused, not only that someone was.
    let public_key_hex = field(proof, "public_key").map_err(|r| r.claiming(lct_id))?;
    let nonce = field(proof, "challenge_nonce").map_err(|r| r.claiming(lct_id))?;
    let signature_hex = field(proof, "signature").map_err(|r| r.claiming(lct_id))?;

    // Nonce first, so a malformed key or signature still burns the challenge.
    let bound_id = store.consume(nonce, now, ttl_secs).ok_or_else(|| {
        PopRefusal::new(
            "hestia.connect_pop_challenge_invalid",
            "challenge_nonce was never issued, has expired, or was already redeemed \
             — request a fresh one with hestia_connect_challenge",
        )
        .claiming(lct_id)
    })?;
    if bound_id != lct_id {
        return Err(PopRefusal::new(
            "hestia.connect_pop_challenge_principal_mismatch",
            format!(
                "challenge was issued for {bound_id} but the proof claims {lct_id}; \
                 a challenge binds to the id it was requested for"
            ),
        )
        .claiming(lct_id));
    }

    let pk_bytes: [u8; 32] = hex::decode(public_key_hex)
        .ok()
        .and_then(|v| v.try_into().ok())
        .ok_or_else(|| {
            PopRefusal::new(
                "hestia.connect_pop_malformed",
                "proof.public_key must be 32 bytes of hex (Ed25519 verifying key)",
            )
            .claiming(lct_id)
        })?;
    let public_key = PublicKey::from_bytes(&pk_bytes).map_err(|e| {
        PopRefusal::new(
            "hestia.connect_pop_malformed",
            format!("proof.public_key is not a valid Ed25519 key: {e}"),
        )
        .claiming(lct_id)
    })?;

    // Identity is derived, not assigned: the claimed id must be THIS key's id.
    let derived = derive_lct_id(&public_key);
    if derived != lct_id {
        return Err(PopRefusal::new(
            "hestia.connect_pop_key_mismatch",
            format!(
                "the presented key derives to {derived}, not the claimed {lct_id}; \
                 an id is sha256 of its binding key and cannot be claimed under another"
            ),
        )
        .claiming(lct_id));
    }

    let sig_bytes: [u8; 64] = hex::decode(signature_hex)
        .ok()
        .and_then(|v| v.try_into().ok())
        .ok_or_else(|| {
            PopRefusal::new(
                "hestia.connect_pop_malformed",
                "proof.signature must be 64 bytes of hex (Ed25519 signature)",
            )
            .claiming(lct_id)
        })?;
    let message = pop_message(lct_id, nonce);
    public_key
        .verify(&message, &SignatureBytes::from_bytes(sig_bytes))
        .map_err(|_| {
            PopRefusal::new(
                "hestia.connect_pop_bad_signature",
                format!(
                    "signature does not verify over \"{CONNECT_POP_DOMAIN}\\n<lct_id>\\n<nonce>\" \
                     under the presented key"
                ),
            )
            .claiming(lct_id)
        })?;

    Ok(VerifiedPrincipal {
        lct_id: lct_id.to_string(),
        public_key_hex: public_key_hex.to_string(),
    })
}

/// `plugin_id → canonical lct_id`, persisted in the vault. BTreeMap so the
/// document is reproducible.
pub type PopPins = BTreeMap<String, String>;

/// The pin verdict for a connect, decided BEFORE any side effect.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PinCheck {
    /// No pin for this label and no proof: asserted connect, as before.
    Unpinned,
    /// A proof verified and the label is either unpinned (pin it now) or
    /// pinned to exactly this id.
    Proven { lct_id: String, first_sight: bool },
    /// The label is pinned and this connect does not satisfy the pin.
    Refused(PopRefusal),
}

/// Reconcile a (possibly absent) verified principal against the pins.
pub fn check_pin(pins: &PopPins, plugin_id: &str, verified: Option<&VerifiedPrincipal>) -> PinCheck {
    match (pins.get(plugin_id), verified) {
        (None, None) => PinCheck::Unpinned,
        (None, Some(v)) => PinCheck::Proven {
            lct_id: v.lct_id.clone(),
            first_sight: true,
        },
        (Some(pinned), Some(v)) if pinned == &v.lct_id => PinCheck::Proven {
            lct_id: v.lct_id.clone(),
            first_sight: false,
        },
        (Some(pinned), Some(v)) => PinCheck::Refused(PopRefusal::new(
            "hestia.connect_pop_principal_mismatch",
            format!(
                "'{plugin_id}' is pinned to {pinned}; the proof presented is for {}; \
                 a strongly enrolled label does not change principals by asserting a new key",
                v.lct_id
            ),
        )
        .claiming(v.lct_id.clone())
        .pinned(pinned.clone())),
        (Some(pinned), None) => PinCheck::Refused(PopRefusal::new(
            "hestia.connect_pop_required",
            format!(
                "'{plugin_id}' is pinned to {pinned} and must connect with a proof of possession \
                 (hestia_connect_challenge, then hestia_connect with `proof`); an asserted connect \
                 under a strongly enrolled label is refused, never silently downgraded"
            ),
        )
        .pinned(pinned.clone())),
    }
}

/// The durable form of a refusal: the `event_data` of the `connect_refused`
/// chain entry. Written by the daemon, outside the refused caller — the
/// witness the envelope alone is not. `ts` and the signer come from the chain
/// entry itself.
pub const CONNECT_REFUSED_EVENT: &str = "connect_refused";

pub fn refusal_row(r: &PopRefusal, plugin_id: &str) -> Value {
    json!({
        "code": r.code,
        "plugin_id": plugin_id,
        "claimed_lct_id": r.claimed_lct_id,
        "pinned_lct_id": r.pinned_lct_id,
    })
}

/// The JSON a refusal is rendered as to the caller (the `hestia_error_envelope`
/// shape lives in the handler; this is just the `details`). `refusal_entry_hash`
/// joins the reply to the chain row so a third party can verify the refusal
/// happened without trusting the refused party's copy of this envelope.
pub fn refusal_details(r: &PopRefusal, plugin_id: &str, refusal_entry_hash: &str) -> Value {
    json!({
        "plugin_id": plugin_id,
        "cause": r.code,
        "claimed_lct_id": r.claimed_lct_id,
        "pinned_lct_id": r.pinned_lct_id,
        "refusalEntryHash": refusal_entry_hash,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_core::KeyPair;

    fn principal() -> (KeyPair, String) {
        let kp = KeyPair::generate();
        let id = derive_lct_id(&kp.verifying_key());
        (kp, id)
    }

    fn proof_for(kp: &KeyPair, id: &str, nonce: &str) -> Value {
        let sig = kp.sign(&pop_message(id, nonce));
        json!({
            "lct_id": id,
            "public_key": kp.verifying_key().to_hex(),
            "challenge_nonce": nonce,
            "signature": sig.to_hex(),
        })
    }

    #[test]
    fn a_legitimate_proof_verifies_and_burns_the_nonce() {
        let (kp, id) = principal();
        let mut store = PopChallengeStore::default();
        let nonce = store.issue(&id, 1_000);
        let v = verify_proof(&mut store, &proof_for(&kp, &id, &nonce), 1_010, CONNECT_POP_TTL_SECS)
            .expect("legitimate proof");
        assert_eq!(v.lct_id, id);
        assert_eq!(v.public_key_hex, kp.verifying_key().to_hex());
        assert!(store.is_empty(), "the nonce is consumed on success");
    }

    #[test]
    fn a_replayed_proof_fails_the_second_time() {
        let (kp, id) = principal();
        let mut store = PopChallengeStore::default();
        let nonce = store.issue(&id, 1_000);
        let proof = proof_for(&kp, &id, &nonce);
        verify_proof(&mut store, &proof, 1_001, CONNECT_POP_TTL_SECS).unwrap();
        let err = verify_proof(&mut store, &proof, 1_002, CONNECT_POP_TTL_SECS).unwrap_err();
        assert_eq!(err.code, "hestia.connect_pop_challenge_invalid");
    }

    #[test]
    fn an_expired_challenge_is_refused_and_cleared() {
        let (kp, id) = principal();
        let mut store = PopChallengeStore::default();
        let nonce = store.issue(&id, 1_000);
        let late = 1_000 + CONNECT_POP_TTL_SECS + 1;
        let err = verify_proof(&mut store, &proof_for(&kp, &id, &nonce), late, CONNECT_POP_TTL_SECS)
            .unwrap_err();
        assert_eq!(err.code, "hestia.connect_pop_challenge_invalid");
        assert!(store.is_empty(), "an expired nonce does not linger");
    }

    #[test]
    fn the_wrong_key_cannot_claim_an_id_it_does_not_derive_to() {
        let (_victim, victim_id) = principal();
        let (attacker, _) = principal();
        let mut store = PopChallengeStore::default();
        let nonce = store.issue(&victim_id, 1_000);
        // Attacker signs correctly with their own key but claims the victim's id.
        let err = verify_proof(
            &mut store,
            &proof_for(&attacker, &victim_id, &nonce),
            1_001,
            CONNECT_POP_TTL_SECS,
        )
        .unwrap_err();
        assert_eq!(err.code, "hestia.connect_pop_key_mismatch");
        assert!(store.is_empty(), "a refused proof still burns the challenge");
    }

    #[test]
    fn a_bad_signature_under_the_right_key_is_refused() {
        let (kp, id) = principal();
        let mut store = PopChallengeStore::default();
        let nonce = store.issue(&id, 1_000);
        let mut proof = proof_for(&kp, &id, &nonce);
        // Sign a different message (a stale nonce) under the right key.
        let stale = kp.sign(&pop_message(&id, "00"));
        proof["signature"] = json!(stale.to_hex());
        let err = verify_proof(&mut store, &proof, 1_001, CONNECT_POP_TTL_SECS).unwrap_err();
        assert_eq!(err.code, "hestia.connect_pop_bad_signature");
    }

    #[test]
    fn a_challenge_binds_to_the_id_it_was_requested_for() {
        let (a, a_id) = principal();
        let (_b, b_id) = principal();
        let mut store = PopChallengeStore::default();
        let nonce = store.issue(&b_id, 1_000);
        let err = verify_proof(&mut store, &proof_for(&a, &a_id, &nonce), 1_001, CONNECT_POP_TTL_SECS)
            .unwrap_err();
        assert_eq!(err.code, "hestia.connect_pop_challenge_principal_mismatch");
    }

    #[test]
    fn malformed_proofs_name_the_missing_field_and_burn_nothing_they_never_reached() {
        let mut store = PopChallengeStore::default();
        let err = verify_proof(&mut store, &json!("nope"), 1, 10).unwrap_err();
        assert_eq!(err.code, "hestia.connect_pop_malformed");
        let err = verify_proof(&mut store, &json!({"lct_id": "x"}), 1, 10).unwrap_err();
        assert!(err.message.contains("proof.public_key"), "{}", err.message);
    }

    #[test]
    fn pins_refuse_downgrade_and_substitution_but_admit_the_pinned_principal() {
        let (kp, id) = principal();
        let (_other, other_id) = principal();
        let mut pins = PopPins::new();
        assert_eq!(check_pin(&pins, "being", None), PinCheck::Unpinned);
        let v = VerifiedPrincipal {
            lct_id: id.clone(),
            public_key_hex: kp.verifying_key().to_hex(),
        };
        assert_eq!(
            check_pin(&pins, "being", Some(&v)),
            PinCheck::Proven { lct_id: id.clone(), first_sight: true }
        );
        pins.insert("being".into(), id.clone());
        assert_eq!(
            check_pin(&pins, "being", Some(&v)),
            PinCheck::Proven { lct_id: id.clone(), first_sight: false }
        );
        match check_pin(&pins, "being", None) {
            PinCheck::Refused(r) => assert_eq!(r.code, "hestia.connect_pop_required"),
            other => panic!("expected refusal, got {other:?}"),
        }
        let imposter = VerifiedPrincipal {
            lct_id: other_id,
            public_key_hex: String::new(),
        };
        match check_pin(&pins, "being", Some(&imposter)) {
            PinCheck::Refused(r) => assert_eq!(r.code, "hestia.connect_pop_principal_mismatch"),
            other => panic!("expected refusal, got {other:?}"),
        }
    }

    /// The cross-implementation contract: a Python client that concatenates
    /// three strings with `\n` produces these exact bytes.
    #[test]
    fn the_message_bytes_are_the_documented_three_lines() {
        assert_eq!(
            pop_message("lct:web4:mb32:bx", "abcd"),
            b"web4:hestia:connect:v1\nlct:web4:mb32:bx\nabcd".to_vec()
        );
    }
}

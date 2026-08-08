//! Operator-surface authorization — the RWOA trust-gradient applied to hestia's
//! dashboard/operator surface (ratified 2026-07-12, thread `accountability-invariant`).
//!
//! The operator surface is Web4 authenticating with Web4: an operator proves
//! presence by SIGNING a challenge with their LCT (`vault::OperatorIdentity`,
//! the strong evidence — clause W), never a shared secret. This module adds the
//! rest of the gradient on top of that foundation:
//!
//! - **S (stakes):** every operator act is classified by consequence + reversibility
//!   ([`Stakes`]); the class sets the required evidence and whether V applies.
//! - **V (catastrophic veto):** irreversible acts (a secret RELEASE has no undo; an
//!   irreversible law change; an operator-set change that could lock out) are not
//!   authorized by a single signature — they require a law-defined **quorum** of
//!   distinct operator signatures ([`VaultPolicyState::irreversible_quorum`]), or
//!   escalate. Reversible acts are risk-managed on the single operator's evidence.
//! - **A (self-witnessing):** the decision carries the *evidence relied upon and the
//!   stakes assessment*, not just the act ([`AuthzOutcome::evidence_record`]), so
//!   "proceeded because reversible, on operator X's signature" is a challengeable
//!   record, not a vibe.
//!
//! O (preflight) and the challenge/response + middleware that make this reachable
//! live in the HTTP layer; this module is the pure, testable decision core.

use std::collections::HashMap;

use serde_json::json;

use crate::vault::VaultPolicyState;

/// Default lifetime of an operator challenge (seconds). Short — a challenge is
/// signed and returned within one dashboard round-trip.
pub const CHALLENGE_TTL_SECS: u64 = 120;

/// Anti-replay store of issued, not-yet-consumed operator challenges. A challenge
/// is single-use (consumed on the auth attempt) and time-bounded — a captured
/// signature can't be replayed past its TTL or a second time. `now` is passed in
/// (unix seconds) so the store is deterministic and testable.
#[derive(Debug, Default)]
pub struct ChallengeStore {
    issued: HashMap<String, u64>,
}

impl ChallengeStore {
    /// Mint a fresh, unpredictable challenge nonce (32 random bytes, hex) and
    /// record its issue time. The operator signs this nonce with their LCT key.
    pub fn issue(&mut self, now: u64) -> String {
        use rand::RngCore;
        let mut buf = [0u8; 32];
        rand::rngs::OsRng.fill_bytes(&mut buf);
        let nonce = hex::encode(buf);
        self.issued.insert(nonce.clone(), now);
        nonce
    }

    /// Consume a challenge: valid iff it was issued, is unexpired, and hasn't been
    /// used. Removes it either way (single-use — a replayed nonce fails the second
    /// time, and an expired one is cleared).
    pub fn consume(&mut self, nonce: &str, now: u64, ttl_secs: u64) -> bool {
        match self.issued.remove(nonce) {
            Some(issued_at) => now.saturating_sub(issued_at) <= ttl_secs,
            None => false,
        }
    }

    /// Drop expired challenges (call opportunistically to bound memory).
    pub fn gc(&mut self, now: u64, ttl_secs: u64) {
        self.issued
            .retain(|_, issued_at| now.saturating_sub(*issued_at) <= ttl_secs);
    }

    #[cfg(test)]
    fn len(&self) -> usize {
        self.issued.len()
    }
}

/// Default operator-session lifetime (seconds). A session is established by ONE
/// strong-evidence event (an LCT-signed challenge) and continues *reversible* acts
/// without re-signing. The irreversible tail is NOT covered by the session — it
/// requires fresh per-act signatures (quorum), so the session token is never a
/// bearer credential for consequential-irreversible acts (RWOA gradient: the
/// strong evidence given at establishment is sufficient for the reversible
/// majority; the irreversible tail always re-collects evidence).
pub const SESSION_TTL_SECS: u64 = 3600;
pub const SESSION_TRANSCRIPT_DOMAIN: &str = "hestia:operator-session:v1";
pub const SOVEREIGN_OFFICE: &str = "role:constellation:sovereign";
const MAX_COMPOSITION_FIELD_BYTES: usize = 512;

/// The identity/authority composition carried by an app-originated operator session.
///
/// `principal` proves the challenge; `actor` is the harness that sent the request.
/// The remaining fields say through which anchor, office, and authority it acts. Keeping
/// this typed in the session store prevents later request records from reconstructing a
/// weaker story from only the principal LCT.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OperatorProvenance {
    pub actor: String,
    pub principal: String,
    pub via_device: String,
    pub office: String,
    pub authority: String,
}

impl OperatorProvenance {
    pub fn validate(&self) -> Result<(), &'static str> {
        for (name, value) in [
            ("actor", self.actor.as_str()),
            ("principal", self.principal.as_str()),
            ("via_device", self.via_device.as_str()),
            ("office", self.office.as_str()),
            ("authority", self.authority.as_str()),
        ] {
            if value.trim().is_empty() || value.trim() != value {
                return Err(match name {
                    "actor" => "actor must be non-empty and trimmed",
                    "principal" => "principal must be non-empty and trimmed",
                    "via_device" => "via_device must be non-empty and trimmed",
                    "office" => "office must be non-empty and trimmed",
                    _ => "authority must be non-empty and trimmed",
                });
            }
            if value.len() > MAX_COMPOSITION_FIELD_BYTES || value.chars().any(char::is_control) {
                return Err("composition fields must be bounded printable strings");
            }
        }
        if self.actor == self.principal {
            return Err("actor and principal must be distinct identities");
        }
        if self.actor == self.via_device || self.principal == self.via_device {
            return Err("actor, principal, and via_device must be distinct identities");
        }
        if !self.actor.starts_with("lct:web4:")
            || !self.principal.starts_with("lct:web4:")
            || !self.via_device.starts_with("lct:web4:")
        {
            return Err("actor, principal, and via_device must be canonical Web4 LCT ids");
        }
        if self.office != SOVEREIGN_OFFICE {
            return Err("operator sessions must exercise the sovereign office");
        }
        Ok(())
    }

    pub fn validate_for_challenge(&self, challenge: &str) -> Result<(), &'static str> {
        self.validate()?;
        let expected = format!("operator-session:{challenge}");
        if self.authority != expected {
            return Err("authority must name the daemon-issued operator session challenge");
        }
        Ok(())
    }
}

/// Length-delimited, domain-separated bytes signed by the principal, app
/// harness, and device anchor. This is duplicated in the app identity domain;
/// pinned test vectors on both sides make drift fail closed.
pub fn canonical_session_transcript(
    challenge: &str,
    provenance: &OperatorProvenance,
    actor_public_key: &str,
    device_public_key: &str,
) -> Vec<u8> {
    let fields = [
        ("challenge", challenge),
        ("actor", provenance.actor.as_str()),
        ("actor_public_key", actor_public_key),
        ("principal", provenance.principal.as_str()),
        ("via_device", provenance.via_device.as_str()),
        ("device_public_key", device_public_key),
        ("office", provenance.office.as_str()),
        ("authority", provenance.authority.as_str()),
    ];
    let mut out = format!("{SESSION_TRANSCRIPT_DOMAIN}\n").into_bytes();
    for (name, value) in fields {
        out.extend_from_slice(format!("{name}:{}\n", value.len()).as_bytes());
        out.extend_from_slice(value.as_bytes());
        out.push(b'\n');
    }
    out
}

/// Existing dashboard sessions prove one operator directly; app sessions carry the
/// complete harness composition. The legacy variant keeps the browser dashboard live
/// while making it impossible for an app session to lose fields once admitted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OperatorSessionIdentity {
    DirectOperator(String),
    Composed(OperatorProvenance),
}

impl From<String> for OperatorSessionIdentity {
    fn from(value: String) -> Self {
        Self::DirectOperator(value)
    }
}

impl From<&str> for OperatorSessionIdentity {
    fn from(value: &str) -> Self {
        Self::DirectOperator(value.to_string())
    }
}

impl From<OperatorProvenance> for OperatorSessionIdentity {
    fn from(value: OperatorProvenance) -> Self {
        Self::Composed(value)
    }
}

impl OperatorSessionIdentity {
    fn principal(&self) -> &str {
        match self {
            Self::DirectOperator(operator) => operator,
            Self::Composed(provenance) => &provenance.principal,
        }
    }

    fn provenance(&self) -> Option<&OperatorProvenance> {
        match self {
            Self::DirectOperator(_) => None,
            Self::Composed(provenance) => Some(provenance),
        }
    }
}

/// Established operator sessions: opaque token → (identity composition, issued_at).
#[derive(Debug, Default)]
pub struct SessionStore {
    sessions: HashMap<String, (OperatorSessionIdentity, u64)>,
}

impl SessionStore {
    /// Open a session for an already-authenticated operator; returns the opaque
    /// bearer token (32 random bytes hex) the client presents on later requests.
    pub fn open(&mut self, identity: impl Into<OperatorSessionIdentity>, now: u64) -> String {
        use rand::RngCore;
        let mut buf = [0u8; 32];
        rand::rngs::OsRng.fill_bytes(&mut buf);
        let token = hex::encode(buf);
        self.sessions.insert(token.clone(), (identity.into(), now));
        token
    }

    /// Resolve a session token to its operator lct_id iff present and unexpired.
    pub fn operator(&self, token: &str, now: u64, ttl_secs: u64) -> Option<&str> {
        self.sessions.get(token).and_then(|(identity, issued)| {
            (now.saturating_sub(*issued) <= ttl_secs).then(|| identity.principal())
        })
    }

    /// Resolve the complete provenance tuple for an app session. A direct browser
    /// session deliberately returns `None`; it must never be dressed up as an app.
    pub fn provenance(&self, token: &str, now: u64, ttl_secs: u64) -> Option<&OperatorProvenance> {
        self.sessions.get(token).and_then(|(identity, issued)| {
            (now.saturating_sub(*issued) <= ttl_secs)
                .then(|| identity.provenance())
                .flatten()
        })
    }

    /// Close a session (operator logout / revocation).
    pub fn close(&mut self, token: &str) {
        self.sessions.remove(token);
    }

    pub fn gc(&mut self, now: u64, ttl_secs: u64) {
        self.sessions
            .retain(|_, (_, issued)| now.saturating_sub(*issued) <= ttl_secs);
    }
}

/// Canonical chain payload for a composed session. One helper is shared by the
/// endpoint and tests so adding a field to the type without recording it fails.
pub fn operator_session_opened_record(provenance: &OperatorProvenance) -> serde_json::Value {
    json!({
        "actor": provenance.actor,
        "principal": provenance.principal,
        "via_device": provenance.via_device,
        "office": provenance.office,
        "authority": provenance.authority,
        "session_ref": provenance.authority,
        "evidence": "principal+harness+device-signatures:v1",
        "device_evidence": "self-issued-app-vault-key",
        "authority_evidence": "principal-signature-over-session-composition",
        "transcript": SESSION_TRANSCRIPT_DOMAIN,
    })
}

/// Attach the composed identity to an app act's existing evidence record.
pub fn attach_operator_provenance(
    mut record: serde_json::Value,
    provenance: Option<&OperatorProvenance>,
) -> serde_json::Value {
    let (Some(object), Some(provenance)) = (record.as_object_mut(), provenance) else {
        return record;
    };
    object.insert("actor".into(), json!(provenance.actor));
    object.insert("principal".into(), json!(provenance.principal));
    object.insert("via_device".into(), json!(provenance.via_device));
    object.insert("office".into(), json!(provenance.office));
    object.insert("authority".into(), json!(provenance.authority));
    object.insert("session_ref".into(), json!(provenance.authority));
    object.insert(
        "composition_evidence".into(),
        json!("principal+harness+device-signatures:v1"),
    );
    record
}

/// Request-level gate (clause O, at the middleware). Given the operator resolved
/// from the request's session (if any) and the act's stakes, decide. Reuses the
/// gradient [`authorize`]: a session is exactly ONE signer, so reversible acts
/// authorize and the irreversible tail returns `RequiresQuorum` — which the
/// middleware surfaces as an escalation (collect fresh per-act operator
/// signatures), never a silent pass.
pub fn gate_session_request(
    law: &VaultPolicyState,
    session_operator: Option<&str>,
    stakes: Stakes,
) -> AuthzOutcome {
    match session_operator {
        None => AuthzOutcome::Denied {
            stakes,
            reason: "no operator session (present an LCT-signed challenge first)".into(),
        },
        Some(op) => authorize(law, stakes, std::slice::from_ref(&op.to_string())),
    }
}

/// Verify one operator's signed challenge (RWOA clause W — the strong evidence).
/// Returns the authorized operator's `lct_id` iff: the challenge was valid +
/// unexpired + unused (consumed here, anti-replay), the signature hex is
/// well-formed, and it verifies against an identity in `operator_access`.
/// Fail-closed on every miss. `now`/`ttl` make the challenge lifetime explicit.
pub fn authenticate_operator(
    law: &VaultPolicyState,
    store: &mut ChallengeStore,
    lct_id: &str,
    challenge: &str,
    signature_hex: &str,
    now: u64,
    ttl_secs: u64,
) -> Option<String> {
    // Consume the challenge FIRST — even a bad attempt burns the nonce, so a
    // captured challenge can't be reused to grind signatures.
    if !store.consume(challenge, now, ttl_secs) {
        return None;
    }
    let raw = hex::decode(signature_hex.trim()).ok()?;
    let sig_bytes: [u8; 64] = raw.try_into().ok()?;
    let sig = web4_core::crypto::SignatureBytes::from_bytes(sig_bytes);
    law.authorize_operator(lct_id, challenge.as_bytes(), &sig)
        .map(|op| op.lct_id.clone())
}

/// Authenticate a composed app session. All semantic fields and both local
/// public keys are covered by three signatures: the authorized principal,
/// the app harness, and the device anchor. The daemon re-derives actor/device
/// LCT ids from their keys rather than accepting caller labels.
#[allow(clippy::too_many_arguments)]
pub fn authenticate_composed_operator(
    law: &VaultPolicyState,
    store: &mut ChallengeStore,
    provenance: &OperatorProvenance,
    challenge: &str,
    actor_public_key_hex: &str,
    device_public_key_hex: &str,
    principal_signature_hex: &str,
    actor_signature_hex: &str,
    device_signature_hex: &str,
    now: u64,
    ttl_secs: u64,
) -> Option<String> {
    provenance.validate_for_challenge(challenge).ok()?;

    // Preserve the legacy endpoint's anti-replay property: any cryptographic
    // attempt consumes the nonce, even when a later proof is invalid.
    if !store.consume(challenge, now, ttl_secs) {
        return None;
    }

    let actor_key = decode_public_key(actor_public_key_hex)?;
    let device_key = decode_public_key(device_public_key_hex)?;
    if web4_core::lct::derive_lct_id(&actor_key) != provenance.actor
        || web4_core::lct::derive_lct_id(&device_key) != provenance.via_device
    {
        return None;
    }

    let transcript = canonical_session_transcript(
        challenge,
        provenance,
        actor_public_key_hex,
        device_public_key_hex,
    );
    let principal_signature = decode_signature(principal_signature_hex)?;
    let actor_signature = decode_signature(actor_signature_hex)?;
    let device_signature = decode_signature(device_signature_hex)?;

    actor_key.verify(&transcript, &actor_signature).ok()?;
    device_key.verify(&transcript, &device_signature).ok()?;
    law.authorize_operator(&provenance.principal, &transcript, &principal_signature)
        .map(|op| op.lct_id.clone())
}

fn decode_signature(value: &str) -> Option<web4_core::crypto::SignatureBytes> {
    let bytes: [u8; 64] = hex::decode(value.trim()).ok()?.try_into().ok()?;
    Some(web4_core::crypto::SignatureBytes::from_bytes(bytes))
}

fn decode_public_key(value: &str) -> Option<web4_core::crypto::PublicKey> {
    let bytes: [u8; 32] = hex::decode(value.trim()).ok()?.try_into().ok()?;
    web4_core::crypto::PublicKey::from_bytes(&bytes).ok()
}

/// Consequence + reversibility of an operator act (clause S). The gradient:
/// weaker evidence suffices lower down; the irreversible tail triggers V.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stakes {
    /// Reads / observability (dashboard JSON, failure feed, chain query). Low
    /// consequence, fully reversible — an authenticated operator session suffices.
    LowReversible,
    /// Config/policy edits (preset, overrides, rules, per-`(instance,role)` overlay,
    /// adding an operator, deleting a stored secret). High consequence but UNDOABLE —
    /// a single operator's strong evidence (their LCT signature) authorizes.
    HighReversible,
    /// The irreversible tail — a secret RELEASE (a read has no undo), an irreversible
    /// law change, or removing the last operator (lockout). Clause V: requires a
    /// law-defined quorum of distinct operator signatures, or escalate.
    Irreversible,
}

impl Stakes {
    /// Classify an operator-surface act by HTTP method + path (the S classification
    /// of the surface). Unknown/ambiguous operator routes default to the strictest
    /// applicable tier (fail-closed): a write is at least HighReversible.
    pub fn classify(method: &str, path: &str) -> Stakes {
        let m = method.to_ascii_uppercase();
        // Reads are low/reversible — EXCEPT releasing a secret, which is irreversible.
        if m == "GET" {
            // GET /api/vault/<name> releases a secret's value — a read with no undo.
            if path.starts_with("/api/vault/") && path.len() > "/api/vault/".len() {
                return Stakes::Irreversible;
            }
            return Stakes::LowReversible;
        }
        // Removing the last operator or an irreversible law amendment: the caller
        // marks these Irreversible explicitly via `classify_op` below; by path alone
        // a DELETE on the operator set is treated as irreversible (lockout risk).
        if (m == "DELETE" || m == "PUT") && path.starts_with("/api/operator") {
            return Stakes::Irreversible;
        }
        // All other operator writes (policy/vault mutations) are high but reversible.
        Stakes::HighReversible
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Stakes::LowReversible => "low-reversible",
            Stakes::HighReversible => "high-reversible",
            Stakes::Irreversible => "irreversible",
        }
    }

    fn is_irreversible(self) -> bool {
        matches!(self, Stakes::Irreversible)
    }
}

/// The gradient verdict on an operator act given the evidence presented (the set
/// of DISTINCT authorized-operator LCTs whose valid signatures accompany the act).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthzOutcome {
    /// Sufficient preponderance for the stakes — proceed.
    Authorized {
        stakes: Stakes,
        signers: Vec<String>,
    },
    /// Clause V: an irreversible act without the law-required quorum. Block and
    /// escalate (collect more operator signatures, or a human gate). NOT a failure —
    /// a recorded, resumable "needs more evidence" state.
    RequiresQuorum {
        have: u32,
        need: u32,
        signers: Vec<String>,
    },
    /// No admissible evidence for the act's stakes (e.g. a high-stakes act with no
    /// valid operator signature, or the surface not bootstrapped). Deny.
    Denied { stakes: Stakes, reason: String },
}

impl AuthzOutcome {
    pub fn is_authorized(&self) -> bool {
        matches!(self, AuthzOutcome::Authorized { .. })
    }

    /// The self-witnessing record (clause A): the act's stakes assessment + the
    /// evidence relied upon + the verdict. Appended to the witness chain with the
    /// act, so the gradient judgment is auditable and challengeable.
    pub fn evidence_record(&self, act: &str) -> serde_json::Value {
        match self {
            AuthzOutcome::Authorized { stakes, signers } => json!({
                "act": act, "verdict": "authorized",
                "stakes": stakes.as_str(), "evidence": "operator-lct-signature",
                "signers": signers,
            }),
            AuthzOutcome::RequiresQuorum {
                have,
                need,
                signers,
            } => json!({
                "act": act, "verdict": "requires-quorum",
                "stakes": "irreversible", "evidence": "operator-lct-signature",
                "signers": signers, "have": have, "need": need,
            }),
            AuthzOutcome::Denied { stakes, reason } => json!({
                "act": act, "verdict": "denied",
                "stakes": stakes.as_str(), "reason": reason,
            }),
        }
    }
}

/// The gradient decision: given the law, an act's `stakes`, and the DISTINCT
/// authorized operators whose valid signatures accompany the act, decide.
///
/// - LowReversible: any authenticated operator (>=1 signer) proceeds.
/// - HighReversible: a single operator's strong evidence authorizes.
/// - Irreversible: requires `law.irreversible_quorum()` distinct signers (clause V);
///   fewer ⇒ RequiresQuorum (escalate).
///
/// `signers` MUST already be de-duplicated and confined to authorized operators
/// (the caller verifies each signature against `operator_access`). Empty ⇒ deny.
pub fn authorize(law: &VaultPolicyState, stakes: Stakes, signers: &[String]) -> AuthzOutcome {
    if !law.operator_access_bootstrapped() {
        return AuthzOutcome::Denied {
            stakes,
            reason: "operator surface not bootstrapped — no authorized operator".into(),
        };
    }
    let n = signers.len() as u32;
    if n == 0 {
        return AuthzOutcome::Denied {
            stakes,
            reason: "no valid operator signature".into(),
        };
    }
    if stakes.is_irreversible() {
        let need = law.irreversible_quorum();
        if n >= need {
            AuthzOutcome::Authorized {
                stakes,
                signers: signers.to_vec(),
            }
        } else {
            AuthzOutcome::RequiresQuorum {
                have: n,
                need,
                signers: signers.to_vec(),
            }
        }
    } else {
        // low/high reversible: a single authorized operator's evidence suffices
        AuthzOutcome::Authorized {
            stakes,
            signers: signers.to_vec(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::vault::policy_state::OperatorIdentity;

    fn law_with_ops(n: usize, quorum: Option<u32>) -> VaultPolicyState {
        let mut law = VaultPolicyState::default();
        for i in 0..n {
            law.operator_access.push(OperatorIdentity {
                lct_id: format!("lct:web4:operator:{i}"),
                public_key_hex: "00".repeat(32),
                label: String::new(),
            });
        }
        law.operator_irreversible_quorum = quorum;
        law
    }

    #[test]
    fn stakes_classification() {
        assert_eq!(
            Stakes::classify("GET", "/api/dashboard"),
            Stakes::LowReversible
        );
        assert_eq!(Stakes::classify("GET", "/api/chain"), Stakes::LowReversible);
        // releasing a secret's value is a read with no undo
        assert_eq!(
            Stakes::classify("GET", "/api/vault/openai-key"),
            Stakes::Irreversible
        );
        // policy edits are high but reversible
        assert_eq!(
            Stakes::classify("PUT", "/api/policy/rule"),
            Stakes::HighReversible
        );
        assert_eq!(
            Stakes::classify("POST", "/api/policy/instance"),
            Stakes::HighReversible
        );
        // operator-set changes risk lockout → irreversible tail
        assert_eq!(
            Stakes::classify("DELETE", "/api/operator/lct:x"),
            Stakes::Irreversible
        );
    }

    #[test]
    fn reversible_acts_pass_on_single_operator() {
        let law = law_with_ops(3, Some(2));
        let one = vec!["lct:web4:operator:0".to_string()];
        assert!(authorize(&law, Stakes::LowReversible, &one).is_authorized());
        assert!(authorize(&law, Stakes::HighReversible, &one).is_authorized());
    }

    #[test]
    fn irreversible_needs_quorum_else_escalates() {
        let law = law_with_ops(3, Some(2));
        let one = vec!["lct:web4:operator:0".to_string()];
        let two = vec![
            "lct:web4:operator:0".to_string(),
            "lct:web4:operator:1".to_string(),
        ];

        // one signature on an irreversible act → RequiresQuorum (escalate), NOT authorized
        match authorize(&law, Stakes::Irreversible, &one) {
            AuthzOutcome::RequiresQuorum { have, need, .. } => {
                assert_eq!((have, need), (1, 2));
            }
            other => panic!("expected RequiresQuorum, got {other:?}"),
        }
        // quorum met → authorized
        assert!(authorize(&law, Stakes::Irreversible, &two).is_authorized());
    }

    #[test]
    fn no_signature_or_unbootstrapped_denies() {
        let bootstrapped = law_with_ops(1, None);
        assert!(matches!(
            authorize(&bootstrapped, Stakes::HighReversible, &[]),
            AuthzOutcome::Denied { .. }
        ));
        let empty = law_with_ops(0, None);
        assert!(matches!(
            authorize(
                &empty,
                Stakes::LowReversible,
                &["lct:web4:operator:0".into()]
            ),
            AuthzOutcome::Denied { .. }
        ));
    }

    #[test]
    fn session_store_and_request_gate() {
        let mut sessions = SessionStore::default();
        let law = law_with_ops(3, Some(2));

        // no session → every act denied (unauthenticated)
        assert!(matches!(
            gate_session_request(&law, None, Stakes::LowReversible),
            AuthzOutcome::Denied { .. }
        ));

        // open a session for op0
        let tok = sessions.open("lct:web4:operator:0", 1000);
        assert_eq!(
            sessions.operator(&tok, 1500, SESSION_TTL_SECS),
            Some("lct:web4:operator:0")
        );
        // expired token resolves to nothing
        assert_eq!(
            sessions.operator(&tok, 1000 + SESSION_TTL_SECS + 1, SESSION_TTL_SECS),
            None
        );

        let op = sessions.operator(&tok, 1500, SESSION_TTL_SECS);
        // reversible acts pass on the session's single operator
        assert!(gate_session_request(&law, op, Stakes::LowReversible).is_authorized());
        assert!(gate_session_request(&law, op, Stakes::HighReversible).is_authorized());
        // irreversible acts do NOT pass on the session alone → escalate (needs quorum)
        assert!(matches!(
            gate_session_request(&law, op, Stakes::Irreversible),
            AuthzOutcome::RequiresQuorum {
                have: 1,
                need: 2,
                ..
            }
        ));

        // closed session → denied again
        sessions.close(&tok);
        assert_eq!(sessions.operator(&tok, 1500, SESSION_TTL_SECS), None);
    }

    /// Sprint A / A4 RED guard. A session is not merely "the operator": it is the
    /// authority chain through which a distinct harness acts for a principal. If any
    /// field disappears here, later chain records cannot reconstruct it.
    #[test]
    fn operator_session_preserves_the_full_provenance_tuple() {
        let provenance = OperatorProvenance {
            actor: "lct:web4:app:test-instance".into(),
            principal: "lct:web4:human:test-principal".into(),
            via_device: "lct:web4:device:test-phone".into(),
            office: "role:constellation:sovereign".into(),
            authority: "occupancy:test-session-authority".into(),
        };
        assert_ne!(provenance.actor, provenance.principal);

        let mut sessions = SessionStore::default();
        let token = sessions.open(provenance.clone(), 1_000);
        let resolved = sessions
            .provenance(&token, 1_001, SESSION_TTL_SECS)
            .expect("fresh session must resolve");
        assert_eq!(resolved, &provenance);

        let record = operator_session_opened_record(resolved);
        for (field, expected) in [
            ("actor", provenance.actor.as_str()),
            ("principal", provenance.principal.as_str()),
            ("via_device", provenance.via_device.as_str()),
            ("office", provenance.office.as_str()),
            ("authority", provenance.authority.as_str()),
        ] {
            assert_eq!(
                record.get(field).and_then(|v| v.as_str()),
                Some(expected),
                "operator session record dropped {field}"
            );
        }
        assert_eq!(record["session_ref"], provenance.authority);
        assert_eq!(record["evidence"], "principal+harness+device-signatures:v1");

        let later = attach_operator_provenance(
            json!({"act": "POST /api/operator/gate-escalation"}),
            Some(&provenance),
        );
        assert_eq!(later["session_ref"], provenance.authority);
        assert_eq!(later["actor"], provenance.actor);
        assert_eq!(later["principal"], provenance.principal);
    }

    #[test]
    fn challenge_store_is_single_use_and_time_bounded() {
        let mut s = ChallengeStore::default();
        let n = s.issue(1000);
        assert_eq!(s.len(), 1);
        // wrong nonce → no
        assert!(!s.consume("deadbeef", 1000, CHALLENGE_TTL_SECS));
        // valid within TTL → yes, and consumed (single-use)
        assert!(s.consume(&n, 1030, CHALLENGE_TTL_SECS));
        assert!(
            !s.consume(&n, 1030, CHALLENGE_TTL_SECS),
            "replay of a consumed nonce fails"
        );
        assert_eq!(s.len(), 0);
        // expired → no (and cleared)
        let n2 = s.issue(2000);
        assert!(!s.consume(&n2, 2000 + CHALLENGE_TTL_SECS + 1, CHALLENGE_TTL_SECS));
        assert_eq!(s.len(), 0);
    }

    #[test]
    fn authenticate_operator_full_flow_fail_closed() {
        use web4_core::crypto::KeyPair;
        let kp = KeyPair::generate();
        let mut law = VaultPolicyState::default();
        law.operator_access.push(OperatorIdentity {
            lct_id: "lct:web4:operator:dp".into(),
            public_key_hex: hex::encode(kp.public_key_bytes()),
            label: String::new(),
        });
        let mut store = ChallengeStore::default();

        // happy path: issue → sign → authenticate
        let ch = store.issue(1000);
        let sig = kp.sign(ch.as_bytes());
        let got = authenticate_operator(
            &law,
            &mut store,
            "lct:web4:operator:dp",
            &ch,
            &sig.to_hex(),
            1000,
            CHALLENGE_TTL_SECS,
        );
        assert_eq!(got.as_deref(), Some("lct:web4:operator:dp"));

        // replay of the SAME challenge+sig → fail (nonce already consumed)
        assert!(
            authenticate_operator(
                &law,
                &mut store,
                "lct:web4:operator:dp",
                &ch,
                &sig.to_hex(),
                1000,
                CHALLENGE_TTL_SECS,
            )
            .is_none()
        );

        // wrong signer on a fresh challenge → fail (nonce still consumed)
        let ch2 = store.issue(1000);
        let attacker = KeyPair::generate();
        let bad = attacker.sign(ch2.as_bytes());
        assert!(
            authenticate_operator(
                &law,
                &mut store,
                "lct:web4:operator:dp",
                &ch2,
                &bad.to_hex(),
                1000,
                CHALLENGE_TTL_SECS,
            )
            .is_none()
        );

        // expired challenge → fail
        let ch3 = store.issue(1000);
        let sig3 = kp.sign(ch3.as_bytes());
        assert!(
            authenticate_operator(
                &law,
                &mut store,
                "lct:web4:operator:dp",
                &ch3,
                &sig3.to_hex(),
                9999,
                CHALLENGE_TTL_SECS,
            )
            .is_none()
        );
    }

    #[test]
    fn composed_session_requires_all_three_signers_and_binds_every_field() {
        use web4_core::{crypto::KeyPair, lct::derive_lct_id};

        let principal_key = KeyPair::generate();
        let actor_key = KeyPair::generate();
        let device_key = KeyPair::generate();
        let principal = "lct:web4:operator:dp".to_string();
        let actor = derive_lct_id(&actor_key.verifying_key());
        let device = derive_lct_id(&device_key.verifying_key());
        let actor_public = hex::encode(actor_key.public_key_bytes());
        let device_public = hex::encode(device_key.public_key_bytes());
        let mut law = VaultPolicyState::default();
        law.operator_access.push(OperatorIdentity {
            lct_id: principal.clone(),
            public_key_hex: hex::encode(principal_key.public_key_bytes()),
            label: String::new(),
        });
        let mut store = ChallengeStore::default();

        let challenge = store.issue(1_000);
        let provenance = OperatorProvenance {
            actor: actor.clone(),
            principal: principal.clone(),
            via_device: device.clone(),
            office: "role:constellation:sovereign".into(),
            authority: format!("operator-session:{challenge}"),
        };
        let transcript =
            canonical_session_transcript(&challenge, &provenance, &actor_public, &device_public);
        let authenticated = authenticate_composed_operator(
            &law,
            &mut store,
            &provenance,
            &challenge,
            &actor_public,
            &device_public,
            &principal_key.sign(&transcript).to_hex(),
            &actor_key.sign(&transcript).to_hex(),
            &device_key.sign(&transcript).to_hex(),
            1_000,
            CHALLENGE_TTL_SECS,
        );
        assert_eq!(authenticated.as_deref(), Some(principal.as_str()));

        // Each semantic field is changed only AFTER all signatures were made.
        // Every mutation must fail, including fields the policy engine does not
        // otherwise interpret (office and authority).
        for field in ["actor", "principal", "via_device", "office", "authority"] {
            let challenge = store.issue(2_000);
            let mut changed = OperatorProvenance {
                actor: actor.clone(),
                principal: principal.clone(),
                via_device: device.clone(),
                office: "role:constellation:sovereign".into(),
                authority: format!("operator-session:{challenge}"),
            };
            let transcript =
                canonical_session_transcript(&challenge, &changed, &actor_public, &device_public);
            let principal_sig = principal_key.sign(&transcript).to_hex();
            let actor_sig = actor_key.sign(&transcript).to_hex();
            let device_sig = device_key.sign(&transcript).to_hex();
            match field {
                "actor" => changed.actor.push('x'),
                "principal" => changed.principal.push('x'),
                "via_device" => changed.via_device.push('x'),
                "office" => changed.office.push('x'),
                "authority" => changed.authority.push('x'),
                _ => unreachable!(),
            }
            assert!(
                authenticate_composed_operator(
                    &law,
                    &mut store,
                    &changed,
                    &challenge,
                    &actor_public,
                    &device_public,
                    &principal_sig,
                    &actor_sig,
                    &device_sig,
                    2_000,
                    CHALLENGE_TTL_SECS,
                )
                .is_none(),
                "changing {field} after signing was accepted"
            );
        }

        for missing in ["principal", "actor", "device"] {
            let challenge = store.issue(3_000);
            let provenance = OperatorProvenance {
                actor: actor.clone(),
                principal: principal.clone(),
                via_device: device.clone(),
                office: SOVEREIGN_OFFICE.into(),
                authority: format!("operator-session:{challenge}"),
            };
            let transcript = canonical_session_transcript(
                &challenge,
                &provenance,
                &actor_public,
                &device_public,
            );
            let mut principal_sig = principal_key.sign(&transcript).to_hex();
            let mut actor_sig = actor_key.sign(&transcript).to_hex();
            let mut device_sig = device_key.sign(&transcript).to_hex();
            match missing {
                "principal" => principal_sig.clear(),
                "actor" => actor_sig.clear(),
                "device" => device_sig.clear(),
                _ => unreachable!(),
            }
            assert!(
                authenticate_composed_operator(
                    &law,
                    &mut store,
                    &provenance,
                    &challenge,
                    &actor_public,
                    &device_public,
                    &principal_sig,
                    &actor_sig,
                    &device_sig,
                    3_000,
                    CHALLENGE_TTL_SECS,
                )
                .is_none(),
                "session opened without the {missing} signature"
            );
        }
    }

    #[test]
    fn composed_session_transcript_matches_the_app_vector() {
        let provenance = OperatorProvenance {
            actor: "lct:web4:mb32:bactor".into(),
            principal: "lct:web4:mb32:bprincipal".into(),
            via_device: "lct:web4:mb32:bdevice".into(),
            office: "role:constellation:sovereign".into(),
            authority: "operator-session:abc".into(),
        };
        let transcript =
            canonical_session_transcript("abc", &provenance, &"11".repeat(32), &"22".repeat(32));
        assert_eq!(
            web4_core::crypto::sha256_hex(&transcript),
            "0524720396a6a9be07c5fa62e9e736e1d1302d59e37d7daf3609d8f87bd492a1",
            "app/daemon transcript drifted; bump the domain version"
        );
    }

    #[test]
    fn evidence_record_is_self_witnessing() {
        let law = law_with_ops(2, Some(2));
        let rec = authorize(
            &law,
            Stakes::HighReversible,
            &["lct:web4:operator:0".into()],
        )
        .evidence_record("PUT /api/policy/rule");
        assert_eq!(rec["verdict"], "authorized");
        assert_eq!(rec["stakes"], "high-reversible");
        assert_eq!(rec["evidence"], "operator-lct-signature");
        assert_eq!(rec["signers"][0], "lct:web4:operator:0");
    }
}

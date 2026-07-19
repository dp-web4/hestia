//! Paired-channel client — hestia's half of the hub's paired-channel broker
//! (CBP sprints A–F on web4 main).
//!
//! **The architecture (dp, 2026-07-18, per the patents):** the HUB is the
//! *authentication controller*. When it admits a pairing between two members
//! (chapter-law gate at `pairing_requested`) it **establishes a sealed
//! channel**; the confirmed-pair detail delivers each side the peer's ephemeral
//! **pairing key**. Participants then *"negotiate additional security layers as
//! needed, using the sealed channel as transport."* A secret is one such layer:
//! it rides the channel as a `pair_message`, sealed end-to-end.
//!
//! This supersedes the earlier `send_secret` + registry-`sealed_by` path (a
//! parallel PKI the pairing obviates). On a confirmed pair there is nothing to
//! resolve by `sealed_by`: the recipient already holds the peer's ephemeral key
//! by `pair_id`. The one lookup that remains is the peer's *static* LCT pubkey
//! for the v2 key's authentication half (`seal_fs` mixes static‖ephemeral ECDH)
//! — the hub *resolver*'s job (a public-key fact), not a private roster.
//!
//! Crypto is entirely `web4_core::pair_channel` (`EphemeralKeyPair`, `seal_fs`,
//! `open_fs`, `derive_session_key_v2`) so hestia and CBP's client interoperate
//! byte-for-byte — one primitive, no reimplementation.
//!
//! **State (forward secrecy):** each side keeps its per-pair ephemeral SECRET
//! for the pair's life and wipes it on revoke/expiry (Sprint F). We persist it
//! **vault-sealed** (`presence/pairings`) so the daemon can reopen the channel
//! across restarts without exposing the secret at rest.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;
use web4_core::crypto::{KeyPair, PublicKey};
use web4_core::pair_channel::{
    ephemeral_public_from_hex, open_fs, seal_fs, EphemeralKeyPair, Sealed,
};

/// Which side of the pair we are — decides *which* ephemeral field in the pair
/// detail is the PEER's (each party reads the other's).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PairingRole {
    /// We sent `pair_request`; the peer is the `counterparty`.
    Initiator,
    /// We sent `pair_confirm`; the peer is the `initiator`.
    Confirmer,
}

/// Our persisted per-pair state. The ephemeral secret is the forward-secrecy
/// material; it lives here vault-sealed and is dropped when the pair ends.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Pairing {
    pub pair_id: Uuid,
    /// The peer's hub-member uuid (the channel identity the hub authenticates).
    pub peer_uuid: Uuid,
    pub role: PairingRole,
    pub purpose: String,
    /// Our per-session X25519 ephemeral SECRET (hex). Forward-secret material —
    /// never leaves the vault; wiped on revoke.
    pub my_ephemeral_secret_hex: String,
    /// The peer's STATIC LCT public key (hex) — the authentication half of the
    /// v2 key (`seal_fs` mixes static‖ephemeral). Resolved once from the hub
    /// registry at establish/confirm time and persisted so send/recv need no
    /// repeated O(N) uuid→LCT lookup.
    pub peer_lct_pubkey_hex: String,
}

impl Pairing {
    /// Reconstruct our ephemeral keypair from the persisted secret.
    pub fn my_ephemeral(&self) -> Result<EphemeralKeyPair> {
        EphemeralKeyPair::from_secret_hex(&self.my_ephemeral_secret_hex)
            .context("reconstructing our ephemeral keypair from vault")
    }

    /// Decode the peer's persisted static LCT public key.
    pub fn peer_lct_pubkey(&self) -> Result<PublicKey> {
        let bytes: [u8; 32] = hex::decode(&self.peer_lct_pubkey_hex)
            .ok()
            .and_then(|b| b.try_into().ok())
            .ok_or_else(|| anyhow::anyhow!("peer_lct_pubkey_hex is not 32-byte hex"))?;
        PublicKey::from_bytes(&bytes).context("decoding peer static LCT pubkey")
    }
}

/// The inner envelope a `secret` rides inside the pair-channel seal. The hub
/// relays the SEALED body opaquely, so this shape is an interop contract between
/// the two *members* (hestia↔CBP), NOT a hub seam. `kind` lets the receive side
/// route a secret to the §7.8.2 credential_access gate + interactive drain,
/// distinct from ordinary coordination traffic. Bytes are hex (arbitrary
/// binary secrets); `act_id` gives the receiver an id to ACK.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SecretEnvelope {
    pub kind: String, // always "secret"
    pub act_id: Uuid,
    /// The secret bytes, hex-encoded (arbitrary binary; matches the prior
    /// send_secret envelope's `secret_hex` so a receiver's parse is uniform).
    pub secret_hex: String,
}

impl SecretEnvelope {
    pub const KIND: &'static str = "secret";

    pub fn new(secret: &[u8]) -> Self {
        Self {
            kind: Self::KIND.to_string(),
            act_id: Uuid::new_v4(),
            secret_hex: hex::encode(secret),
        }
    }

    /// Serialize to the bytes that get sealed. Kept separate so the caller can
    /// drop the plaintext immediately after enveloping.
    pub fn to_sealed_bytes(&self) -> Result<Vec<u8>> {
        serde_json::to_vec(self).context("serializing SecretEnvelope")
    }

    pub fn from_opened_bytes(bytes: &[u8]) -> Result<Self> {
        serde_json::from_slice(bytes).context("parsing opened SecretEnvelope")
    }

    /// Recover the raw secret bytes. Fail-closed on a wrong `kind` (a non-secret
    /// message must not be treated as one).
    pub fn secret_bytes(&self) -> Result<Vec<u8>> {
        if self.kind != Self::KIND {
            anyhow::bail!("envelope kind is '{}', not 'secret'", self.kind);
        }
        hex::decode(&self.secret_hex).context("decoding secret_hex")
    }
}

/// The set of pairings this member holds, persisted vault-sealed at
/// `presence/pairings` (legacy sidecar `pairings.json`).
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PairingStore {
    pub pairings: HashMap<Uuid, Pairing>,
}

impl PairingStore {
    pub fn load(vault: &crate::vault::Vault) -> Result<Self> {
        crate::vault::load_doc(vault, "presence", "pairings", "pairings.json")
    }

    pub fn save(&self, vault: &mut crate::vault::Vault) -> Result<()> {
        crate::vault::save_doc(vault, "presence", "pairings", "pairings.json", self)
    }

    pub fn get(&self, pair_id: &Uuid) -> Option<&Pairing> {
        self.pairings.get(pair_id)
    }

    pub fn insert(&mut self, p: Pairing) {
        self.pairings.insert(p.pair_id, p);
    }

    /// Wipe a pairing's forward-secret material on revoke/expiry (Sprint F: the
    /// FS guarantee holds only if endpoints destroy their ephemeral secrets).
    pub fn wipe(&mut self, pair_id: &Uuid) -> Option<Pairing> {
        self.pairings.remove(pair_id)
    }
}

/// Given a confirmed pair's detail, return the PEER's ephemeral X25519 public
/// key — the field determined by our role. Fail-closed: an unconfirmed pair (no
/// peer ephemeral yet) is an error, not a silent fallback to a weaker key.
pub fn peer_ephemeral_pub(
    detail: &PairView,
    role: PairingRole,
) -> Result<x25519_dalek::PublicKey> {
    let hex = match role {
        // We initiated → the peer confirmed → read their (counterparty) ephemeral.
        PairingRole::Initiator => detail.counterparty_ephemeral_pub_hex.as_deref(),
        // We confirmed → the peer initiated → read their (initiator) ephemeral.
        PairingRole::Confirmer => detail.initiator_ephemeral_pub_hex.as_deref(),
    };
    let hex = hex.ok_or_else(|| {
        anyhow::anyhow!(
            "pair {} has no peer ephemeral key yet (not confirmed?) — refusing to seal/open",
            detail.id
        )
    })?;
    ephemeral_public_from_hex(hex).context("decoding peer ephemeral pubkey")
}

/// Seal a plaintext to the peer over this confirmed pair (v2, forward-secret).
/// `peer_lct` is the peer's *static* LCT pubkey (from the hub resolver) — the
/// authentication half of the v2 key. Output is base64 for the `pair_message`
/// `body`. **Never** logs the plaintext.
pub fn seal_over_pair(
    pairing: &Pairing,
    detail: &PairView,
    my_lct: &KeyPair,
    peer_lct: &PublicKey,
    plaintext: &[u8],
) -> Result<String> {
    let my_eph = pairing.my_ephemeral()?;
    let peer_eph = peer_ephemeral_pub(detail, pairing.role)?;
    let sealed = seal_fs(my_lct, &my_eph, peer_lct, &peer_eph, pairing.pair_id, plaintext)
        .context("sealing over pair channel (seal_fs)")?;
    Ok(sealed.to_base64())
}

/// Open a `pair_message` body sealed to us over this confirmed pair. Symmetric
/// inverse of [`seal_over_pair`]. Fail-closed on any decode/auth failure.
pub fn open_over_pair(
    pairing: &Pairing,
    detail: &PairView,
    my_lct: &KeyPair,
    peer_lct: &PublicKey,
    body_b64: &str,
) -> Result<Vec<u8>> {
    let my_eph = pairing.my_ephemeral()?;
    let peer_eph = peer_ephemeral_pub(detail, pairing.role)?;
    let sealed = Sealed::from_base64(body_b64).context("decoding pair_message body")?;
    open_fs(my_lct, &my_eph, peer_lct, &peer_eph, pairing.pair_id, &sealed)
        .context("opening pair_message (open_fs)")
}

// ---------------------------------------------------------------------------
// Wire structs — exact field names of the hub's paired-channel REST surface
// (`/v1/hubs/:id/pairs/...`). The contract is the field names; a rename here is
// an interop break, so these are the single source both directions read.
// ---------------------------------------------------------------------------

/// `POST /pairs/request` payload (inside the SignedEnvelope).
#[derive(Serialize)]
pub struct PairRequestPayload {
    pub action: &'static str, // "pair_request"
    pub counterparty_lct_id: Uuid,
    pub purpose: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub initiator_ephemeral_pub_hex: Option<String>,
}

/// `POST /pairs/:id/confirm` payload.
#[derive(Serialize)]
pub struct PairConfirmPayload {
    pub action: &'static str, // "pair_confirm"
    pub pair_id: Uuid,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub counterparty_ephemeral_pub_hex: Option<String>,
}

/// `POST /pairs/:id/messages` payload — `body` is base64 ciphertext (opaque to
/// the hub, which witnesses only its `payload_hash`).
#[derive(Serialize)]
pub struct PairMessagePayload {
    pub action: &'static str, // "pair_message"
    pub pair_id: Uuid,
    pub body: String,
}

/// `PairAccepted` — the request/confirm response we need the `pair_id` from.
#[derive(Deserialize)]
pub struct PairAccepted {
    pub pair_id: Uuid,
}

/// `GET /pairs/:id` detail (subset of the hub's `PairSummary` we consume).
#[derive(Clone, Debug, Deserialize)]
pub struct PairView {
    pub id: Uuid,
    pub initiator: Uuid,
    pub counterparty: Uuid,
    #[serde(default)]
    pub purpose: String,
    #[serde(default)]
    pub effective_status: String,
    #[serde(default)]
    pub initiator_ephemeral_pub_hex: Option<String>,
    #[serde(default)]
    pub counterparty_ephemeral_pub_hex: Option<String>,
}

impl PairView {
    pub fn is_active(&self) -> bool {
        self.effective_status == "active"
    }
}

/// One entry from `GET /pairs/:id/messages`.
#[derive(Clone, Debug, Deserialize)]
pub struct PairMessageView {
    pub seq: u64,
    pub from: Uuid,
    /// base64 ciphertext (the sealed `body` we posted).
    pub payload: String,
}

/// `GET /pairs/:id/messages` response.
#[derive(Deserialize)]
pub struct PairMessagesResponse {
    #[serde(default)]
    pub messages: Vec<PairMessageView>,
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The crux interop proof: two members, each with their own LCT keypair and
    /// a per-pair ephemeral keypair, derive the SAME v2 session key from the
    /// hub-brokered pair detail and round-trip a secret — with NO registry
    /// resolution and NO `sealed_by`. This is the mechanism dp's architecture
    /// selects, exercised end to end minus the HTTP hop.
    #[test]
    fn two_members_round_trip_a_secret_over_a_confirmed_pair() {
        let alice_lct = KeyPair::generate();
        let bob_lct = KeyPair::generate();
        let pair_id = Uuid::new_v4();

        // Each side mints an ephemeral keypair (published in request/confirm).
        let alice_eph = EphemeralKeyPair::generate();
        let bob_eph = EphemeralKeyPair::generate();

        // Persisted per-pair state, as it would live vault-sealed.
        let alice_pairing = Pairing {
            pair_id,
            peer_uuid: Uuid::new_v4(),
            role: PairingRole::Initiator,
            purpose: "secret-transport".into(),
            my_ephemeral_secret_hex: alice_eph.secret_hex(),
            peer_lct_pubkey_hex: hex::encode(bob_lct.verifying_key().to_bytes()),
        };
        let bob_pairing = Pairing {
            pair_id,
            peer_uuid: Uuid::new_v4(),
            role: PairingRole::Confirmer,
            purpose: "secret-transport".into(),
            my_ephemeral_secret_hex: bob_eph.secret_hex(),
            peer_lct_pubkey_hex: hex::encode(alice_lct.verifying_key().to_bytes()),
        };

        // The hub-brokered pair detail: initiator=alice's eph, counterparty=bob's.
        let detail = PairView {
            id: pair_id,
            initiator: alice_pairing.peer_uuid, // uuids irrelevant to the crypto
            counterparty: bob_pairing.peer_uuid,
            purpose: "secret-transport".into(),
            effective_status: "active".into(),
            initiator_ephemeral_pub_hex: Some(alice_eph.public_hex()),
            counterparty_ephemeral_pub_hex: Some(bob_eph.public_hex()),
        };

        let secret = b"kaggle_token=hunter2-do-not-log";

        // Alice seals to Bob using the peer's STATIC LCT pubkey (hub resolver)
        // + the peer's EPHEMERAL pubkey (pair detail).
        let body = seal_over_pair(&alice_pairing, &detail, &alice_lct, &bob_lct.verifying_key(), secret)
            .expect("alice seals");
        // The hub only ever sees this opaque base64 — assert the plaintext isn't in it.
        assert!(!body.contains("hunter2"), "ciphertext must not leak plaintext");

        // Bob opens with HIS state + Alice's static+ephemeral pubkeys.
        let opened = open_over_pair(&bob_pairing, &detail, &bob_lct, &alice_lct.verifying_key(), &body)
            .expect("bob opens");
        assert_eq!(opened, secret, "round-trip must recover the exact secret");
    }

    #[test]
    fn wrong_peer_key_fails_closed() {
        let alice_lct = KeyPair::generate();
        let bob_lct = KeyPair::generate();
        let mallory_lct = KeyPair::generate();
        let pair_id = Uuid::new_v4();
        let alice_eph = EphemeralKeyPair::generate();
        let bob_eph = EphemeralKeyPair::generate();

        let alice_pairing = Pairing {
            pair_id, peer_uuid: Uuid::new_v4(), role: PairingRole::Initiator,
            purpose: "x".into(), my_ephemeral_secret_hex: alice_eph.secret_hex(),
            peer_lct_pubkey_hex: hex::encode(bob_lct.verifying_key().to_bytes()),
        };
        let bob_pairing = Pairing {
            pair_id, peer_uuid: Uuid::new_v4(), role: PairingRole::Confirmer,
            purpose: "x".into(), my_ephemeral_secret_hex: bob_eph.secret_hex(),
            peer_lct_pubkey_hex: hex::encode(alice_lct.verifying_key().to_bytes()),
        };
        let detail = PairView {
            id: pair_id, initiator: Uuid::new_v4(), counterparty: Uuid::new_v4(),
            purpose: "s".into(),
            effective_status: "active".into(),
            initiator_ephemeral_pub_hex: Some(alice_eph.public_hex()),
            counterparty_ephemeral_pub_hex: Some(bob_eph.public_hex()),
        };
        let body = seal_over_pair(&alice_pairing, &detail, &alice_lct, &bob_lct.verifying_key(), b"s")
            .unwrap();
        // Bob tries to open pretending the sender was Mallory (wrong static key) — must fail.
        assert!(
            open_over_pair(&bob_pairing, &detail, &bob_lct, &mallory_lct.verifying_key(), &body).is_err(),
            "opening with the wrong sender static key must fail closed"
        );
    }

    #[test]
    fn secret_envelope_round_trips_through_the_pair_channel() {
        // The full inner-contract path: wrap a secret in a SecretEnvelope, seal
        // it over the pair, open on the other side, recover the exact bytes.
        let alice_lct = KeyPair::generate();
        let bob_lct = KeyPair::generate();
        let pair_id = Uuid::new_v4();
        let alice_eph = EphemeralKeyPair::generate();
        let bob_eph = EphemeralKeyPair::generate();
        let alice = Pairing {
            pair_id, peer_uuid: Uuid::new_v4(), role: PairingRole::Initiator,
            purpose: "s".into(), my_ephemeral_secret_hex: alice_eph.secret_hex(),
            peer_lct_pubkey_hex: hex::encode(bob_lct.verifying_key().to_bytes()),
        };
        let bob = Pairing {
            pair_id, peer_uuid: Uuid::new_v4(), role: PairingRole::Confirmer,
            purpose: "s".into(), my_ephemeral_secret_hex: bob_eph.secret_hex(),
            peer_lct_pubkey_hex: hex::encode(alice_lct.verifying_key().to_bytes()),
        };
        let detail = PairView {
            id: pair_id, initiator: Uuid::new_v4(), counterparty: Uuid::new_v4(),
            purpose: "s".into(),
            effective_status: "active".into(),
            initiator_ephemeral_pub_hex: Some(alice_eph.public_hex()),
            counterparty_ephemeral_pub_hex: Some(bob_eph.public_hex()),
        };

        let secret = b"\x00\x01kaggle-token-BINARY\xff";
        let env = SecretEnvelope::new(secret);
        let act_id = env.act_id;
        let body = seal_over_pair(
            &alice, &detail, &alice_lct, &alice.peer_lct_pubkey().unwrap(),
            &env.to_sealed_bytes().unwrap(),
        ).unwrap();

        let opened = open_over_pair(
            &bob, &detail, &bob_lct, &bob.peer_lct_pubkey().unwrap(), &body,
        ).unwrap();
        let recovered = SecretEnvelope::from_opened_bytes(&opened).unwrap();
        assert_eq!(recovered.kind, SecretEnvelope::KIND);
        assert_eq!(recovered.act_id, act_id, "act_id survives for the ACK");
        assert_eq!(recovered.secret_bytes().unwrap(), secret, "exact binary secret recovered");
    }

    #[test]
    fn secret_envelope_wrong_kind_fails_closed() {
        let mut env = SecretEnvelope::new(b"x");
        env.kind = "coordination".into();
        assert!(env.secret_bytes().is_err(), "a non-secret kind must not yield secret bytes");
    }

    #[test]
    fn unconfirmed_pair_has_no_peer_key() {
        let detail = PairView {
            id: Uuid::new_v4(), initiator: Uuid::new_v4(), counterparty: Uuid::new_v4(),
            purpose: "s".into(),
            effective_status: "proposed".into(),
            initiator_ephemeral_pub_hex: Some(EphemeralKeyPair::generate().public_hex()),
            counterparty_ephemeral_pub_hex: None, // peer hasn't confirmed
        };
        assert!(
            peer_ephemeral_pub(&detail, PairingRole::Initiator).is_err(),
            "no peer ephemeral yet → refuse to seal/open"
        );
    }
}

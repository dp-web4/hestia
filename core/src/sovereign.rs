//! The constellation sovereign as a first-class, vault-persisted LCT.
//!
//! Until now hestia's sovereign was a *placeholder string*
//! (`lct:web4:hestia:sovereign:phase1-placeholder`) — the root that mints role
//! LCTs and anchors the witness chain, yet it had no presence of its own: no
//! key-derived id, no keypair, no `binding_proof`. A sovereign with no LCT is the
//! same contradiction #28 fixed for roles ("the role has presence" needs a durable
//! identity) — one level up: the *society* that issues the roles must itself have
//! presence before it can witness anything.
//!
//! This mints hestia's sovereign as a real [`web4_core::Lct`], **vault-persisted**
//! (id stable across restarts, keypair sealed) exactly like [`crate::role_registry`]
//! does for roles. The id is pubkey-derived ([`web4_core::Lct::lct_id`]), so it is
//! stable even if a later concord decision changes the entity type (see the two
//! flagged canonical questions below) — identity rides the key, not the metadata.
//!
//! **Self-issued §3.2 bootstrap, honestly `Placeholder`-strength.** The sovereign
//! signs its own binding (it is the root — there is no higher authority to issue
//! it), and a *software* sovereign remains `SovereignStrength::Placeholder`: the
//! hub still cannot independently verify the `(instance, role)` binding until the
//! sovereign is hardware-bound (TPM). So this changes NO trust-ordering semantics —
//! it gives the root real presence without upgrading its strength claim.
//!
//! ## Two canonical questions flagged to the concord (NOT decided here)
//! 1. **`EntityType::Society`** — canon §2.3 lists `society` as an entity type, but
//!    `web4_core::EntityType` has no such variant. A constellation sovereign IS a
//!    society; minted here as the closest existing variant (`Organization`),
//!    provisional. Because the id is pubkey-derived, a later switch to `Society`
//!    only re-signs the binding — it does NOT change the sovereign's identity.
//! 2. **`SovereignStrength::Software`** — the enum is `Placeholder | Hardware`. A
//!    vault-sealed software sovereign sits *between* them, but adding a rung
//!    reorders the trust model, so it stays `Placeholder` (the honest, weakest
//!    claim) until the concord rules.

use web4_core::{EntityType, Lct, LctBuilder};

const SOVEREIGN_NAMESPACE: &str = "sovereign";
const SOVEREIGN_DOC: &str = "identity";
const SOVEREIGN_LEGACY_FILE: &str = "sovereign.json";

/// The persisted sovereign: its LCT (durable, pubkey-derived identity) and its
/// sealed keypair secret (hex) — the vault doctrine, same as [`crate::role_registry`]'s
/// `PersistedRole`. The secret lets the sovereign *sign as itself* (witness role
/// issuance, attest members) — without it the sovereign LCT would be hollow.
#[derive(serde::Serialize, serde::Deserialize)]
struct PersistedSovereign {
    /// The human-anchoring string this sovereign was minted for (audit only; the
    /// canonical identity is `lct.lct_id()`).
    anchor: String,
    lct: Lct,
    keypair_secret_hex: String,
}

/// The constellation sovereign's durable identity, loaded/minted from the vault.
pub struct Sovereign {
    /// The sovereign's LCT — its presence. `lct.lct_id()` is the canonical id.
    pub lct: Lct,
    /// The string the daemon still keys the witness chain / member labels on
    /// (`sovereign_lct` on `ServerState`). Kept verbatim so existing derivations
    /// (member labels, chain author) stay byte-stable across this addition.
    pub anchor: String,
}

impl Sovereign {
    /// Load the sovereign identity from the vault, minting + persisting it on first
    /// boot. Stable across restarts (id is pubkey-derived AND the keypair is
    /// sealed). `anchor` is the legacy sovereign string the daemon already uses for
    /// witness-chain authorship and member-label derivation — recorded verbatim so
    /// nothing keyed on it shifts.
    ///
    /// Persistence failure degrades honestly: an ephemeral sovereign for this boot
    /// with a logged warning (the daemon must still start), re-minted next boot —
    /// same posture as `load_or_mint_registry`.
    pub fn load_or_mint(vault: &mut crate::vault::Vault, anchor: &str) -> Self {
        let existing: Option<PersistedSovereign> =
            crate::vault::load_doc::<Option<PersistedSovereign>>(
                vault,
                SOVEREIGN_NAMESPACE,
                SOVEREIGN_DOC,
                SOVEREIGN_LEGACY_FILE,
            )
            .unwrap_or(None);

        if let Some(p) = existing {
            // Reload the durable identity. (The keypair secret stays sealed in the
            // vault; it is re-materialized only when the sovereign needs to sign.)
            return Sovereign { lct: p.lct, anchor: p.anchor };
        }

        // First boot: mint the sovereign as a self-issued §3.2 bootstrap. It is the
        // root, so `created_by` is None and it signs its OWN binding.
        // `EntityType::Organization` is the provisional society mapping (canonical
        // question 1). Strength stays Placeholder (a software sovereign is not
        // hardware-verifiable).
        let (mut lct, keypair) = LctBuilder::new(EntityType::Organization).build();
        lct.sign_binding(&keypair);

        let persisted = PersistedSovereign {
            anchor: anchor.to_string(),
            lct: lct.clone(),
            keypair_secret_hex: hex::encode(keypair.secret_key_bytes()),
        };
        if let Err(e) = crate::vault::save_doc(
            vault,
            SOVEREIGN_NAMESPACE,
            SOVEREIGN_DOC,
            SOVEREIGN_LEGACY_FILE,
            &persisted,
        ) {
            eprintln!(
                "[sovereign] WARNING: persisting sovereign identity failed ({e}) — \
                 ephemeral sovereign this boot; re-mints next boot"
            );
        }
        Sovereign { lct, anchor: anchor.to_string() }
    }

    /// The sovereign's canonical, key-derived LCT id (`lct:web4:mb32:…`).
    pub fn lct_id(&self) -> String {
        self.lct.lct_id()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fresh_vault() -> (tempfile::TempDir, std::path::PathBuf) {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("v.enc");
        (dir, path)
    }

    #[test]
    fn sovereign_identity_is_stable_across_vault_reopens() {
        // The society that mints the roles must itself have durable presence — its
        // LCT id must survive a restart, exactly like the roles it issues (#28).
        let (_dir, path) = fresh_vault();
        let mut v = crate::vault::Vault::init(path.clone(), "p".into()).unwrap();
        let s1 = Sovereign::load_or_mint(&mut v, "lct:web4:hestia:sovereign:phase1-placeholder");
        let id1 = s1.lct_id();
        drop(v);
        // reopen = the restart
        let mut v2 = crate::vault::Vault::open(path, "p".into()).unwrap();
        let s2 = Sovereign::load_or_mint(&mut v2, "lct:web4:hestia:sovereign:phase1-placeholder");
        assert_eq!(id1, s2.lct_id(), "sovereign LCT id must be stable across restarts");
        assert!(id1.starts_with("lct:web4:mb32:b"), "canonical key-derived id");
    }

    #[test]
    fn sovereign_binding_is_self_signed_and_verifies() {
        // Self-issued §3.2 bootstrap: the root signs its own binding, verifiable
        // from the document alone. This is what lets the sovereign later witness
        // role issuance (a signer must first be able to answer for itself).
        let (_dir, path) = fresh_vault();
        let mut v = crate::vault::Vault::init(path, "p".into()).unwrap();
        let s = Sovereign::load_or_mint(&mut v, "anchor");
        assert!(s.lct.verify_binding(), "sovereign binding must self-verify");
        assert_eq!(s.lct.entity_type, EntityType::Organization, "provisional society mapping");
        assert!(s.lct.created_by.is_none(), "the root has no issuer");
    }

    #[test]
    fn anchor_is_recorded_verbatim_for_downstream_derivations() {
        // Member labels + witness-chain authorship still key on the anchor STRING;
        // it must round-trip verbatim so nothing keyed on it shifts.
        let (_dir, path) = fresh_vault();
        let mut v = crate::vault::Vault::init(path, "p".into()).unwrap();
        let anchor = "lct:web4:hestia:sovereign:phase1-placeholder";
        let s = Sovereign::load_or_mint(&mut v, anchor);
        assert_eq!(s.anchor, anchor);
    }
}

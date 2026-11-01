//! Custodial member LCTs — the third registry consumer (after the sovereign and
//! the constellation roles).
//!
//! A fleet *member* (`claude-code`, a mesh watcher, a timer) has been a mere
//! **label** all along: `member_lct(plugin_id)` = a hashed string, no keypair, no
//! presence. This mints each member a real [`web4_core::Lct`] — an `AiSoftware`
//! entity, custodial (hestia holds the sealed keypair; the member never sees it,
//! the S3 delegated posture from the Kimi concord), vault-persisted and stable
//! across restarts exactly like [`crate::sovereign`] and [`crate::role_registry`].
//!
//! **The label is not thrown away — it is carried as a verifiable legacy alias.**
//! The member LCT records a [`web4_core::LegacyAlias`] whose
//! [`web4_core::LegacyDerivation::HestiaMember`] re-derives the old
//! `lct:web4:member:<hex>` label byte-for-byte (the registry ingest checks this,
//! it does not trust it — HUB's §2 check 4). So (instance, role) trust grains
//! keyed on the label stay continuous: the same member, now with presence, no
//! re-key (the third-consumer migration ruling, 2026-07-10).
//!
//! **Minted on first observation, never per-connect.** A member that connects is
//! a real member; its LCT is minted once, then it is a cheap in-memory lookup.
//! This honors the connect-path guidance (no per-connect chain/vault side effects)
//! while still giving every real member durable presence. Fail-OPEN: a mint that
//! can't persist logs and retries next sighting — a member without an LCT yet is
//! simply not-yet-publishable, never a refused connect (unlike the fail-CLOSED
//! synthetic exclusion, which is a safety gate).

use std::collections::{HashMap, HashSet};
use web4_core::{EntityType, Lct, LegacyAlias, LegacyDerivation, MrhEdge};

const MEMBERS_NAMESPACE: &str = "members";
const MEMBERS_DOC: &str = "registry";
const MEMBERS_LEGACY_FILE: &str = "members.json";

/// One persisted member: `plugin_id` (the durable member identity the fleet keys
/// on), its custodial LCT, and the sealed keypair secret (hex) — the vault
/// doctrine, same as `PersistedRole`. The secret lets hestia sign AS the member
/// (custodial delegation), and re-sign its binding after a schema change.
#[derive(serde::Serialize, serde::Deserialize)]
struct PersistedMember {
    plugin_id: String,
    lct: Lct,
    keypair_secret_hex: String,
    /// A FILLER, not a member: the durable custodial LCT under which the plane signs a
    /// role-bound reasoner it invokes for one act (the lean path, 2026-09-03 — keyed per
    /// (backend, resolved model), minted once, never per act). Same enrollment class,
    /// same custody, same vault doctrine as a member; what differs is what it may become.
    /// A filler is never a witness (`vouch_witnessing_key` refuses it) and never a
    /// connecting member (`ensure_member` will not return it). Defaults false so every
    /// row written before this field existed reads as a member, which is what it was.
    #[serde(default)]
    filler: bool,
}

/// In-memory member registry: `plugin_id → LCT`, rebuilt from the vault each boot.
#[derive(Default)]
pub struct MemberRegistry {
    members: HashMap<String, Lct>,
    /// The subset of `members` minted as fillers. Kept beside the map rather than on the
    /// LCT because the LCT is what gets PUBLISHED, and the registry ingest is not the
    /// place to teach a new field; the refusals that need this fact all run here.
    fillers: HashSet<String>,
}

/// Which namespace proved a member reference.
///
/// A caller must never infer "canonical" from a string shape after resolution:
/// the resolver carries the evidence that actually matched. This is the FR1
/// seam from `PRD_LCT_IDENTITY_CONVERGENCE` and the identity half of F3's
/// machine-level receive router (#1202/#1210).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MemberReferenceKind {
    PluginId,
    CanonicalLct,
    VerifiedLegacyAlias,
}

/// One resolved, non-filler member presence.
#[derive(Debug)]
pub struct MemberResolution<'a> {
    pub plugin_id: &'a str,
    pub lct: &'a Lct,
    pub matched_by: MemberReferenceKind,
}

/// Is a resolved address actually hosted below the named parent on this box?
///
/// `KnownButNotChild` is deliberately distinct from `Unknown`: a receiver
/// can honestly say "that entity is known, but not local to this parent" instead
/// of silently falling through to a similarly named seat.
#[derive(Debug)]
pub enum LocalChildResolution<'a> {
    Local(MemberResolution<'a>),
    KnownButNotChild(MemberResolution<'a>),
    Unknown,
}

impl MemberRegistry {
    pub fn get(&self, plugin_id: &str) -> Option<&Lct> {
        self.members.get(plugin_id)
    }
    /// Is this id a filler — a custodial LCT the plane invokes, never a member that
    /// connects, witnesses, or confers? The witness-onboard path asks this BEFORE the
    /// vault is opened, so the refusal names itself instead of reading as a missing mint.
    pub fn is_filler(&self, plugin_id: &str) -> bool {
        self.fillers.contains(plugin_id)
    }
    pub fn len(&self) -> usize {
        self.members.len()
    }
    pub fn is_empty(&self) -> bool {
        self.members.is_empty()
    }

    /// Resolve exactly one MEMBER reference through the canonical three namespaces:
    ///
    /// - ordinary strings are plugin/member ids;
    /// - `lct:web4:mb32:...` is canonical presence;
    /// - `lct:web4:member:...` is accepted only when the stored legacy alias verifies.
    ///
    /// Fillers are excluded: they are invoked role occupants, not independently
    /// addressable members. Unknown namespace-looking `lct:web4:...` strings do
    /// not fall back to plugin ids — that would let a typo in an identity namespace
    /// silently become a different kind of identifier.
    ///
    /// Duplicate canonical ids or verified aliases fail closed instead of picking
    /// whichever HashMap entry happens to iterate first. #840 owns copied-presence
    /// adjudication; this resolver's job is to refuse ambiguity, not hide it.
    pub fn resolve_reference(
        &self,
        reference: &str,
    ) -> anyhow::Result<Option<MemberResolution<'_>>> {
        let reference = reference.trim();
        if reference.is_empty() {
            return Ok(None);
        }

        if reference.starts_with("lct:web4:mb32:") {
            let mut found: Option<MemberResolution<'_>> = None;
            for (plugin_id, lct) in &self.members {
                if self.fillers.contains(plugin_id) || lct.lct_id() != reference {
                    continue;
                }
                anyhow::ensure!(
                    found.is_none(),
                    "canonical member LCT '{reference}' resolves to more than one member"
                );
                found = Some(MemberResolution {
                    plugin_id: plugin_id.as_str(),
                    lct,
                    matched_by: MemberReferenceKind::CanonicalLct,
                });
            }
            return Ok(found);
        }

        if reference.starts_with("lct:web4:member:") {
            let mut found: Option<MemberResolution<'_>> = None;
            for (plugin_id, lct) in &self.members {
                if self.fillers.contains(plugin_id) {
                    continue;
                }
                let Some(alias) = lct.legacy_alias.as_ref() else {
                    continue;
                };
                if alias.legacy_id != reference {
                    continue;
                }
                anyhow::ensure!(
                    alias.verify(),
                    "legacy member alias '{reference}' is present but fails derivation verification"
                );
                anyhow::ensure!(
                    found.is_none(),
                    "verified legacy member alias '{reference}' resolves to more than one member"
                );
                found = Some(MemberResolution {
                    plugin_id: plugin_id.as_str(),
                    lct,
                    matched_by: MemberReferenceKind::VerifiedLegacyAlias,
                });
            }
            return Ok(found);
        }

        // Identity-looking input is never reinterpreted as a plugin id.
        if reference.starts_with("lct:web4:") {
            return Ok(None);
        }

        let Some((plugin_id, lct)) = self.members.get_key_value(reference) else {
            return Ok(None);
        };
        if self.fillers.contains(plugin_id) {
            return Ok(None);
        }
        Ok(Some(MemberResolution {
            plugin_id: plugin_id.as_str(),
            lct,
            matched_by: MemberReferenceKind::PluginId,
        }))
    }

    /// Enumerate non-filler members whose LCT explicitly carries the given
    /// parent binding. This is a projection of witnessed identity state, not a
    /// naming convention: `sprout-being` is not local merely because its name
    /// starts with `sprout-`.
    pub fn children_of(&self, parent_lct_id: &str) -> Vec<(&str, &Lct)> {
        let mut out: Vec<(&str, &Lct)> = self
            .members
            .iter()
            .filter(|(plugin_id, lct)| {
                !self.fillers.contains(*plugin_id)
                    && lct.mrh.bound.iter().any(|edge| {
                        edge.edge_type == "parent" && edge.lct_id == parent_lct_id
                    })
            })
            .map(|(plugin_id, lct)| (plugin_id.as_str(), lct))
            .collect();
        out.sort_by(|a, b| a.0.cmp(b.0));
        out
    }

    /// Resolve an address and classify whether it belongs to this parent.
    ///
    /// This is intentionally only the DEMUX primitive for F3. It does not wake
    /// a session, infer work assignment, ACK a hub mailbox item, or grant any
    /// authority. Address chooses the inbox; local law decides what happens next.
    pub fn resolve_child_of(
        &self,
        parent_lct_id: &str,
        reference: &str,
    ) -> anyhow::Result<LocalChildResolution<'_>> {
        let Some(member) = self.resolve_reference(reference)? else {
            return Ok(LocalChildResolution::Unknown);
        };
        let local = member.lct.mrh.bound.iter().any(|edge| {
            edge.edge_type == "parent" && edge.lct_id == parent_lct_id
        });
        if local {
            Ok(LocalChildResolution::Local(member))
        } else {
            Ok(LocalChildResolution::KnownButNotChild(member))
        }
    }

    /// Every (plugin_id, LCT) pair, for the publish set. Sorted by plugin_id so
    /// dry-runs and publishes are reproducible.
    pub fn iter_sorted(&self) -> Vec<(&String, &Lct)> {
        let mut v: Vec<_> = self.members.iter().collect();
        v.sort_by(|a, b| a.0.cmp(b.0));
        v
    }
}

/// Load the persisted member registry from the vault. Additive: never mints here
/// (minting is [`ensure_member`], driven by real connects) — a fresh vault yields
/// an empty registry, populated as members appear.
pub fn load_members(vault: &crate::vault::Vault) -> MemberRegistry {
    let persisted: Vec<PersistedMember> =
        crate::vault::load_doc(vault, MEMBERS_NAMESPACE, MEMBERS_DOC, MEMBERS_LEGACY_FILE)
            .unwrap_or_default();
    let mut members = HashMap::new();
    let mut fillers = HashSet::new();
    for p in persisted {
        if p.filler {
            fillers.insert(p.plugin_id.clone());
        }
        members.insert(p.plugin_id, p.lct);
    }
    MemberRegistry { members, fillers }
}

/// Attach a citizenship reference to a member's LCT and re-persist, so the member
/// now *carries* proof-of-citizenship (a tamper-evident pointer to the ledger
/// record — the authoritative home stays the ledger). Located by `plugin_id`, not
/// by lct_id, since that's the durable member key. Idempotent: a reference already
/// present (same society + entry) is not duplicated. Returns `true` if the member
/// exists and the reference is now attached (added or already present).
///
/// The subject's `citizenships` is plural (one per society), so this appends —
/// it never overwrites another society's citizenship (the plurality reshape).
pub fn attach_citizenship(
    vault: &mut crate::vault::Vault,
    registry: &mut MemberRegistry,
    plugin_id: &str,
    citizenship: web4_core::BirthCertificateRef,
) -> bool {
    let Some(lct) = registry.members.get_mut(plugin_id) else {
        return false;
    };
    if !lct.citizenships.contains(&citizenship) {
        lct.citizenships.push(citizenship);
    }
    // Re-persist the whole roster (the member's keypair secret is reloaded from
    // the existing doc so the persisted record stays complete).
    let mut persisted: Vec<PersistedMember> =
        crate::vault::load_doc(vault, MEMBERS_NAMESPACE, MEMBERS_DOC, MEMBERS_LEGACY_FILE)
            .unwrap_or_default();
    if let Some(p) = persisted.iter_mut().find(|p| p.plugin_id == plugin_id) {
        p.lct = lct.clone();
        if let Err(e) = crate::vault::save_doc(
            vault,
            MEMBERS_NAMESPACE,
            MEMBERS_DOC,
            MEMBERS_LEGACY_FILE,
            &persisted,
        ) {
            eprintln!("[members] WARNING: persisting citizenship for '{plugin_id}' failed ({e})");
        }
    }
    true
}

/// Vouch a member's **operational witnessing key** on its LCT (concord ruling (B),
/// 2026-07-18): the member's custodial BINDING key (held sealed here) signs a
/// `#540 OperationalKey(purpose="witnessing")` over the given operational pubkey,
/// so a verifier resolves the witness's signing key from the registry offline —
/// one uniform resolver path for machines and agents alike, no hub roster.
///
/// A one-time, vault-attended act (the sealed binding key signs once); thereafter
/// the member witnesses autonomously with the operational key. Located by
/// `plugin_id`; re-persists. Returns `false` if the member is unknown or its
/// sealed binding secret can't be recovered (fail-closed — never a forged vouch).
pub fn vouch_witnessing_key(
    vault: &mut crate::vault::Vault,
    registry: &mut MemberRegistry,
    plugin_id: &str,
    operational_pubkey: web4_core::PublicKey,
) -> bool {
    let mut persisted: Vec<PersistedMember> =
        crate::vault::load_doc(vault, MEMBERS_NAMESPACE, MEMBERS_DOC, MEMBERS_LEGACY_FILE)
            .unwrap_or_default();
    let Some(p) = persisted.iter_mut().find(|p| p.plugin_id == plugin_id) else {
        return false;
    };
    // A FILLER IS NEVER A WITNESS. Three minted fillers conferring the plane's own being
    // is the lean path's refusal one altitude up (cbp, 2026-09-03): a filler's key is the
    // plane's key, so its attestation is the plane witnessing itself under another name —
    // the `LocalCli` "one channel wearing two names" defect at the membership seam. Before
    // this branch, witness onboard could not tell a filler from a member (legion's one
    // hazard into the membership work), because nothing recorded the difference.
    if p.filler {
        eprintln!(
            "[members] REFUSED: '{plugin_id}' is a filler (an invoked role occupant signed \
             custodially by this plane), and a filler is never a witness — vouch refused"
        );
        return false;
    }
    // Recover the custodial binding keypair (sealed in the vault) to sign the vouch.
    let Some(binding_kp) = hex::decode(&p.keypair_secret_hex)
        .ok()
        .and_then(|b| <[u8; 32]>::try_from(b).ok())
        .map(|bytes| web4_core::crypto::KeyPair::from_secret_bytes(&bytes))
    else {
        eprintln!(
            "[members] WARNING: cannot recover binding key for '{plugin_id}' — vouch refused"
        );
        return false;
    };
    if binding_kp.verifying_key() != p.lct.public_key {
        eprintln!(
            "[members] WARNING: sealed key for '{plugin_id}' does not bind its LCT — vouch refused"
        );
        return false;
    }
    p.lct
        .authorize_operational_key(web4_core::WITNESS_PURPOSE, operational_pubkey, &binding_kp);
    if let Some(lct) = registry.members.get_mut(plugin_id) {
        *lct = p.lct.clone();
    }
    if let Err(e) = crate::vault::save_doc(
        vault,
        MEMBERS_NAMESPACE,
        MEMBERS_DOC,
        MEMBERS_LEGACY_FILE,
        &persisted,
    ) {
        eprintln!(
            "[members] WARNING: persisting witnessing-key vouch for '{plugin_id}' failed ({e})"
        );
        return false;
    }
    true
}

/// Build the verifiable legacy alias tying a member LCT to its pre-LCT label.
/// `sovereign_anchor` MUST be the exact string `member_lct` hashes over, so the
/// alias re-derives to the label the trust grains already use.
fn member_legacy_alias(plugin_id: &str, sovereign_anchor: &str) -> LegacyAlias {
    let derivation = LegacyDerivation::HestiaMember {
        plugin_id: plugin_id.to_string(),
        sovereign: sovereign_anchor.to_string(),
    };
    LegacyAlias {
        legacy_id: derivation.derive(),
        derivation,
    }
}

/// Ensure `plugin_id` has a custodial member LCT, minting + persisting on first
/// sight. Idempotent: an in-memory hit returns immediately (the hot path). Returns
/// the member's canonical `lct_id` when present/minted, `None` when it should not
/// have one (empty/synthetic — the same fail-closed domain as `member_lct`).
///
/// `sovereign_lct` is the LCT-anchor string (for the legacy alias + `created_by`
/// lineage); `sovereign_lct_id` is the sovereign's canonical id (the `mrh.bound`
/// parent target). Persist failure is logged and swallowed — the member simply
/// isn't published yet (fail-open; presence is not a safety gate).
pub fn ensure_member(
    vault: &mut crate::vault::Vault,
    registry: &mut MemberRegistry,
    plugin_id: &str,
    is_synthetic: bool,
    sovereign_lct_id: &str,
    sovereign_anchor: &str,
) -> Option<String> {
    let id = plugin_id.trim();
    if id.is_empty() || is_synthetic {
        return None; // mirror member_lct's fail-closed domain exactly
    }
    mint_once(
        vault,
        registry,
        id,
        false,
        sovereign_lct_id,
        sovereign_anchor,
    )
}

/// Ensure a FILLER LCT exists for `filler_id` — the durable custodial identity of a
/// role-bound reasoner the plane invokes (the lean path). Same mint as a member, same
/// vault, same enrollment class; marked so the refusals in this module can tell it apart.
///
/// This is the SEAM, not the policy: the caller owns the key (`(backend, resolved model)`,
/// with the model as the backend reports it resolved, and NO mint when the backend cannot
/// report one — cbp's pin, 2026-09-03). What this guarantees is only that whatever id is
/// minted here can never be vouched as a witness or returned as a connecting member.
/// Minted once, idempotent, never per act. Refuses (None) when the id already names a
/// member: an id cannot be re-labelled into a filler by asking.
pub fn ensure_filler(
    vault: &mut crate::vault::Vault,
    registry: &mut MemberRegistry,
    filler_id: &str,
    sovereign_lct_id: &str,
    sovereign_anchor: &str,
) -> Option<String> {
    let id = filler_id.trim();
    if id.is_empty() {
        return None;
    }
    mint_once(
        vault,
        registry,
        id,
        true,
        sovereign_lct_id,
        sovereign_anchor,
    )
}

/// The one mint. `filler` is recorded on the persisted row and in the registry's filler
/// set; a hit under the OTHER kind returns `None` rather than the existing LCT, because
/// an id that is a member must not answer as a filler and a filler must not answer as a
/// member — the whole reason the field exists is that the two were indistinguishable.
fn mint_once(
    vault: &mut crate::vault::Vault,
    registry: &mut MemberRegistry,
    id: &str,
    filler: bool,
    sovereign_lct_id: &str,
    sovereign_anchor: &str,
) -> Option<String> {
    if let Some(lct) = registry.members.get(id) {
        if registry.fillers.contains(id) != filler {
            eprintln!(
                "[members] REFUSED: '{id}' is already minted as a {} and was asked for as a {}",
                if filler { "member" } else { "filler" },
                if filler { "filler" } else { "member" },
            );
            return None;
        }
        return Some(lct.lct_id()); // hot path: already present
    }

    // First sight: mint an AiSoftware LCT with a custodial keypair.
    let (mut lct, keypair) = Lct::new(EntityType::AiSoftware, None);
    lct.sign_binding(&keypair); // self-issued §3.2 bootstrap, custodial key proves the binding
    lct.legacy_alias = Some(member_legacy_alias(id, sovereign_anchor));
    if !sovereign_lct_id.is_empty() {
        lct.mrh.bound = vec![MrhEdge {
            lct_id: sovereign_lct_id.to_string(),
            edge_type: "parent".to_string(),
            ts: lct.created_at,
        }];
    }

    // Persist: reload the doc, append, save (append-only; other members untouched).
    let mut persisted: Vec<PersistedMember> =
        crate::vault::load_doc(vault, MEMBERS_NAMESPACE, MEMBERS_DOC, MEMBERS_LEGACY_FILE)
            .unwrap_or_default();
    persisted.push(PersistedMember {
        plugin_id: id.to_string(),
        lct: lct.clone(),
        keypair_secret_hex: hex::encode(keypair.secret_key_bytes()),
        filler,
    });
    if let Err(e) = crate::vault::save_doc(
        vault,
        MEMBERS_NAMESPACE,
        MEMBERS_DOC,
        MEMBERS_LEGACY_FILE,
        &persisted,
    ) {
        eprintln!(
            "[members] WARNING: persisting member LCT for '{id}' failed ({e}) — \
             not published this boot; re-mints on next sighting"
        );
        return None; // not durable → don't advertise presence we can't reproduce
    }
    let lct_id = lct.lct_id();
    registry.members.insert(id.to_string(), lct);
    if filler {
        registry.fillers.insert(id.to_string());
    }
    Some(lct_id)
}

// Moved from server/http.rs (#1110) so the CLI's `delegate grant` door can name the nearest
// recorded id exactly as the HTTP doors do -- one helper, so the two refusals cannot drift.
/// Recorded member ids a mistyped `asked` most plausibly meant: equal ignoring case and
/// punctuation first, else within two edits. At most three, best first. Pure, so its refusals
/// can be tested without a daemon. It only ever NAMES candidates in an error message -- it
/// never redirects a grant, because guessing the target of an authority change is the
/// operator's job, not a string distance's.
pub fn nearest_member_ids(asked: &str, known: &[String]) -> Vec<String> {
    let fold = |s: &str| -> Vec<char> {
        s.chars().filter(|c| c.is_ascii_alphanumeric()).map(|c| c.to_ascii_lowercase()).collect()
    };
    let a = fold(asked);
    if a.is_empty() {
        return Vec::new();
    }
    let dist = |x: &[char], y: &[char]| -> usize {
        let mut prev: Vec<usize> = (0..=y.len()).collect();
        for (i, cx) in x.iter().enumerate() {
            let mut cur = vec![i + 1];
            for (j, cy) in y.iter().enumerate() {
                let sub = prev[j] + usize::from(cx != cy);
                cur.push(sub.min(prev[j + 1] + 1).min(cur[j] + 1));
            }
            prev = cur;
        }
        prev[y.len()]
    };
    let mut scored: Vec<(usize, &String)> = known
        .iter()
        .map(|k| (dist(&a, &fold(k)), k))
        .filter(|(d, _)| *d <= 2)
        .collect();
    scored.sort_by(|x, y| x.0.cmp(&y.0).then_with(|| x.1.cmp(y.1)));
    scored.into_iter().take(3).map(|(_, k)| k.clone()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fresh_vault() -> (tempfile::TempDir, crate::vault::Vault) {
        let dir = tempfile::TempDir::new().unwrap();
        let vault = crate::vault::Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        (dir, vault)
    }

    #[test]
    fn ensure_member_mints_persists_and_is_idempotent() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        let a1 =
            ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        let a2 =
            ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        assert_eq!(a1, a2, "second call returns the same LCT (no re-mint)");
        assert_eq!(reg.len(), 1);
        assert!(a1.starts_with("lct:web4:mb32:b"));
        // distinct members get distinct LCTs
        let b = ensure_member(&mut vault, &mut reg, "alice", false, "sid", "anchor").unwrap();
        assert_ne!(a1, b);
        assert_eq!(reg.len(), 2);
    }

    #[test]
    fn a_filler_is_minted_once_and_never_answers_as_a_member() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        let f1 = ensure_filler(
            &mut vault,
            &mut reg,
            "ollama:qwen3:2b@sha256:8f1c",
            "sid",
            "anchor",
        )
        .expect("first mint");
        let f2 = ensure_filler(
            &mut vault,
            &mut reg,
            "ollama:qwen3:2b@sha256:8f1c",
            "sid",
            "anchor",
        )
        .expect("idempotent");
        assert_eq!(
            f1, f2,
            "one LCT per (backend, resolved model), never per act"
        );
        assert!(reg.is_filler("ollama:qwen3:2b@sha256:8f1c"));
        // The same id asked for as a MEMBER is refused, not returned: a filler that could
        // answer a connect as a member would have presence it never earned.
        assert!(
            ensure_member(
                &mut vault,
                &mut reg,
                "ollama:qwen3:2b@sha256:8f1c",
                false,
                "sid",
                "anchor"
            )
            .is_none()
        );
        // And a member cannot be re-labelled into a filler by asking.
        ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        assert!(ensure_filler(&mut vault, &mut reg, "claude-code", "sid", "anchor").is_none());
        assert!(!reg.is_filler("claude-code"));
        // The mark survives the vault round trip, which is where the onboard path reads it.
        let reloaded = load_members(&vault);
        assert!(reloaded.is_filler("ollama:qwen3:2b@sha256:8f1c"));
        assert!(!reloaded.is_filler("claude-code"));
        assert_eq!(reloaded.len(), 2);
    }

    #[test]
    fn a_filler_cannot_be_vouched_as_a_witness() {
        // The one reach of the lean path into the membership work. Before the `filler`
        // mark, this call succeeded for any minted id — witness onboard could not tell a
        // filler from a member, so three fillers could confer the plane's own being.
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        ensure_filler(
            &mut vault,
            &mut reg,
            "ollama:qwen3:2b@sha256:8f1c",
            "sid",
            "anchor",
        )
        .unwrap();
        ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        let op = web4_core::crypto::KeyPair::generate();
        assert!(
            !vouch_witnessing_key(
                &mut vault,
                &mut reg,
                "ollama:qwen3:2b@sha256:8f1c",
                op.verifying_key()
            ),
            "a filler is never a witness"
        );
        assert_eq!(
            reg.get("ollama:qwen3:2b@sha256:8f1c")
                .unwrap()
                .operational_key_for(web4_core::WITNESS_PURPOSE),
            None,
            "and the refusal left no vouch behind, in memory"
        );
        assert_eq!(
            load_members(&vault)
                .get("ollama:qwen3:2b@sha256:8f1c")
                .unwrap()
                .operational_key_for(web4_core::WITNESS_PURPOSE),
            None,
            "or in the vault"
        );
        // The control: the same call for a member still vouches.
        assert!(vouch_witnessing_key(
            &mut vault,
            &mut reg,
            "claude-code",
            op.verifying_key()
        ));
        assert_eq!(
            reg.get("claude-code")
                .unwrap()
                .operational_key_for(web4_core::WITNESS_PURPOSE),
            Some(op.verifying_key())
        );
    }

    #[test]
    fn member_lct_carries_a_verifiable_alias_to_its_label() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        let lct = reg.get("claude-code").unwrap();
        let alias = lct
            .legacy_alias
            .as_ref()
            .expect("member carries a legacy alias");
        assert!(
            alias.verify(),
            "the alias re-derives (registry ingest check 4)"
        );
        // and it targets the SAME label the trust grains key on
        let expected = LegacyDerivation::HestiaMember {
            plugin_id: "claude-code".into(),
            sovereign: "anchor".into(),
        }
        .derive();
        assert_eq!(alias.legacy_id, expected);
        // it's a proven, sovereign-bound, AiSoftware entity
        assert!(lct.verify_binding());
        assert_eq!(lct.entity_type, EntityType::AiSoftware);
        assert_eq!(lct.mrh.bound[0].lct_id, "sid");
    }

    #[test]
    fn synthetic_and_empty_get_no_lct() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        assert!(ensure_member(&mut vault, &mut reg, "runner", true, "sid", "anchor").is_none());
        assert!(ensure_member(&mut vault, &mut reg, "   ", false, "sid", "anchor").is_none());
        assert_eq!(reg.len(), 0);
    }

    #[test]
    fn attach_citizenship_makes_the_member_carry_the_reference_and_persists() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        let cref = web4_core::BirthCertificateRef {
            issuing_society: "lct:web4:society:hestia".into(),
            entry_id: "42".into(),
            entry_hash: "deadbeef".into(),
        };
        assert!(attach_citizenship(
            &mut vault,
            &mut reg,
            "claude-code",
            cref.clone()
        ));
        assert_eq!(
            reg.get("claude-code").unwrap().citizenships,
            vec![cref.clone()]
        );
        // idempotent: attaching the same ref again does not duplicate
        attach_citizenship(&mut vault, &mut reg, "claude-code", cref.clone());
        assert_eq!(reg.get("claude-code").unwrap().citizenships.len(), 1);
        // a SECOND society's citizenship appends (plurality), never overwrites
        let cref2 = web4_core::BirthCertificateRef {
            issuing_society: "lct:web4:society:hub".into(),
            entry_id: "7".into(),
            entry_hash: "cafe".into(),
        };
        attach_citizenship(&mut vault, &mut reg, "claude-code", cref2.clone());
        assert_eq!(reg.get("claude-code").unwrap().citizenships.len(), 2);
        // persisted: a reload sees both citizenships
        let reloaded = load_members(&vault);
        assert_eq!(reloaded.get("claude-code").unwrap().citizenships.len(), 2);
        // an unknown member → false, no panic
        assert!(!attach_citizenship(&mut vault, &mut reg, "ghost", cref));
    }

    #[test]
    fn vouch_witnessing_key_publishes_the_resolvable_operational_key() {
        // Ruling (B): the custodial binding key vouches the operational witnessing
        // key, so a verifier resolves it from the LCT alone (uniform #540 path).
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        ensure_member(
            &mut vault,
            &mut reg,
            "legion-witness",
            false,
            "sid",
            "anchor",
        )
        .unwrap();
        let operational = web4_core::crypto::KeyPair::generate(); // the channel key
        assert!(vouch_witnessing_key(
            &mut vault,
            &mut reg,
            "legion-witness",
            operational.verifying_key()
        ));
        // resolvable from the member LCT, no roster
        let lct = reg.get("legion-witness").unwrap();
        assert_eq!(
            lct.operational_key_for(web4_core::WITNESS_PURPOSE),
            Some(operational.verifying_key())
        );
        // persisted: a reload still resolves it
        let reloaded = load_members(&vault);
        assert_eq!(
            reloaded
                .get("legion-witness")
                .unwrap()
                .operational_key_for(web4_core::WITNESS_PURPOSE),
            Some(operational.verifying_key())
        );
        // unknown member → false, no panic
        assert!(!vouch_witnessing_key(
            &mut vault,
            &mut reg,
            "ghost",
            operational.verifying_key()
        ));
    }

    #[test]
    fn canonical_resolver_accepts_plugin_canonical_and_verified_legacy_alias() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        ensure_member(&mut vault, &mut reg, "sprout-being", false, "parent-a", "anchor")
            .unwrap();

        let canonical = reg.get("sprout-being").unwrap().lct_id();
        let legacy = reg
            .get("sprout-being")
            .unwrap()
            .legacy_alias
            .as_ref()
            .unwrap()
            .legacy_id
            .clone();

        for (reference, expected_kind) in [
            ("sprout-being".to_string(), MemberReferenceKind::PluginId),
            (canonical.clone(), MemberReferenceKind::CanonicalLct),
            (legacy.clone(), MemberReferenceKind::VerifiedLegacyAlias),
        ] {
            let resolved = reg
                .resolve_reference(&reference)
                .unwrap()
                .expect("known member resolves");
            assert_eq!(resolved.plugin_id, "sprout-being");
            assert_eq!(resolved.lct.lct_id(), canonical);
            assert_eq!(resolved.matched_by, expected_kind);
        }

        // A syntactically identity-like typo is absence, never a plugin-id fallback.
        assert!(reg
            .resolve_reference("lct:web4:other:sprout-being")
            .unwrap()
            .is_none());
    }

    #[test]
    fn legacy_resolution_requires_a_verified_alias_and_never_fabricates_presence() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        ensure_member(&mut vault, &mut reg, "sprout-being", false, "parent-a", "anchor")
            .unwrap();

        // A correctly-derived alias for a member that is NOT in the registry is still
        // absence. The derivation proves a label, not presence.
        let absent = member_legacy_alias("ghost-being", "anchor").legacy_id;
        assert!(reg.resolve_reference(&absent).unwrap().is_none());

        // If stored continuity evidence itself is corrupt, fail closed and name it.
        let forged = "lct:web4:member:forged".to_string();
        reg.members
            .get_mut("sprout-being")
            .unwrap()
            .legacy_alias
            .as_mut()
            .unwrap()
            .legacy_id = forged.clone();
        let err = reg.resolve_reference(&forged).unwrap_err().to_string();
        assert!(err.contains("fails derivation verification"), "{err}");
    }

    #[test]
    fn local_child_projection_uses_parent_binding_not_name_or_filler_status() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();

        // These stand in for the future machine LCTs. The projection is deliberately
        // agnostic to HOW that parent identity is minted; it reads only the LCT binding.
        ensure_member(&mut vault, &mut reg, "sprout-claude", false, "machine-a", "anchor")
            .unwrap();
        ensure_member(&mut vault, &mut reg, "sprout-being", false, "machine-a", "anchor")
            .unwrap();
        ensure_member(&mut vault, &mut reg, "sprout-stale", false, "machine-b", "anchor")
            .unwrap();
        ensure_filler(
            &mut vault,
            &mut reg,
            "sprout-local-reasoner",
            "machine-a",
            "anchor",
        )
        .unwrap();

        let children = reg.children_of("machine-a");
        assert_eq!(
            children.iter().map(|(id, _)| *id).collect::<Vec<_>>(),
            vec!["sprout-being", "sprout-claude"],
            "same-name-prefix remote members and fillers are not hosted children"
        );

        let being_lct = reg.get("sprout-being").unwrap().lct_id();
        match reg.resolve_child_of("machine-a", &being_lct).unwrap() {
            LocalChildResolution::Local(r) => assert_eq!(r.plugin_id, "sprout-being"),
            other => panic!("sprout-being should be local, got {other:?}"),
        }

        let stale_lct = reg.get("sprout-stale").unwrap().lct_id();
        match reg.resolve_child_of("machine-a", &stale_lct).unwrap() {
            LocalChildResolution::KnownButNotChild(r) => assert_eq!(r.plugin_id, "sprout-stale"),
            other => panic!("known remote child must not become local, got {other:?}"),
        }

        assert!(matches!(
            reg.resolve_child_of("machine-a", "sprout-ghost").unwrap(),
            LocalChildResolution::Unknown
        ));
    }

    #[test]
    fn members_survive_a_reload() {
        let (_dir, mut vault) = fresh_vault();
        let mut reg = MemberRegistry::default();
        let minted =
            ensure_member(&mut vault, &mut reg, "claude-code", false, "sid", "anchor").unwrap();
        // Reload from the vault (a restart).
        let reloaded = load_members(&vault);
        assert_eq!(reloaded.len(), 1);
        assert_eq!(reloaded.get("claude-code").unwrap().lct_id(), minted);
    }
}

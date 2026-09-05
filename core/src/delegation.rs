//! Delegation management — vault-backed storage for DelegatedAuthority grants.
//!
//! Wraps web4-core's `DelegatedAuthority` with local persistence (JSON file
//! alongside the vault) and CLI surface for creating, listing, and revoking
//! delegations.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use uuid::Uuid;
use web4_core::crypto::KeyPair;
use web4_core::delegation::{DelegatedAuthority, DelegationScope};
use web4_core::role::SocietyRole;

/// On-disk delegation store — a JSON array of DelegatedAuthority.
#[derive(Debug, Serialize, Deserialize, Default)]
pub struct DelegationStore {
    pub delegations: Vec<DelegatedAuthority>,
}

impl DelegationStore {
    /// Load delegations from the vault (migrating a legacy `delegations.json`).
    pub fn load(vault: &crate::vault::Vault) -> Result<Self> {
        crate::vault::load_doc(vault, "presence", "delegations", "delegations.json")
    }

    /// Persist delegations as an encrypted vault document.
    pub fn save(&self, vault: &mut crate::vault::Vault) -> Result<()> {
        crate::vault::save_doc(vault, "presence", "delegations", "delegations.json", self)
    }

    pub fn create_delegation(
        &mut self,
        delegator_lct_id: Uuid,
        agent_lct_id: Uuid,
        roles: Vec<SocietyRole>,
        actions: Vec<String>,
        expires_hours: Option<u64>,
        delegator_keypair: &KeyPair,
    ) -> &DelegatedAuthority {
        let scope = if roles.is_empty() && actions.is_empty() {
            DelegationScope::unrestricted()
        } else {
            DelegationScope {
                roles,
                actions,
                society_lct_id: None,
            }
        };

        let expires_at =
            expires_hours.map(|h| chrono::Utc::now() + chrono::Duration::hours(h as i64));

        let deleg = DelegatedAuthority::create(
            delegator_lct_id,
            agent_lct_id,
            scope,
            expires_at,
            delegator_keypair,
        );

        self.delegations.push(deleg);
        self.delegations.last().unwrap()
    }

    pub fn revoke(&mut self, delegation_id: Uuid) -> Result<()> {
        let deleg = self
            .delegations
            .iter_mut()
            .find(|d| d.id == delegation_id)
            .ok_or_else(|| anyhow::anyhow!("delegation {} not found", delegation_id))?;
        deleg.revoke();
        Ok(())
    }

    pub fn active(&self) -> Vec<&DelegatedAuthority> {
        self.delegations.iter().filter(|d| d.is_active()).collect()
    }

    pub fn for_agent(&self, agent_lct_id: Uuid) -> Vec<&DelegatedAuthority> {
        self.delegations
            .iter()
            .filter(|d| d.agent_lct_id == agent_lct_id && d.is_active())
            .collect()
    }

    /// THE FIRST ENFORCEMENT POINT THIS STORE HAS EVER HAD (#952).
    ///
    /// Until now `DelegationStore` was written by the CLI, listed by the CLI, and rendered by
    /// the dashboard, and **no surface consulted it before deciding anything**. `delegate grant`
    /// recorded an intention with no teeth. That is the honest starting state, and it is why
    /// this lookup is deliberately narrow rather than a general "may agent X do action Y":
    /// giving a dormant store its first authority is the moment to be conservative about what
    /// it can confer, not the moment to generalise.
    ///
    /// Answers exactly one question: may `agent_lct_id` rule a scope request for `path`?
    ///
    /// Matching, and why each clause is the way it is:
    ///
    /// * **`actions` must name it.** An UNRESTRICTED delegation (empty roles AND empty actions,
    ///   `DelegationScope::unrestricted`) does NOT confer this. Every delegation minted before
    ///   this commit is unrestricted or role-only, and none of their delegators could have meant
    ///   "and may also widen a member's filesystem reach" — the power did not exist to mean. A
    ///   dormant record must not gain authority by a later release; the operator re-grants
    ///   naming the action, which is one command and leaves a dated record of the intent.
    /// * **Roles confer nothing here.** Same reasoning: `--role administrator` was never a
    ///   statement about scope rulings.
    /// * **Bounded by path prefix, not by asker.** `scope.decide:<prefix>` lets an operator
    ///   delegate "rulings on that being's own home" without also delegating rulings on
    ///   shared-context, a repo, or `/`. Bounding by asker instead would let one seat grant its
    ///   own being anything that being thought to ask for.
    /// * **Containment is `_within_path_grant`'s rule**, separator-anchored, so a delegation on
    ///   `/a/b` never covers `/a/bc`. Bare `scope.decide` is unbounded and covers any path — an
    ///   operator can still say that, deliberately, and the record shows it.
    ///
    /// Returns the delegation that authorises the ruling, so the caller can name its id in the
    /// witnessed record. A ruling whose authority is not attributable is not auditable.
    pub fn scope_decide_authority_for(
        &self,
        agent_lct_id: Uuid,
        path: &str,
        member: &str,
    ) -> Option<&DelegatedAuthority> {
        self.delegations.iter().find(|d| {
            d.agent_lct_id == agent_lct_id
                && d.is_active()
                && d.scope
                    .actions
                    .iter()
                    .any(|a| action_covers(a, path, member))
        })
    }
}

/// The delegation-store key for a seat, derived from its **registry LCT** — the id that comes
/// from its public key — and not from its plugin name, its UID, or its machine (sprout-claude
/// on #952: "keyed to the seat's LCT rather than a UID or machine name"; hestia #954 is about
/// to make UID identity meaningful and this must not acquire a dependency on it).
///
/// `DelegatedAuthority.agent_lct_id` is a `Uuid` in web4-core while member LCTs are mb32
/// strings, so this is a deterministic UUIDv5 over the LCT string under a fixed hestia
/// namespace: same seat, same key, on any machine, with no schema change and no allocator.
/// `hestia delegate agent-id <plugin_id>` prints it so an operator can grant against it.
pub fn agent_key_for_lct(lct_id: &str) -> Uuid {
    // A fixed, arbitrary namespace constant: it only has to be stable, and it is.
    const NS: Uuid = Uuid::from_bytes([
        0x68, 0x65, 0x73, 0x74, 0x69, 0x61, 0x2d, 0x64, 0x65, 0x6c, 0x65, 0x67, 0x61, 0x74, 0x65,
        0x00,
    ]);
    Uuid::new_v5(&NS, lct_id.trim().as_bytes())
}

/// The exact bytes a delegate signs to rule a scope request (#952).
///
/// WHY A SIGNATURE AT ALL. `hestia_connect` authenticates nobody (#63/#128): a session's
/// `plugin_id` is asserted by the caller. That is tolerable for the escalation arbiter, which
/// records a second-party review; it is NOT tolerable for the one MCP path that mints a
/// STANDING grant, because durable loosening is the thing the operator wall exists to keep
/// attributable. So the ruling carries a signature by the delegate's own registry key, and the
/// daemon verifies it against the public key the member registry already holds.
///
/// This does not create a new preventive boundary at assurance A1 — anyone who can open the
/// vault to sign could also mint a delegation or write a standing grant directly. What it
/// creates is EVIDENCE: the chain records a ruling attributable to a key, not to a name a
/// caller typed. Domain-separated and versioned so it can never be confused with another
/// signature this fleet produces.
pub fn arbitration_message(request_id: &str, granted: bool, reason: &str) -> String {
    format!(
        "hestia:scope-arbitrate:v1\n{request_id}\n{}\n{reason}",
        if granted { "granted" } else { "refused" }
    )
}

/// The delegable action name for scope rulings.
///
/// Forms, narrowest last:
/// * `scope.decide` — every path, every member. An operator can still say this deliberately.
/// * `scope.decide:/abs/prefix` — that subtree, any member.
/// * `scope.decide:<member>:/abs/prefix` — that subtree AND only that member's requests.
///
/// The member comes BEFORE the path, and the path is always absolute. That ordering is what
/// makes the grammar unambiguous: an earlier draft put the member after the path as
/// `…:/abs/prefix@member`, and `@` is legal in a path (`/home/dp/mail@archive` parsed as
/// prefix `/home/dp/mail`, member `archive`). Caught by the mesh session on #952 before any
/// such delegation existed. With the member first, the first `:` after the action name
/// starts either a member (no leading `/`) or a path (leading `/`), and nothing else can.
///
/// The member form exists because a prefix alone is sufficient for a being's own home but
/// NOT for a shared path (sprout-claude, #952): delegating `scope.decide:/…/shared-context`
/// without it would let the holder rule that path for any member that asks.
pub const ACTION_SCOPE_DECIDE: &str = "scope.decide";

/// Does the delegated action string authorise a scope ruling on `path` for `member`?
///
/// Containment is separator-anchored, matching the gate's `_within_path_grant`: a prefix
/// covers itself and its descendants and nothing else, so a delegation on `/x/b` never covers
/// `/x/bb` — which on this fleet is a DIFFERENT being's home, one directory over. Purely
/// lexical on already-normalised absolute paths: the daemon records and the gate enforces, and
/// the two do not necessarily share a mount, so this must not resolve symlinks it cannot see.
pub fn action_covers(action: &str, path: &str, member: &str) -> bool {
    let path = path.trim_end_matches('/');
    let Some((name, rest)) = action.split_once(':') else {
        return action == ACTION_SCOPE_DECIDE;
    };
    if name != ACTION_SCOPE_DECIDE {
        return false;
    }
    // `rest` is either `/abs/prefix` or `<member>:/abs/prefix`. A member never starts with
    // `/` and never contains `:` (it is a plugin id), so the split is exact.
    let (bound_member, prefix) = if rest.starts_with('/') {
        (None, rest)
    } else {
        match rest.split_once(':') {
            Some((m, p)) => (Some(m.trim()), p),
            None => return false, // `scope.decide:legion-being` with no path binds nothing
        }
    };
    if let Some(m) = bound_member {
        if m.is_empty() || m != member {
            return false;
        }
    }
    let prefix = prefix.trim().trim_end_matches('/');
    // An empty or relative prefix authorises nothing: `scope.decide:` would otherwise read
    // as unbounded, which is the opposite of what typing a bound means.
    if prefix.is_empty() || !prefix.starts_with('/') {
        return false;
    }
    path == prefix || path.starts_with(&format!("{prefix}/"))
}

/// Parse a role name string into a SocietyRole.
pub fn parse_role(s: &str) -> Result<SocietyRole> {
    match s.to_lowercase().as_str() {
        "sovereign" => Ok(SocietyRole::Sovereign),
        "laworacle" | "law_oracle" | "law-oracle" => Ok(SocietyRole::LawOracle),
        "policyentity" | "policy_entity" | "policy-entity" => Ok(SocietyRole::PolicyEntity),
        "treasurer" => Ok(SocietyRole::Treasurer),
        "administrator" | "admin" => Ok(SocietyRole::Administrator),
        "archivist" => Ok(SocietyRole::Archivist),
        "citizen" => Ok(SocietyRole::Citizen),
        "witness" => Ok(SocietyRole::Witness),
        "auditor" => Ok(SocietyRole::Auditor),
        other => Ok(SocietyRole::Custom(other.to_string())),
    }
}

/// The delegator every delegation on this box is signed by: the vault's own identity key
/// (`ai_identity_secret`), the same key `hub join` and `profile push` sign with. Before #952
/// `delegate grant` signed with `KeyPair::generate()` and named a random UUID as delegator,
/// so every record claimed a provenance it did not have. The delegator id is the UUIDv5 of
/// the key's derived LCT id, so a reader can recompute who signed from the key alone.
pub fn vault_delegator(vault: &crate::vault::Vault) -> Result<(Uuid, KeyPair)> {
    let secret_hex = vault
        .get("ai_identity_secret")
        .map(|e| e.secret.clone())
        .ok_or_else(|| anyhow::anyhow!(
            "no identity key in the vault (ai_identity_secret) — run `hestia init --ai`; a \
             delegation must be signed by the operator's own key, not a throwaway"
        ))?;
    let bytes = hex::decode(secret_hex.trim()).context("ai_identity_secret is not hex")?;
    let arr: [u8; 32] = bytes
        .as_slice()
        .try_into()
        .map_err(|_| anyhow::anyhow!("ai_identity_secret is not 32 bytes"))?;
    let kp = KeyPair::from_secret_bytes(&arr);
    let lct_id = web4_core::derive_lct_id(&kp.verifying_key());
    Ok((agent_key_for_lct(&lct_id), kp))
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---- #952: the first enforcement point, and the cases that would bite ----

    fn store_with(actions: Vec<&str>) -> (DelegationStore, Uuid) {
        let kp = KeyPair::generate();
        let agent = Uuid::new_v4();
        let mut st = DelegationStore::default();
        st.create_delegation(
            Uuid::new_v4(),
            agent,
            vec![],
            actions.into_iter().map(String::from).collect(),
            None,
            &kp,
        );
        (st, agent)
    }

    /// The one sprout-claude flagged: a bare string prefix would also match the being next
    /// door. `/…/instances/b` must never cover `/…/instances/bb`.
    #[test]
    fn prefix_is_separator_anchored_not_a_string_prefix() {
        let a = "scope.decide:/home/dp/ws/instances/b";
        assert!(action_covers(a, "/home/dp/ws/instances/b", "m"));
        assert!(action_covers(a, "/home/dp/ws/instances/b/journal.md", "m"));
        assert!(!action_covers(a, "/home/dp/ws/instances/bb", "m"));
        assert!(!action_covers(a, "/home/dp/ws/instances/bb/journal.md", "m"));
        assert!(!action_covers(a, "/home/dp/ws/instances", "m"));
    }

    /// A prefix alone is enough for a being's own home but not for a shared path, so the
    /// `@member` form ANDs the two.
    #[test]
    fn member_bound_action_only_covers_that_member() {
        let a = "scope.decide:legion-being:/home/dp/ws/shared-context";
        assert!(action_covers(a, "/home/dp/ws/shared-context/forum", "legion-being"));
        assert!(!action_covers(a, "/home/dp/ws/shared-context/forum", "sprout-being"));
        assert!(!action_covers(a, "/home/dp/ws/other", "legion-being"));
    }

    #[test]
    fn bare_action_is_unbounded_and_relative_or_empty_prefix_authorises_nothing() {
        assert!(action_covers("scope.decide", "/anything/at/all", "m"));
        assert!(!action_covers("scope.decide:", "/anything", "m"));
        assert!(!action_covers("scope.decide:relative/path", "/relative/path", "m"));
        assert!(!action_covers("scope.decide:legion-being", "/a", "m")); // member, no path
        assert!(!action_covers("scope.decide::/a", "/a", "m"));          // empty member
        // `@` is legal in a path and must never be read as a member separator
        assert!(action_covers("scope.decide:/home/dp/mail@archive", "/home/dp/mail@archive/x", "m"));
        assert!(!action_covers("scope.decide:/home/dp/mail@archive", "/home/dp/mail", "m"));
        assert!(!action_covers("witness.attest:/a", "/a", "m"));
    }

    /// A delegation minted before this action existed must not silently gain the power to
    /// widen a member's filesystem reach.
    #[test]
    fn unrestricted_and_role_only_delegations_confer_nothing() {
        let kp = KeyPair::generate();
        let agent = Uuid::new_v4();
        let mut st = DelegationStore::default();
        st.create_delegation(Uuid::new_v4(), agent, vec![], vec![], None, &kp); // unrestricted
        st.create_delegation(
            Uuid::new_v4(),
            agent,
            vec![SocietyRole::Administrator],
            vec![],
            None,
            &kp,
        );
        assert!(st.scope_decide_authority_for(agent, "/home/dp/ws", "m").is_none());
    }

    #[test]
    fn authority_requires_the_same_agent_and_survives_only_while_active() {
        let (mut st, agent) = store_with(vec!["scope.decide:/home/dp/ws/x"]);
        assert!(st
            .scope_decide_authority_for(agent, "/home/dp/ws/x/journal.md", "m")
            .is_some());
        assert!(st
            .scope_decide_authority_for(Uuid::new_v4(), "/home/dp/ws/x/journal.md", "m")
            .is_none());
        assert!(st.scope_decide_authority_for(agent, "/home/dp/ws/y", "m").is_none());
        let id = st.delegations[0].id;
        st.revoke(id).unwrap();
        assert!(st
            .scope_decide_authority_for(agent, "/home/dp/ws/x/journal.md", "m")
            .is_none());
    }

    /// Keyed to the LCT, so the same seat resolves to the same key anywhere, and two seats
    /// never collide.
    #[test]
    fn agent_key_is_deterministic_per_lct() {
        let a = agent_key_for_lct("lct:web4:mb32:baaa");
        assert_eq!(a, agent_key_for_lct("  lct:web4:mb32:baaa  "));
        assert_ne!(a, agent_key_for_lct("lct:web4:mb32:bbbb"));
    }

    #[test]
    fn test_create_and_list() {
        let kp = KeyPair::generate();
        let delegator = Uuid::new_v4();
        let agent = Uuid::new_v4();

        let mut store = DelegationStore::default();
        store.create_delegation(
            delegator,
            agent,
            vec![SocietyRole::Administrator],
            vec![],
            None,
            &kp,
        );

        assert_eq!(store.delegations.len(), 1);
        assert_eq!(store.active().len(), 1);
        assert_eq!(store.for_agent(agent).len(), 1);
        assert_eq!(store.for_agent(Uuid::new_v4()).len(), 0);
    }

    #[test]
    fn test_revoke() {
        let kp = KeyPair::generate();
        let mut store = DelegationStore::default();
        store.create_delegation(Uuid::new_v4(), Uuid::new_v4(), vec![], vec![], None, &kp);

        let id = store.delegations[0].id;
        assert_eq!(store.active().len(), 1);

        store.revoke(id).unwrap();
        assert_eq!(store.active().len(), 0);
    }

    #[test]
    fn test_persistence_roundtrip() {
        let kp = KeyPair::generate();
        let mut store = DelegationStore::default();
        store.create_delegation(
            Uuid::new_v4(),
            Uuid::new_v4(),
            vec![SocietyRole::Witness],
            vec!["attest".into()],
            Some(24),
            &kp,
        );

        let json = serde_json::to_string(&store).unwrap();
        let recovered: DelegationStore = serde_json::from_str(&json).unwrap();
        assert_eq!(recovered.delegations.len(), 1);
        assert!(recovered.delegations[0].is_active());
    }
}

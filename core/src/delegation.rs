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
    /// * **Optionally ANDed with the member**, on sprout's amendment (#952, 2026-09-05). A bare
    ///   prefix is sufficient for a being's own home, because one member owns that subtree. It
    ///   is NOT sufficient for a shared path: `scope.decide:/home/dp/ai-workspace/shared-context`
    ///   would let the holder rule that path for ANY member that asked. The member bound is
    ///   never expressible alone — see `action_covers`.
    /// * **Containment is `_within_path_grant`'s rule**, separator-anchored, so a delegation on
    ///   `/a/b` never covers `/a/bc`. Bare `scope.decide` is unbounded and covers any path — an
    ///   operator can still say that, deliberately, and the record shows it.
    ///
    /// Returns the delegation that authorises the ruling, so the caller can name its id in the
    /// witnessed record. A ruling whose authority is not attributable is not auditable.
    pub fn scope_decide_authority(
        &self,
        agent_lct_id: Uuid,
        member: &str,
        path: &str,
    ) -> Option<&DelegatedAuthority> {
        self.delegations.iter().find(|d| {
            d.agent_lct_id == agent_lct_id
                && d.is_active()
                && d.scope
                    .actions
                    .iter()
                    .any(|a| action_covers(a, member, path))
        })
    }
}

/// The delegable action name for scope rulings.
///
/// Three spellings, widening to narrowing:
///
/// | action                              | rules for      | over          |
/// |-------------------------------------|----------------|---------------|
/// | `scope.decide`                      | any member     | any path      |
/// | `scope.decide:/abs/prefix`          | any member     | that subtree  |
/// | `scope.decide:<member>:/abs/prefix` | that member    | that subtree  |
///
/// There is deliberately no fourth row. `scope.decide:<member>` — a member bound with no path
/// bound — is NOT a spelling, and `action_covers` refuses it: bounding by asker alone is the
/// exact failure this feature must not introduce, since it would let a seat grant its own being
/// anything that being thought to ask for.
pub const ACTION_SCOPE_DECIDE: &str = "scope.decide";

/// Does the delegated action string `action` authorise a scope ruling on `path` for `member`?
///
/// Separator-anchored containment, matching the gate's `_within_path_grant`: a prefix covers
/// itself and its descendants and nothing else, so `/a/b` never covers `/a/bc`. Purely lexical
/// on already-normalised absolute paths — the daemon records, the gate enforces, and the two do
/// not necessarily share a mount, so this must not resolve symlinks it cannot see.
///
/// The member/prefix ambiguity is resolved by a property of the values, not by a count of
/// colons: a scope path is always ABSOLUTE, so the field after `scope.decide:` is a path iff it
/// starts with `/`, and otherwise it is a member id. That is why a member id containing `/` is
/// refused below rather than merely unmatched — permitting one would make the grammar
/// ambiguous, and an ambiguous authority grammar resolves in the grantee's favour eventually.
pub fn action_covers(action: &str, member: &str, path: &str) -> bool {
    let path = path.trim_end_matches('/');
    let Some((name, rest)) = action.split_once(':') else {
        // Bare, unbounded — and only the exact action name. A role, or any other action a
        // pre-#952 delegation happens to carry, confers nothing here.
        return action == ACTION_SCOPE_DECIDE;
    };
    if name != ACTION_SCOPE_DECIDE {
        return false;
    }
    let rest = rest.trim();
    let (bound_member, prefix) = if rest.starts_with('/') {
        (None, rest)
    } else {
        match rest.split_once(':') {
            // `scope.decide:<member>:<prefix>` — both bounds, ANDed.
            Some((m, p)) => (Some(m.trim()), p.trim()),
            // `scope.decide:<member>` with no path bound. Refused: see ACTION_SCOPE_DECIDE.
            None => return false,
        }
    };
    if let Some(m) = bound_member {
        // An empty member bound is not "any member" — it is a malformed bound, and reading it
        // as the wider of the two meanings is how a typo becomes a widening. A member id
        // containing `/` would make the grammar ambiguous; refuse rather than guess.
        if m.is_empty() || m.contains('/') || m != member {
            return false;
        }
    }
    let prefix = prefix.trim_end_matches('/');
    // An empty or relative prefix authorises nothing: `scope.decide:` would otherwise read as
    // unbounded, which is the opposite of what typing a bound means.
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

#[cfg(test)]
mod tests {
    use super::*;

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

    // ── #952 delegable scope arbitration: the action grammar ────────────────────────────
    //
    // These pin the REFUSALS as hard as the grants. The grant path is the feature; the
    // refusal path is the reason the feature is allowed to exist, and it is the half that
    // rots silently — a widened matcher still passes every "it works" test.

    #[test]
    fn a_bare_prefix_covers_itself_and_its_descendants_and_nothing_else() {
        let p = "scope.decide:/w/sage/instances/b";
        assert!(action_covers(p, "sage", "/w/sage/instances/b"));
        assert!(action_covers(p, "sage", "/w/sage/instances/b/memory/n.md"));
        // Any member, since no member bound was typed.
        assert!(action_covers(p, "codex", "/w/sage/instances/b/x"));
        // The sibling-prefix defect sprout measured on SAGE #39: `/…/b` must not reach
        // `/…/bb`, a DIFFERENT being's home. Separator-anchored, so it does not.
        assert!(!action_covers(p, "sage", "/w/sage/instances/bb"));
        assert!(!action_covers(p, "sage", "/w/sage/instances/bb/memory/n.md"));
        // Upward is not containment either.
        assert!(!action_covers(p, "sage", "/w/sage/instances"));
        assert!(!action_covers(p, "sage", "/w"));
        assert!(!action_covers(p, "sage", "/etc/shadow"));
    }

    #[test]
    fn a_member_bound_is_anded_with_the_prefix_never_substituted_for_it() {
        // sprout's case 1: a SHARED path, where the prefix alone would let the holder rule
        // for any member that asked.
        let shared = "scope.decide:sage-sprout:/w/shared-context";
        assert!(action_covers(shared, "sage-sprout", "/w/shared-context/forum/x.md"));
        assert!(action_covers(shared, "sage-sprout", "/w/shared-context"));
        // Same path, different asker — the whole point of the amendment.
        assert!(!action_covers(shared, "codex", "/w/shared-context/forum/x.md"));
        // Right asker, wrong path: the member bound does not widen the path bound.
        assert!(!action_covers(shared, "sage-sprout", "/w/hestia"));
        // And the sibling-prefix rule still holds under a member bound.
        assert!(!action_covers(shared, "sage-sprout", "/w/shared-contextX"));
    }

    #[test]
    fn bounding_by_asker_alone_is_not_expressible() {
        // THE failure this feature must not introduce: a seat granting its own being
        // whatever that being thought to ask for. There is no spelling for it.
        assert!(!action_covers("scope.decide:sage-sprout", "sage-sprout", "/etc/shadow"));
        assert!(!action_covers("scope.decide:sage-sprout", "sage-sprout", "/w/anything"));
        // An empty member bound reads as a malformed bound, not as "any member" — resolving
        // a typo toward the wider meaning is how a widening arrives unnoticed.
        assert!(!action_covers("scope.decide::/w/x", "sage", "/w/x"));
        // A relative or empty prefix authorises nothing, alone or under a member bound.
        assert!(!action_covers("scope.decide:", "sage", "/w/x"));
        assert!(!action_covers("scope.decide:w/x", "sage", "/w/x"));
        assert!(!action_covers("scope.decide:sage:w/x", "sage", "/w/x"));
        assert!(!action_covers("scope.decide:sage:", "sage", "/w/x"));
    }

    #[test]
    fn a_dormant_delegation_does_not_acquire_scope_authority_by_upgrade() {
        // Every delegation minted before #952 is unrestricted or role-only. None of their
        // delegators could have meant "and may also widen a member's filesystem reach" —
        // the power did not exist to mean. So: nothing but the named action confers it.
        let kp = KeyPair::generate();
        let agent = Uuid::new_v4();
        let mut store = DelegationStore::default();

        // UNRESTRICTED (empty roles AND empty actions) — the widest thing expressible.
        store.create_delegation(Uuid::new_v4(), agent, vec![], vec![], None, &kp);
        assert!(
            store.scope_decide_authority(agent, "sage", "/w/x").is_none(),
            "an unrestricted delegation must not confer scope rulings by silence"
        );

        // Role-only, including the most authoritative role there is.
        store.create_delegation(
            Uuid::new_v4(),
            agent,
            vec![SocietyRole::Administrator],
            vec![],
            None,
            &kp,
        );
        assert!(store.scope_decide_authority(agent, "sage", "/w/x").is_none());

        // A neighbouring action name must not prefix-match into the real one.
        store.create_delegation(
            Uuid::new_v4(),
            agent,
            vec![],
            vec!["scope.decide.all".into(), "scope".into(), "decide".into()],
            None,
            &kp,
        );
        assert!(store.scope_decide_authority(agent, "sage", "/w/x").is_none());
    }

    #[test]
    fn scope_decide_authority_names_the_delegation_that_authorised_it() {
        // A ruling whose authority is not attributable is not auditable, so the lookup
        // returns the record rather than a bool.
        let kp = KeyPair::generate();
        let seat = Uuid::new_v4();
        let other_seat = Uuid::new_v4();
        let mut store = DelegationStore::default();
        let id = store
            .create_delegation(
                Uuid::new_v4(),
                seat,
                vec![],
                vec!["scope.decide:sage:/w/sage/instances/b".into()],
                Some(24),
                &kp,
            )
            .id;

        let found = store
            .scope_decide_authority(seat, "sage", "/w/sage/instances/b/memory")
            .expect("the delegation authorises this ruling");
        assert_eq!(found.id, id);

        // Held by a DIFFERENT seat: a delegation is to one holder, not to the fleet.
        assert!(store
            .scope_decide_authority(other_seat, "sage", "/w/sage/instances/b/memory")
            .is_none());

        // Revoked is not active, and revocation is the operation a policy authority most
        // needs to work.
        store.revoke(id).unwrap();
        assert!(store
            .scope_decide_authority(seat, "sage", "/w/sage/instances/b/memory")
            .is_none());
    }
}

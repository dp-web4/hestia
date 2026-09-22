//! Retired members: the operator's answer to an id that should no longer be a party.
//!
//! WHY THIS EXISTS. A member id is caller-asserted free text, so a typo in a grant form mints a
//! member (#1067, now refused at the source). dp's trust list carried `claude-code` (5,415 acts),
//! `Claude-code` (0) and `caude-code` (0) as three agents from 2026-09-08, and said the same thing
//! on 09-19 and again on 09-21: *"we still have three versions of you in hestia that i don't see a
//! way of managing."* Aliasing (#1075) folds their EVIDENCE; it does not stop them being parties,
//! and it leaves the rows. Nothing in hestia could say "this id is not a member here any more".
//!
//! WHAT RETIREMENT IS, AND IS NOT.
//!
//! It is not deletion. The chain is append-only and history stays exactly where it landed; a
//! retirement is a new fact ABOUT an id, witnessed like any other. `retired` is a live index
//! rebuilt from the vault, the same construction as the member and role registries.
//!
//! It removes AUTHORITY and it removes the id from the default view. Concretely:
//!   * every grant the id holds -- standing AND live -- is revoked in the same act that retires
//!     it, so there is no window in which a retired id still reaches a path;
//!   * authority reaches it through NO door afterwards: `scope_grant`, `scope_decide`,
//!     `standing/promote` and `standing/reassign` all refuse it through one helper
//!     (`http::refuse_if_retired`) -- one per route was how a reviewer found the gap;
//!   * the agent list hides it unless the operator asks to see retired ids.
//!
//! IT DOES NOT REFUSE A CONNECT, and that is a decision rather than an omission. Retiring an id
//! that is actually running would then lock a live seat out of its own machine, and the phantom
//! case -- the one this exists for -- can never connect at all. So a retired id that DOES connect
//! is treated as news: `tool_connect` witnesses `retired_member_connected`, and the agents view
//! keeps the row visible -- marked -- while the id is connected or has acted.
//! Hiding a retired agent that is demonstrably alive is the one direction that would be dangerous,
//! because it hides a live agent.
//!
//! PER-SEAT, AND NOT PROPAGATED. Each seat retires its own view. A retirement is not published to
//! the hub and does not reach another seat's registry: a member's standing elsewhere is that
//! society's business, and a mechanism that let one seat retire an id fleet-wide would be a much
//! larger authority than the one being asked for. Proposed to dp on 2026-09-19 as PRD question 1
//! and never answered; built the conservative way rather than left unbuilt, because the ask it
//! blocks was dp's FIRST one. It is reversible (`reinstate`) and the choice is recorded here so
//! that a later ruling changes a stated decision rather than discovering an accident.

use serde::{Deserialize, Serialize};

const RETIRED_NAMESPACE: &str = "members";
const RETIRED_DOC: &str = "retired";
const RETIRED_LEGACY_FILE: &str = "retired-members.json";

/// One retired id, with the account of why. `ref` and `reason` are required at the route: a
/// retirement that revokes authority and hides a row must not be an unexplained row itself.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RetiredMember {
    pub plugin_id: String,
    pub retired_at: u64,
    pub reason: String,
    #[serde(default, rename = "ref")]
    pub evidence_ref: String,
    /// What the id held when it was retired, so reinstating is an informed act rather than a
    /// blind one. Recorded, NOT restored -- see `reinstate`.
    #[serde(default)]
    pub revoked_paths: Vec<String>,
    /// True when the operator overrode the recently-acted guard.
    #[serde(default)]
    pub was_active: bool,
}

/// `plugin_id -> retirement`, rebuilt from the vault at load like the member registry.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct RetirementStore {
    /// Monotonic across retire AND reinstate, so a reader can order two snapshots. Same reason
    /// `StandingScopeStore` has one.
    #[serde(default)]
    pub generation: u64,
    #[serde(default)]
    pub retired: Vec<RetiredMember>,
}

impl RetirementStore {
    pub fn is_retired(&self, plugin_id: &str) -> bool {
        self.get(plugin_id).is_some()
    }

    pub fn get(&self, plugin_id: &str) -> Option<&RetiredMember> {
        let id = plugin_id.trim();
        self.retired.iter().find(|r| r.plugin_id == id)
    }

    pub fn ids(&self) -> Vec<String> {
        let mut v: Vec<String> = self.retired.iter().map(|r| r.plugin_id.clone()).collect();
        v.sort();
        v
    }

    /// Idempotent: retiring an already-retired id replaces the record rather than stacking a
    /// second one, and still moves the generation (the operator restated it; a reader ordering
    /// snapshots must see that something happened).
    pub fn retire(&mut self, r: RetiredMember) {
        self.retired.retain(|x| x.plugin_id != r.plugin_id);
        self.retired.push(r);
        self.retired.sort_by(|a, b| a.plugin_id.cmp(&b.plugin_id));
        self.generation += 1;
    }

    /// Returns the record removed, or None when the id was not retired.
    pub fn reinstate(&mut self, plugin_id: &str) -> Option<RetiredMember> {
        let id = plugin_id.trim();
        let i = self.retired.iter().position(|r| r.plugin_id == id)?;
        let r = self.retired.remove(i);
        self.generation += 1;
        Some(r)
    }
}

pub fn load(vault: &crate::vault::Vault) -> RetirementStore {
    crate::vault::load_doc(vault, RETIRED_NAMESPACE, RETIRED_DOC, RETIRED_LEGACY_FILE)
        .unwrap_or_default()
}

pub fn save(
    vault: &mut crate::vault::Vault,
    store: &RetirementStore,
) -> anyhow::Result<()> {
    crate::vault::save_doc(vault, RETIRED_NAMESPACE, RETIRED_DOC, RETIRED_LEGACY_FILE, store)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rec(id: &str) -> RetiredMember {
        RetiredMember {
            plugin_id: id.into(),
            retired_at: 1,
            reason: "typo".into(),
            evidence_ref: "dp 2026-09-08".into(),
            revoked_paths: vec![],
            was_active: false,
        }
    }

    #[test]
    fn retiring_twice_restates_rather_than_stacks_and_still_moves_the_generation() {
        let mut s = RetirementStore::default();
        s.retire(rec("Claude-code"));
        s.retire(rec("caude-code"));
        assert_eq!(s.ids(), vec!["Claude-code", "caude-code"]);
        let g = s.generation;
        s.retire(RetiredMember { reason: "restated".into(), ..rec("Claude-code") });
        assert_eq!(s.retired.len(), 2, "a restatement replaces, it does not stack");
        assert_eq!(s.get("Claude-code").unwrap().reason, "restated");
        assert!(s.generation > g, "a reader ordering two snapshots must see that this happened");
    }

    #[test]
    fn reinstate_returns_what_it_removed_and_is_a_no_op_on_an_id_that_was_never_retired() {
        let mut s = RetirementStore::default();
        s.retire(rec("caude-code"));
        assert!(s.is_retired("caude-code"));
        // Trimmed, like `member_lct`: the operator's whitespace is not a different member.
        assert!(s.is_retired("  caude-code  "));
        let g = s.generation;
        assert!(s.reinstate("nobody").is_none(), "nothing to undo");
        assert_eq!(s.generation, g, "a no-op must not move the generation");
        assert_eq!(s.reinstate("caude-code").unwrap().reason, "typo");
        assert!(!s.is_retired("caude-code"));
        assert!(s.generation > g);
    }
}

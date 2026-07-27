//! Operator-editable policy lists — the law, as data, bound to agents.
//!
//! dp, 2026-07-26: "we might consider a more sophisticated allow/deny lists, global and
//! per-agent, that get formed into the operating law for each session, that's injected at
//! launch. transparency. the lists should live in the vault, but the law should be
//! queriable in-session." … "the lists should be operator-editable … and operator should
//! be able to match lists to agents. also, permissions per list should be
//! read/write/list/delete, the last two being distinct."
//!
//! WHY LISTS RATHER THAN MORE RULES. Rules live in code and presets; changing one is a
//! deploy. A list is data an operator edits, binds to whichever agents it should govern,
//! and which composes into that session's law at launch. The same policy engine enforces
//! it — this is about who can author law and how legible it is, not about a second
//! enforcement path.
//!
//! THE FOUR VERBS ARE FOUR, NOT TWO. It is tempting to collapse these into read/write, and
//! the collapse is where authorization bugs live:
//!
//!   * `List`   — learn that an entry EXISTS, and its name. Not its contents.
//!   * `Read`   — see the contents of an entry.
//!   * `Write`  — create or modify an entry.
//!   * `Delete` — remove one. NOT implied by `Write`.
//!
//! `List` without `Read` is the common and correct case for credentials: an agent may need
//! to know `kaggle-token` exists in order to ask for it, without being able to read it.
//! Folding `List` into `Read` forces a choice between blinding the agent and handing it the
//! secret.
//!
//! `Delete` separate from `Write` matters for the opposite reason: a write is recoverable
//! from history, a delete is the one verb that destroys. An agent that must maintain a list
//! needs `Write`; almost none of them need `Delete`, and granting it because it "feels like
//! writing" is how an irreversible verb gets handed out by default.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// One capability over a list. Distinct verbs, deliberately — see the module docs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ListPerm {
    /// Enumerate entry names/metadata without seeing contents.
    List,
    /// See entry contents.
    Read,
    /// Create or modify entries. Does NOT imply Delete.
    Write,
    /// Remove entries. The only verb that destroys; never implied.
    Delete,
}

impl ListPerm {
    /// Parse from the wire. Unknown verbs are rejected rather than ignored — silently
    /// dropping an unrecognised permission would grant less than asked and read as
    /// success, and the same bug in the other direction would grant more.
    pub fn parse(s: &str) -> Option<Self> {
        match s.to_ascii_lowercase().as_str() {
            "list" => Some(Self::List),
            "read" => Some(Self::Read),
            "write" => Some(Self::Write),
            "delete" => Some(Self::Delete),
            _ => None,
        }
    }
}

/// What a list does when it matches.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ListKind {
    /// Matching acts are permitted (subject to the base preset remaining the floor).
    Allow,
    /// Matching acts are refused.
    Deny,
}

/// A grant of verbs over a list to one subject.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ListGrant {
    /// `plugin_id`, or `role:constellation:*`, or `*` for every member.
    pub subject: String,
    pub perms: Vec<ListPerm>,
}

/// An operator-authored policy list.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolicyList {
    pub name: String,
    /// Stated in the operator's words. This is what gets published to the agent at launch,
    /// so it is law-as-written rather than a rule id — an agent that is told "rm must
    /// stand alone" complies; one that is told `deny-rule-17` learns only that a phrasing
    /// failed and tries another.
    pub description: String,
    pub kind: ListKind,
    /// Command/path patterns this list matches.
    pub entries: Vec<String>,
    /// Which agents this list governs: `plugin_id`, `role:constellation:*`, or `*`.
    /// Empty binds to nobody — a list is inert until an operator matches it to agents.
    #[serde(default)]
    pub bound_to: Vec<String>,
    /// Who may do what TO THE LIST ITSELF (distinct from what the list governs).
    #[serde(default)]
    pub grants: Vec<ListGrant>,
    /// `false` parks a list without deleting it — the operator equivalent of a comment.
    #[serde(default = "yes")]
    pub enabled: bool,
}

fn yes() -> bool {
    true
}

impl PolicyList {
    /// Does this list govern the given member?
    ///
    /// Binding is by explicit match only. There is deliberately no "applies to everything
    /// unless excluded" mode: a list that governs by default would silently widen its
    /// reach every time a member joined, which is the opposite of the transparency this
    /// exists for.
    pub fn governs(&self, plugin_id: &str, role_lct: &str) -> bool {
        self.enabled
            && self
                .bound_to
                .iter()
                .any(|b| b == "*" || b == plugin_id || b == role_lct)
    }

    /// May `subject` exercise `perm` on this list?
    ///
    /// Fails CLOSED: no matching grant means no. An absent grant is not a permissive
    /// default — that inversion is the single most common authorization defect, and this
    /// codebase has already shipped it once in the gate (absent signal read as allow).
    pub fn permits(&self, subject_plugin: &str, subject_role: &str, perm: ListPerm) -> bool {
        self.grants.iter().any(|g| {
            (g.subject == "*" || g.subject == subject_plugin || g.subject == subject_role)
                && g.perms.contains(&perm)
        })
    }

    /// The metadata view — what a holder of `List` (but not `Read`) may see.
    ///
    /// Entries are counted, never returned. This is the whole point of the verb split, and
    /// the place it would be easiest to leak by including "just the first few".
    pub fn metadata_only(&self) -> serde_json::Value {
        serde_json::json!({
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "enabled": self.enabled,
            "entry_count": self.entries.len(),
            "bound_to": self.bound_to,
        })
    }
}

/// All operator-authored lists, keyed by name. Lives in the vault (encrypted at rest,
/// decrypted into memory only) because it is consequential config, and consequential
/// config does not live in the environment.
pub type PolicyLists = HashMap<String, PolicyList>;

/// The lists governing one member, in binding order.
pub fn for_member<'a>(
    lists: &'a PolicyLists,
    plugin_id: &str,
    role_lct: &str,
) -> Vec<&'a PolicyList> {
    let mut v: Vec<&PolicyList> = lists
        .values()
        .filter(|l| l.governs(plugin_id, role_lct))
        .collect();
    // Deterministic order so the published law reads the same twice, and so a diff
    // between two sessions' law is a real change rather than map iteration order.
    v.sort_by(|a, b| a.name.cmp(&b.name));
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    fn list(name: &str, bound: &[&str], grants: Vec<ListGrant>) -> PolicyList {
        PolicyList {
            name: name.into(),
            description: "test".into(),
            kind: ListKind::Deny,
            entries: vec!["a".into(), "b".into()],
            bound_to: bound.iter().map(|s| s.to_string()).collect(),
            grants,
            enabled: true,
        }
    }

    #[test]
    fn list_permission_does_not_imply_read() {
        let l = list("x", &["*"], vec![ListGrant { subject: "codex".into(), perms: vec![ListPerm::List] }]);
        assert!(l.permits("codex", "role:constellation:member", ListPerm::List));
        assert!(!l.permits("codex", "role:constellation:member", ListPerm::Read),
                "List must not imply Read — that is the whole reason they are separate");
    }

    #[test]
    fn write_permission_does_not_imply_delete() {
        let l = list("x", &["*"], vec![ListGrant { subject: "codex".into(), perms: vec![ListPerm::Write] }]);
        assert!(l.permits("codex", "role:constellation:member", ListPerm::Write));
        assert!(!l.permits("codex", "role:constellation:member", ListPerm::Delete),
                "Delete is the only verb that destroys; it is never implied by Write");
    }

    #[test]
    fn absent_grant_fails_closed() {
        let l = list("x", &["*"], vec![]);
        for p in [ListPerm::List, ListPerm::Read, ListPerm::Write, ListPerm::Delete] {
            assert!(!l.permits("anyone", "role:constellation:member", p),
                    "no grant must mean NO, never a permissive default");
        }
    }

    #[test]
    fn metadata_view_never_carries_entries() {
        let l = list("x", &["*"], vec![]);
        let m = l.metadata_only().to_string();
        assert!(m.contains("entry_count"));
        assert!(!m.contains("\"a\""), "metadata view must not leak entry contents");
    }

    #[test]
    fn a_list_bound_to_nobody_governs_nobody() {
        let l = list("x", &[], vec![]);
        assert!(!l.governs("codex", "role:constellation:member"),
                "lists are inert until an operator binds them");
    }

    #[test]
    fn binding_matches_plugin_or_role_or_star() {
        assert!(list("x", &["codex"], vec![]).governs("codex", "role:constellation:member"));
        assert!(list("x", &["role:constellation:member"], vec![]).governs("kimi", "role:constellation:member"));
        assert!(list("x", &["*"], vec![]).governs("anyone", "role:constellation:x"));
        assert!(!list("x", &["codex"], vec![]).governs("kimi", "role:constellation:member"));
    }
}

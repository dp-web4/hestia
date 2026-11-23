//! Record which operator delegation, if any, covers an ordinary tool act (#1320).
//!
//! This is evidence, not a new permit path. `assess` never changes a verdict. Unrestricted and
//! role-only delegations do not acquire tool-act authority by implication: an operator must name
//! `act` explicitly. The acting member remains the session's A1 plugin identity, so the record
//! says which delegation covers that identity, not a stronger proof of who physically acted.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use uuid::Uuid;
use web4_core::crypto::PublicKey;
use web4_core::delegation::DelegatedAuthority;

use crate::delegation::{agent_key_for_lct, DelegationStore};

fn canonical_absolute(path: &str) -> Option<String> {
    if path != path.trim() {
        return None;
    }
    let path = path.trim();
    if !path.starts_with('/') || path.ends_with("//") {
        return None;
    }
    let path = path.trim_end_matches('/');
    if path.is_empty() {
        return Some("/".into());
    }
    if path.split('/').skip(1).any(|seg| seg.is_empty() || seg == "." || seg == "..") {
        return None;
    }
    Some(path.to_string())
}

fn path_within(target: &str, prefix: &str) -> bool {
    let Some(prefix) = canonical_absolute(prefix) else { return false };
    // Preserve the existing refusal to delegate an entire filesystem root as a path bound.
    if prefix == "/" {
        return false;
    }
    let Some(target) = canonical_absolute(target) else { return false };
    target == prefix || target.starts_with(&format!("{prefix}/"))
}

const PATH_CATEGORIES: &[&str] = &["file_read", "file_write"];

pub fn act_covers(action: &str, tool_name: &str, category: &str, target: Option<&str>) -> bool {
    let action = action.trim();
    if action == "act" {
        return true;
    }
    let Some(rest) = action.strip_prefix("act:") else {
        return false;
    };
    let (selector, bound) = match rest.split_once(':') {
        Some((selector, bound)) => (selector.trim(), Some(bound)),
        None => (rest.trim(), None),
    };
    if selector.is_empty() {
        return false;
    }
    if selector != "*" && selector != category && selector != tool_name {
        return false;
    }
    match bound {
        None => true,
        Some(prefix) => {
            PATH_CATEGORIES.contains(&category) && target.is_some_and(|t| path_within(t, prefix))
        }
    }
}

#[derive(Debug, Default)]
pub struct Snapshot {
    pub store: Option<DelegationStore>,
    pub store_error: Option<String>,
    pub operator_key: Option<PublicKey>,
    pub operator_key_error: Option<String>,
    pub member_lcts: HashMap<String, String>,
    pub role_lcts: HashMap<String, String>,
}

impl Snapshot {
    pub fn build(
        vault: &crate::vault::Vault,
        home: &std::path::Path,
        members: &crate::member_registry::MemberRegistry,
        roles: &web4_core::RoleRegistry,
    ) -> Self {
        let mut snap = Self::default();
        match DelegationStore::load(vault) {
            Ok(store) => snap.store = Some(store),
            Err(e) => snap.store_error = Some(format!("{e:#}")),
        }
        match crate::delegation::operator_delegator(vault, home) {
            Ok((_, kp)) => snap.operator_key = Some(kp.verifying_key()),
            Err(e) => snap.operator_key_error = Some(format!("{e:#}")),
        }
        for (id, lct) in members.iter_sorted() {
            snap.member_lcts.insert(id.clone(), lct.lct_id());
        }
        for label in roles.labels() {
            if let Some(role) = roles.get(label) {
                snap.role_lcts.insert(label.to_string(), role.lct.lct_id());
            }
        }
        snap
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Match,
    None,
    Unkeyed,
    Uncovered,
    Expired,
    Revoked,
    InvalidSignature,
    Unavailable,
}

impl Status {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Match => "match",
            Self::None => "none",
            Self::Unkeyed => "unkeyed",
            Self::Uncovered => "uncovered",
            Self::Expired => "expired",
            Self::Revoked => "revoked",
            Self::InvalidSignature => "invalid_signature",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Act<'a> {
    pub plugin_id: &'a str,
    pub role: &'a str,
    pub tool_name: &'a str,
    pub category: &'a str,
    pub target: Option<&'a str>,
}

#[derive(Debug, Clone)]
pub struct Finding {
    pub status: Status,
    pub member_lct: Option<String>,
    pub member_key: Option<Uuid>,
    pub role_key: Option<Uuid>,
    pub delegation_ids: Vec<String>,
    pub delegator_lct: Option<String>,
    pub matched_via: Option<&'static str>,
    pub matched_action: Option<String>,
    pub coverage_basis: Option<&'static str>,
    pub coverage_uncertainty: Option<&'static str>,
    pub detail: Option<String>,
}

impl Finding {
    pub fn to_json(&self, assessed_by: &str) -> Value {
        json!({
            "mode": "record",
            "status": self.status.as_str(),
            "assessed_by": assessed_by,
            "member_lct": self.member_lct,
            "agent_key": self.member_key.map(|k| k.to_string()),
            "role_agent_key": self.role_key.map(|k| k.to_string()),
            "delegation_ids": self.delegation_ids,
            "delegator_lct": self.delegator_lct,
            "matched_via": self.matched_via,
            "matched_action": self.matched_action,
            "coverage_basis": self.coverage_basis,
            "coverage_uncertainty": self.coverage_uncertainty,
            "detail": self.detail,
            "verdict_changed": false,
        })
    }
}

pub fn assess(snap: &Snapshot, act: &Act, now: DateTime<Utc>) -> Finding {
    let member_lct = snap.member_lcts.get(act.plugin_id).cloned();
    let member_key = member_lct.as_deref().map(agent_key_for_lct);
    let role_key = snap.role_lcts.get(act.role).map(|l| agent_key_for_lct(l));
    let mut finding = Finding {
        status: Status::None,
        member_lct,
        member_key,
        role_key,
        delegation_ids: Vec::new(),
        delegator_lct: None,
        matched_via: None,
        matched_action: None,
        coverage_basis: None,
        coverage_uncertainty: None,
        detail: None,
    };
    let Some(store) = snap.store.as_ref() else {
        finding.status = Status::Unavailable;
        finding.detail = snap.store_error.clone();
        return finding;
    };
    if member_key.is_none() && role_key.is_none() {
        finding.status = Status::Unkeyed;
        return finding;
    }
    let via = |d: &DelegatedAuthority| -> Option<&'static str> {
        if Some(d.agent_lct_id) == member_key {
            Some("member")
        } else if Some(d.agent_lct_id) == role_key {
            Some("role")
        } else {
            None
        }
    };
    let mine: Vec<&DelegatedAuthority> =
        store.delegations.iter().filter(|d| via(d).is_some()).collect();
    if mine.is_empty() {
        finding.status = if member_key.is_none() { Status::Unkeyed } else { Status::None };
        return finding;
    }
    let covering_action = |d: &DelegatedAuthority| -> Option<String> {
        d.scope
            .actions
            .iter()
            .find(|a| act_covers(a, act.tool_name, act.category, act.target))
            .cloned()
    };
    let covering: Vec<(&DelegatedAuthority, String)> =
        mine.iter().filter_map(|d| covering_action(d).map(|a| (*d, a))).collect();
    if covering.is_empty() {
        finding.status = Status::Uncovered;
        finding.delegation_ids = mine.iter().map(|d| d.id.to_string()).collect();
        finding.detail = Some(if mine.iter().any(|d| d.scope.actions.is_empty()) {
            "an unrestricted or role-only delegation does not cover tool acts; re-grant naming `act`"
                .into()
        } else {
            "no `act…` action in their scopes covers this tool, category or path".into()
        });
        return finding;
    }
    let is_expired = |d: &DelegatedAuthority| d.expires_at.is_some_and(|e| now >= e);
    let mut matches = Vec::new();
    let mut invalid = Vec::new();
    let mut revoked = Vec::new();
    let mut expired = Vec::new();
    for (d, action) in &covering {
        if d.revoked {
            revoked.push(*d);
        } else if is_expired(d) {
            expired.push(*d);
        } else {
            match snap.operator_key.as_ref() {
                Some(pk) if d.verify(pk).is_ok() => matches.push((*d, action.clone())),
                _ => invalid.push(*d),
            }
        }
    }
    matches.sort_by_key(|(d, _)| match via(d) {
        Some("member") => 0,
        Some("role") => 1,
        _ => 2,
    });
    if let Some((first, action)) = matches.first() {
        finding.status = Status::Match;
        finding.delegation_ids = matches.iter().map(|(d, _)| d.id.to_string()).collect();
        finding.delegator_lct = Some(first.delegator_lct_id.to_string());
        finding.matched_via = via(first);
        finding.matched_action = Some(action.clone());
        finding.coverage_basis = Some("operator-signed act scope matched to the A1 session identity");
        finding.coverage_uncertainty = Some(
            "strict lexical absolute-path comparison; filesystem aliases and the physical actor are not verified",
        );
        finding.detail = Some(
            "record only: the named action covers this act; this is not authorization or proof of the physical actor".into(),
        );
        return finding;
    }
    let (status, closest) = if !invalid.is_empty() {
        if snap.operator_key.is_none() {
            finding.detail = Some(format!(
                "no operator key to verify against: {}",
                snap.operator_key_error.clone().unwrap_or_default()
            ));
        }
        (Status::InvalidSignature, invalid)
    } else if !revoked.is_empty() {
        (Status::Revoked, revoked)
    } else {
        (Status::Expired, expired)
    };
    finding.status = status;
    finding.delegation_ids = closest.iter().map(|d| d.id.to_string()).collect();
    finding.delegator_lct = closest.first().map(|d| d.delegator_lct_id.to_string());
    finding
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_core::crypto::KeyPair;

    struct Fx {
        snap: Snapshot,
        op: KeyPair,
        key: Uuid,
    }

    fn fx() -> Fx {
        let op = KeyPair::generate();
        let mut snap = Snapshot::default();
        snap.store = Some(DelegationStore::default());
        snap.operator_key = Some(op.verifying_key());
        snap.member_lcts.insert("codex".into(), "lct:web4:mb32:codex".into());
        snap.role_lcts.insert("role:worker".into(), "lct:web4:mb32:role-worker".into());
        let key = agent_key_for_lct("lct:web4:mb32:codex");
        Fx { snap, op, key }
    }

    fn grant(fx: &mut Fx, actions: &[&str], hours: Option<u64>, signer: Option<&KeyPair>) -> String {
        let store = fx.snap.store.as_mut().unwrap();
        let signer = signer.unwrap_or(&fx.op);
        store
            .create_delegation(
                Uuid::new_v4(),
                fx.key,
                vec![],
                actions.iter().map(|s| s.to_string()).collect(),
                hours,
                signer,
            )
            .id
            .to_string()
    }

    fn act<'a>(tool: &'a str, category: &'a str, target: Option<&'a str>) -> Act<'a> {
        Act { plugin_id: "codex", role: "role:worker", tool_name: tool, category, target }
    }

    #[test]
    fn vocabulary_covers_only_named_acts_and_clean_path_bounds() {
        let c = act_covers;
        assert!(c("act", "Bash", "command", Some("ls")));
        assert!(c("act:*", "Bash", "command", Some("ls")));
        assert!(c("act:command", "Bash", "command", Some("ls")));
        assert!(c("act:Bash", "Bash", "command", Some("ls")));
        assert!(!c("act:Bash", "Shell", "command", Some("ls")));
        assert!(!c("scope.decide", "Bash", "command", Some("ls")));
        assert!(c("act:file_write:/w", "Write", "file_write", Some("/w/x")));
        assert!(c("act:file_write:/w/", "Write", "file_write", Some("/w/x")));
        assert!(c("act:*:/w", "Read", "file_read", Some("/w")));
        assert!(!c("act:file_write:/w", "Write", "file_write", Some("/wx/a")));
        assert!(!c("act:file_write:/w", "Write", "file_write", Some("/w/../etc/passwd")));
        assert!(!c("act:file_write:/w", "Write", "file_write", Some("/w//etc/passwd")));
        assert!(!c("act:file_write:/w//", "Write", "file_write", Some("/w/etc/passwd")));
        assert!(!c("act:file_write:/w/../etc", "Write", "file_write", Some("/w/../etc/passwd")));
        assert!(!c("act:file_write:/w/./", "Write", "file_write", Some("/w/etc/passwd")));
        assert!(!c("act:file_write:/w", "Write", "file_write", Some("/w/etc/passwd ")));
        assert!(!c("act:file_write:/w", "Write", "file_write", Some("relative")));
        assert!(!c("act:*:/usr", "Bash", "command", Some("/usr/bin/rm -rf /")));
    }

    #[test]
    fn valid_covering_delegation_records_match_without_changing_the_verdict() {
        let mut f = fx();
        let id = grant(&mut f, &["act:command"], Some(2), None);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::Match);
        assert_eq!(r.delegation_ids, vec![id]);
        assert_eq!(r.matched_via, Some("member"));
        let j = r.to_json("query_policy");
        assert_eq!(j["mode"], "record");
        assert_eq!(j["verdict_changed"], false);
        assert!(j["coverage_basis"].as_str().unwrap().contains("A1 session identity"));
        assert!(j["coverage_uncertainty"].as_str().unwrap().contains("lexical"));
        assert!(j["coverage_uncertainty"].as_str().unwrap().contains("physical actor"));
        assert!(j["detail"].as_str().unwrap().contains("not authorization"));
    }

    #[test]
    fn role_keyed_delegation_matches_via_role() {
        let mut f = fx();
        let role_key = agent_key_for_lct("lct:web4:mb32:role-worker");
        f.snap.store.as_mut().unwrap().create_delegation(
            Uuid::new_v4(), role_key, vec![], vec!["act".into()], None, &f.op,
        );
        let r = assess(&f.snap, &act("Read", "file_read", Some("/x")), Utc::now());
        assert_eq!((r.status, r.matched_via), (Status::Match, Some("role")));
    }

    #[test]
    fn role_only_unrestricted_scope_does_not_acquire_tool_act_coverage() {
        let mut f = fx();
        let role_key = agent_key_for_lct("lct:web4:mb32:role-worker");
        f.snap.store.as_mut().unwrap().create_delegation(
            Uuid::new_v4(), role_key, vec![], vec![], None, &f.op,
        );
        let r = assess(&f.snap, &act("Read", "file_read", Some("/x")), Utc::now());
        assert_eq!(r.status, Status::Uncovered);
        assert!(r.detail.unwrap().contains("unrestricted"));
    }

    #[test]
    fn member_coverage_precedes_role_coverage_regardless_of_grant_order() {
        let mut f = fx();
        let role_key = agent_key_for_lct("lct:web4:mb32:role-worker");
        let role_id = f.snap.store.as_mut().unwrap().create_delegation(
            Uuid::new_v4(), role_key, vec![], vec!["act".into()], None, &f.op,
        ).id.to_string();
        let member_id = grant(&mut f, &["act"], None, None);
        let r = assess(&f.snap, &act("Read", "file_read", Some("/x")), Utc::now());
        assert_eq!(r.matched_via, Some("member"));
        assert_eq!(r.delegation_ids.first(), Some(&member_id));
        assert!(r.delegation_ids.contains(&role_id));
    }

    #[test]
    fn exact_expiry_is_closed_and_valid_overlap_wins_over_revoked() {
        let mut f = fx();
        let expired_id = grant(&mut f, &["act"], Some(1), None);
        let expires_at = f.snap.store.as_ref().unwrap().delegations.iter()
            .find(|d| d.id.to_string() == expired_id).unwrap().expires_at.unwrap();
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), expires_at);
        assert_eq!(r.status, Status::Expired);

        let valid_id = grant(&mut f, &["act"], None, None);
        f.snap.store.as_mut().unwrap().revoke(Uuid::parse_str(&expired_id).unwrap()).unwrap();
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::Match);
        assert_eq!(r.delegation_ids, vec![valid_id]);
    }

    #[test]
    fn absence_and_unrestricted_records_are_not_silent_authority() {
        let f = fx();
        assert_eq!(assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now()).status, Status::None);
        let mut f = fx();
        grant(&mut f, &[], None, None);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::Uncovered);
        assert!(r.detail.unwrap().contains("unrestricted"));
    }

    #[test]
    fn expired_revoked_and_foreign_signature_are_distinct() {
        let mut f = fx();
        grant(&mut f, &["act"], Some(1), None);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now() + chrono::Duration::hours(2));
        assert_eq!(r.status, Status::Expired);
        let mut f = fx();
        let id = grant(&mut f, &["act"], None, None);
        f.snap.store.as_mut().unwrap().revoke(Uuid::parse_str(&id).unwrap()).unwrap();
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!((r.status, r.delegation_ids), (Status::Revoked, vec![id]));
        let mut f = fx();
        let stranger = KeyPair::generate();
        grant(&mut f, &["act"], None, Some(&stranger));
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::InvalidSignature);
        let good = grant(&mut f, &["act"], None, None);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!((r.status, r.delegation_ids), (Status::Match, vec![good]));
    }

    #[test]
    fn unkeyed_and_unavailable_do_not_read_as_none() {
        let f = fx();
        let ghost = Act { plugin_id: "ghost", role: "role:none", tool_name: "Bash", category: "command", target: None };
        assert_eq!(assess(&f.snap, &ghost, Utc::now()).status, Status::Unkeyed);
        let mut f = fx();
        f.snap.store = None;
        f.snap.store_error = Some("unreadable store".into());
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::Unavailable);
        assert_eq!(r.detail.as_deref(), Some("unreadable store"));
    }
}

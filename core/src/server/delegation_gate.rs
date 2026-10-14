//! DELEGATION ON THE TOOL-CALL DECISION PATH — "under whose authority does this agent act?"
//!
//! Before this module the README and the web4 NIST crosswalk said delegation was *measured —
//! scoped by role+action, signed, revocable*, and the delegation store was consulted by exactly
//! one surface: delegated scope arbitration (`scope.decide:…`, #952). Every ordinary tool call a
//! seat made was decided by law (society / role / instance / operator grant / hub law) and
//! nothing on that path asked which operator delegation, if any, authorised the member to act at
//! all. A comparison with an external gate (2026-10-14) showed neither gate answers that question
//! from evidence. This module is the smallest credible answer:
//!
//! 1. **Look up** — at decision time, daemon side, resolve the acting member's registry LCT (and
//!    its constellation role's LCT), derive the delegation keys exactly as `hestia delegate
//!    agent-id` does ([`crate::delegation::agent_key_for_lct`]), and find the delegations whose
//!    agent is either key and whose scope covers THIS act ([`act_covers`]).
//! 2. **Classify** — unexpired, not revoked, signature verified against THIS box's operator key
//!    ([`crate::delegation::operator_delegator`], the same key every `delegate grant` signs with).
//! 3. **Record** — every decision row (`policy_decision`, and the `policy_allow` the gate's
//!    witness writes for permits) carries a `delegation` object: mode, status, delegation id(s),
//!    delegator LCT. That is what makes "under whose authority" answerable from the chain.
//! 4. **Enforce, only if the operator says so** — [`GateMode`] is `off | record | enforce`,
//!    default `record`, held in a vault document only the operator CLI writes. In `record` the
//!    finding is evidence and changes no verdict, so a live seat is not newly denied anything.
//!
//! THE SCOPE VOCABULARY (the `actions` strings of a `DelegationScope`). The action vocabulary is
//! open by design (#1110); this module interprets one new verb family, `act`:
//!
//! | action                          | covers                                                    |
//! |---------------------------------|-----------------------------------------------------------|
//! | `act`                           | every tool act                                            |
//! | `act:*`                         | every tool act (explicit spelling)                        |
//! | `act:<category>`                | acts whose daemon category (`policy::classify`) matches   |
//! | `act:<ToolName>`                | acts of that exact tool name                              |
//! | `act:<category\|Tool\|*>:/abs/p` | the above, AND the target is a path within `/abs/p`       |
//!
//! Categories are the daemon's own: `command`, `file_read`, `file_write`, `network`,
//! `task_management`, `credential_access`, `witness_append`, `unknown`. A path bound only binds
//! path-shaped acts (`file_read` / `file_write`): a shell command's target is the command text,
//! and `/usr/bin/rm -rf /` must never read as "a path under /usr". Containment is the
//! separator-anchored rule `scope.decide` uses (`/w` covers `/w/x`, never `/wx`), and a target
//! carrying a `.` or `..` segment is covered by no bound, because lexical containment of an
//! unnormalised path is not containment.
//!
//! WHAT DOES NOT COVER AN ACT, deliberately (the #952 rule: a dormant record must not gain
//! authority by a later release):
//! * an UNRESTRICTED delegation (empty roles and empty actions). web4-core reads that as "all
//!   actions"; every such record on a live box was minted before this verb existed, and none of
//!   its delegators could have meant "and may run any tool". It is reported as `uncovered`, with
//!   a note, so the operator sees it and can re-grant naming `act`.
//! * a ROLE-only delegation (`--role administrator`). Society roles and constellation roles are
//!   different vocabularies; nothing maps one onto the other yet.
//! * a `scope.decide…` action. That is authority to RULE on someone else's reach, not to act.
//!
//! ASSURANCE (A1, stated rather than implied). The member's identity is the session's
//! `plugin_id`, which `hestia_connect` asserts and does not prove (#63/#128). So this records
//! "the delegation that covers the member this session CLAIMS to be". That is still the first
//! time the chain names an authority for an ordinary act, and it composes with the transport
//! binding work that will make the claim proven.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex as StdMutex};

use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use uuid::Uuid;
use web4_core::crypto::PublicKey;
use web4_core::delegation::DelegatedAuthority;

use crate::delegation::{agent_key_for_lct, DelegationStore};

/// Vault namespace + document name of the mode. Read with `get_document` ONLY — no legacy
/// plaintext sidecar fallback, because a sidecar is a file a same-UID member could write.
pub const MODE_NS: &str = "presence";
pub const MODE_DOC: &str = "delegation-gate";

/// The verb this module interprets.
pub const ACTION_ACT: &str = "act";

/// How the delegation check participates in a decision. Operator-only: see [`load_mode`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GateMode {
    /// Not consulted. Rows say so (`status: not_checked`), so "off" is never mistaken for
    /// "checked and found nothing".
    Off,
    /// Consulted and recorded on every decision row; never changes a verdict. THE DEFAULT.
    Record,
    /// Consulted, recorded, and an act with no covering valid delegation is denied.
    Enforce,
}

impl GateMode {
    pub fn parse(s: &str) -> Option<Self> {
        match s.trim() {
            "off" => Some(Self::Off),
            "record" => Some(Self::Record),
            "enforce" => Some(Self::Enforce),
            _ => None,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Off => "off",
            Self::Record => "record",
            Self::Enforce => "enforce",
        }
    }
}

/// The mode as stored in the vault. Absent document = [`GateMode::Record`] (the default).
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ModeDoc {
    pub mode: String,
    pub set_at: DateTime<Utc>,
    #[serde(default)]
    pub reason: Option<String>,
}

/// Read the mode from the vault. `Ok(None)` = no document (default applies). A document that
/// is present and does not parse is an `Err`, never a silent default: an operator who set
/// `enforce` and typo'd the store must not be quietly running `record`.
pub fn load_mode(vault: &crate::vault::Vault) -> anyhow::Result<Option<ModeDoc>> {
    let Some(bytes) = vault.get_document(MODE_NS, MODE_DOC) else {
        return Ok(None);
    };
    let doc: ModeDoc = serde_json::from_slice(bytes)
        .map_err(|e| anyhow::anyhow!("delegation-gate mode document unreadable: {e}"))?;
    if GateMode::parse(&doc.mode).is_none() {
        anyhow::bail!("delegation-gate mode document names unknown mode '{}'", doc.mode);
    }
    Ok(Some(doc))
}

/// Write the mode. Called from the operator CLI (`hestia delegate mode`), which opens the vault
/// with the operator's passphrase. No MCP tool reaches this.
pub fn save_mode(
    vault: &mut crate::vault::Vault,
    mode: GateMode,
    reason: Option<String>,
) -> anyhow::Result<()> {
    let doc = ModeDoc { mode: mode.as_str().to_string(), set_at: Utc::now(), reason };
    vault
        .put_document(MODE_NS, MODE_DOC, serde_json::to_vec(&doc)?)
        .map_err(|e| anyhow::anyhow!("saving delegation-gate mode: {e}"))?;
    Ok(())
}

// ------------------------------------------------------------------------------ vocabulary

/// Is `target` a path within `prefix`, separator-anchored and lexically clean?
fn path_within(target: &str, prefix: &str) -> bool {
    let prefix = prefix.trim().trim_end_matches('/');
    if prefix.is_empty() || !prefix.starts_with('/') {
        return false;
    }
    if !target.starts_with('/') {
        return false;
    }
    if target.split('/').any(|seg| seg == "." || seg == "..") {
        return false;
    }
    let t = target.trim_end_matches('/');
    t == prefix || t.starts_with(&format!("{prefix}/"))
}

/// Categories whose `target` is a filesystem path, so a path bound can mean something.
const PATH_CATEGORIES: &[&str] = &["file_read", "file_write"];

/// Does the delegated action string cover a tool act? See the module docs for the grammar.
pub fn act_covers(action: &str, tool_name: &str, category: &str, target: Option<&str>) -> bool {
    let action = action.trim();
    if action == ACTION_ACT {
        return true;
    }
    let Some(rest) = action.strip_prefix("act:") else {
        return false;
    };
    let (sel, bound) = match rest.split_once(':') {
        Some((s, b)) => (s.trim(), Some(b)),
        None => (rest.trim(), None),
    };
    if sel.is_empty() {
        return false;
    }
    let sel_ok = sel == "*" || sel == category || sel == tool_name;
    if !sel_ok {
        return false;
    }
    match bound {
        None => true,
        Some(prefix) => {
            PATH_CATEGORIES.contains(&category) && target.is_some_and(|t| path_within(t, prefix))
        }
    }
}

/// How an `act` action string reads, for the grant doors (#1110: refuse what binds nothing).
/// `None` = not an `act` action at all.
pub fn act_shape_problem(action: &str) -> Option<Option<String>> {
    let action = action.trim();
    if action == ACTION_ACT {
        return Some(None);
    }
    let rest = action.strip_prefix("act:")?;
    let (sel, bound) = match rest.split_once(':') {
        Some((s, b)) => (s.trim(), Some(b.trim())),
        None => (rest.trim(), None),
    };
    if sel.is_empty() {
        return Some(Some(format!(
            "`{action}` has an empty selector, so it binds nothing. Write `act` for every act, \
             `act:<category>` or `act:<ToolName>` for a kind of act"
        )));
    }
    if let Some(b) = bound {
        let p = b.trim_end_matches('/');
        if p.is_empty() || !p.starts_with('/') {
            return Some(Some(format!(
                "`{action}` has an empty or relative path bound, which binds nothing; the bound \
                 must be absolute"
            )));
        }
        if !(sel == "*" || PATH_CATEGORIES.contains(&sel)) {
            return Some(Some(format!(
                "`{action}` bounds a non-path selector by a path; a path bound only binds \
                 file_read / file_write acts (or `*`, which then covers only those). Drop the \
                 bound, or use `act:file_read:{p}` / `act:file_write:{p}`"
            )));
        }
    }
    Some(None)
}

// ------------------------------------------------------------------------------- snapshot

/// Everything delegation-related, read from the ON-DISK vault (so a `hestia delegate grant` the
/// CLI wrote after the daemon started is seen without a restart, as #952 requires).
#[derive(Debug, Default)]
pub struct Snapshot {
    pub mode: Option<GateMode>,
    /// The stored document behind `mode` (when and why it was set), for the transition witness.
    pub mode_doc: Option<ModeDoc>,
    /// Why the mode could not be read, if it could not. Treated as the strictest reading the
    /// operator could have meant: see [`Snapshot::effective_mode`].
    pub mode_error: Option<String>,
    pub store: Option<DelegationStore>,
    pub store_error: Option<String>,
    pub operator_key: Option<PublicKey>,
    pub operator_key_error: Option<String>,
    /// plugin_id -> registry LCT id.
    pub member_lcts: HashMap<String, String>,
    /// constellation role label -> role LCT id.
    pub role_lcts: HashMap<String, String>,
    pub loaded_at: Option<DateTime<Utc>>,
}

impl Snapshot {
    /// The mode in force. Absent document = `record`. A document that exists and cannot be read
    /// is ALSO `record`, not `enforce`: the operator may have meant `off`, and reading an
    /// unreadable document as `enforce` would be a new outage on every seat. `record` never
    /// changes a verdict, and every row then carries `mode_error`, so the fault is visible on
    /// each decision rather than silently defaulted. (A decision dp may want to revisit: see PR.)
    pub fn effective_mode(&self) -> GateMode {
        self.mode.unwrap_or(GateMode::Record)
    }

    /// Build from a freshly opened vault.
    pub fn from_vault(vault: &crate::vault::Vault, home: &std::path::Path) -> Self {
        let mut s = Snapshot { loaded_at: Some(Utc::now()), ..Default::default() };
        match load_mode(vault) {
            Ok(Some(doc)) => {
                s.mode = GateMode::parse(&doc.mode);
                s.mode_doc = Some(doc);
            }
            Ok(None) => {}
            Err(e) => s.mode_error = Some(format!("{e:#}")),
        }
        match DelegationStore::load(vault) {
            Ok(st) => s.store = Some(st),
            Err(e) => s.store_error = Some(format!("{e:#}")),
        }
        match crate::delegation::operator_delegator(vault, home) {
            Ok((_, kp)) => s.operator_key = Some(kp.verifying_key()),
            Err(e) => s.operator_key_error = Some(format!("{e:#}")),
        }
        let reg = crate::member_registry::load_members(vault);
        for (id, lct) in reg.iter_sorted() {
            s.member_lcts.insert(id.clone(), lct.lct_id());
        }
        s.role_lcts = crate::role_registry::persisted_role_lct_ids(vault);
        s
    }

    fn unavailable(why: String) -> Self {
        Snapshot { store_error: Some(why), loaded_at: Some(Utc::now()), ..Default::default() }
    }
}

/// What identifies the on-disk inputs, so the snapshot is rebuilt only when one changed.
/// The vault is saved by atomic rename, so the inode moves on every save (unix).
#[derive(Debug, Clone, PartialEq, Eq)]
struct Fingerprint {
    vault: Option<(std::time::SystemTime, u64, u64)>,
    operator_key: Option<(std::time::SystemTime, u64, u64)>,
}

fn file_fp(p: &std::path::Path) -> Option<(std::time::SystemTime, u64, u64)> {
    let m = std::fs::metadata(p).ok()?;
    #[cfg(unix)]
    let ino = std::os::unix::fs::MetadataExt::ino(&m);
    #[cfg(not(unix))]
    let ino = 0u64;
    Some((m.modified().ok()?, m.len(), ino))
}

/// The daemon's handle: where the vault is and how to open it, plus the cached snapshot. Shared
/// by the state and the lock-free publication, so the decision path reads it without the state
/// lock.
pub struct DelegationGate {
    vault_path: PathBuf,
    passphrase: zeroize::Zeroizing<String>,
    home: PathBuf,
    cache: StdMutex<Option<(Fingerprint, Arc<Snapshot>)>>,
    /// The mode this daemon last WITNESSED (see [`DelegationGate::mode_transition`]).
    witnessed_mode: StdMutex<Option<GateMode>>,
}

impl std::fmt::Debug for DelegationGate {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DelegationGate").field("vault_path", &self.vault_path).finish()
    }
}

impl DelegationGate {
    pub fn new(vault_path: PathBuf, passphrase: &str, home: PathBuf) -> Self {
        Self {
            vault_path,
            passphrase: zeroize::Zeroizing::new(passphrase.to_string()),
            home,
            cache: StdMutex::new(None),
            witnessed_mode: StdMutex::new(None),
        }
    }

    /// The mode is set by the operator CLI writing the vault directly, which leaves no chain row
    /// of its own. So the daemon witnesses the mode it OBSERVES: the first decision after a
    /// start, and the first decision after any change, gets back `Some(event_data)` for a
    /// `delegation_gate_mode` row, appended (by the caller, under the state lock) BEFORE that
    /// decision's own row. Every decision row also names its mode, so the record is complete
    /// either way; this row makes the change itself findable without scanning decisions.
    pub fn mode_transition(&self, snap: &Snapshot) -> Option<Value> {
        let now = snap.effective_mode();
        let mut g = match self.witnessed_mode.lock() {
            Ok(g) => g,
            Err(p) => p.into_inner(),
        };
        if *g == Some(now) {
            return None;
        }
        let from = g.map(|m| m.as_str());
        *g = Some(now);
        Some(json!({
            "from": from,
            "to": now.as_str(),
            "explicit": snap.mode_doc.is_some(),
            "set_at": snap.mode_doc.as_ref().map(|d| d.set_at),
            "reason": snap.mode_doc.as_ref().and_then(|d| d.reason.clone()),
            "mode_error": snap.mode_error,
            "observed_by": "query_policy",
            "note": if from.is_none() { "first observation since daemon start" } else { "mode changed" },
        }))
    }

    /// The current snapshot. A `stat` of two files on the hot path; a vault re-open (one KDF)
    /// only when the vault or the operator key changed on disk since the last read. Held under
    /// the cache mutex so concurrent decisions after a change re-open once, not once each.
    pub fn snapshot(&self) -> Arc<Snapshot> {
        let fp = Fingerprint {
            vault: file_fp(&self.vault_path),
            operator_key: file_fp(&self.home.join("operator.key")),
        };
        let mut guard = match self.cache.lock() {
            Ok(g) => g,
            Err(p) => p.into_inner(),
        };
        if let Some((cached_fp, snap)) = guard.as_ref() {
            if *cached_fp == fp && fp.vault.is_some() {
                return snap.clone();
            }
        }
        let snap = Arc::new(
            match crate::vault::Vault::open(self.vault_path.clone(), (*self.passphrase).clone()) {
                Ok(v) => Snapshot::from_vault(&v, &self.home),
                Err(e) => Snapshot::unavailable(format!("cannot re-read the vault from disk: {e}")),
            },
        );
        *guard = Some((fp, snap.clone()));
        snap
    }
}

// ------------------------------------------------------------------------------ assessment

/// The outcome of the lookup, as recorded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    /// Mode `off`: not consulted.
    NotChecked,
    /// A valid (unexpired, unrevoked, operator-signed) delegation covers this act.
    Match,
    /// No delegation names this member (or its role) at all.
    None,
    /// The member has no registry LCT, so no delegation can be keyed to it.
    Unkeyed,
    /// Delegations name this member, but none of their scopes covers this act.
    Uncovered,
    /// Only expired delegations cover this act.
    Expired,
    /// Only revoked delegations cover this act.
    Revoked,
    /// A covering delegation exists whose signature does not verify against this box's
    /// operator key (or there is no operator key to verify it against).
    InvalidSignature,
    /// The store could not be read.
    Unavailable,
}

impl Status {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::NotChecked => "not_checked",
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

    /// The deny rule id this status carries in `enforce`. `None` for a match / not checked.
    pub fn rule_id(self) -> Option<&'static str> {
        match self {
            Self::NotChecked | Self::Match => None,
            Self::None | Self::Unkeyed => Some("delegation.absent"),
            Self::Uncovered => Some("delegation.uncovered"),
            Self::Expired => Some("delegation.expired"),
            Self::Revoked => Some("delegation.revoked"),
            Self::InvalidSignature => Some("delegation.invalid_signature"),
            Self::Unavailable => Some("delegation.unavailable"),
        }
    }
}

/// The act being decided, in the terms the vocabulary speaks.
#[derive(Debug, Clone, Copy)]
pub struct Act<'a> {
    pub plugin_id: &'a str,
    pub role: &'a str,
    pub tool_name: &'a str,
    pub category: &'a str,
    pub target: Option<&'a str>,
}

/// One assessment, ready to record.
#[derive(Debug, Clone)]
pub struct Finding {
    pub mode: GateMode,
    pub status: Status,
    pub member_lct: Option<String>,
    pub member_key: Option<Uuid>,
    pub role_key: Option<Uuid>,
    /// The deciding delegation(s): the matches, or the closest non-matches for the status.
    pub delegation_ids: Vec<String>,
    pub delegator_lct: Option<String>,
    pub matched_via: Option<&'static str>,
    pub matched_action: Option<String>,
    pub detail: Option<String>,
    pub mode_error: Option<String>,
}

impl Finding {
    /// The `delegation` object every decision row carries.
    pub fn to_json(&self, assessed_by: &str) -> Value {
        let mut v = json!({
            "mode": self.mode.as_str(),
            "status": self.status.as_str(),
            "assessed_by": assessed_by,
        });
        let o = v.as_object_mut().expect("object");
        if self.status != Status::NotChecked {
            o.insert("member_lct".into(), json!(self.member_lct));
            o.insert("agent_key".into(), json!(self.member_key.map(|k| k.to_string())));
            o.insert("role_agent_key".into(), json!(self.role_key.map(|k| k.to_string())));
            o.insert("delegation_ids".into(), json!(self.delegation_ids));
            o.insert("delegator_lct".into(), json!(self.delegator_lct));
        }
        if let Some(m) = self.matched_via {
            o.insert("matched_via".into(), json!(m));
        }
        if let Some(a) = &self.matched_action {
            o.insert("matched_action".into(), json!(a));
        }
        if let Some(d) = &self.detail {
            o.insert("detail".into(), json!(d));
        }
        if let Some(e) = &self.mode_error {
            o.insert("mode_error".into(), json!(e));
        }
        if let Some(r) = self.enforced_rule() {
            o.insert("enforced_rule".into(), json!(r));
        }
        v
    }

    /// The deny rule, when this finding denies (mode `enforce` and no match).
    pub fn enforced_rule(&self) -> Option<&'static str> {
        if self.mode == GateMode::Enforce {
            self.status.rule_id()
        } else {
            None
        }
    }

    /// The deny reason, with its remedy (every deny says why AND what to do).
    pub fn deny_reason(&self, act: &Act) -> Option<String> {
        let rule = self.enforced_rule()?;
        let key = self
            .member_key
            .map(|k| k.to_string())
            .unwrap_or_else(|| format!("$(hestia delegate agent-id {})", act.plugin_id));
        let grant = format!(
            "hestia delegate grant {key} --action 'act:{}' --expires <hours>",
            act.category
        );
        let why = match self.status {
            Status::None => format!(
                "no operator delegation names '{}' as its agent, and this society runs \
                 delegation in ENFORCE mode: no act runs without a named authority",
                act.plugin_id
            ),
            Status::Unkeyed => format!(
                "'{}' has no LCT in this society's member registry, so no delegation can be keyed \
                 to it (a delegation binds to a key-derived identity, never a name)",
                act.plugin_id
            ),
            Status::Uncovered => format!(
                "'{}' holds delegation(s) {}, but none covers a `{}` act ({}){}",
                act.plugin_id,
                self.delegation_ids.join(", "),
                act.category,
                act.tool_name,
                self.detail.as_deref().map(|d| format!(" — {d}")).unwrap_or_default()
            ),
            Status::Expired => format!(
                "the delegation covering this act ({}) has EXPIRED",
                self.delegation_ids.join(", ")
            ),
            Status::Revoked => format!(
                "the delegation covering this act ({}) was REVOKED by the operator",
                self.delegation_ids.join(", ")
            ),
            Status::InvalidSignature => format!(
                "the delegation covering this act ({}) does not verify against this box's \
                 operator key, so it is not this operator's grant{}",
                self.delegation_ids.join(", "),
                self.detail.as_deref().map(|d| format!(" ({d})")).unwrap_or_default()
            ),
            Status::Unavailable => format!(
                "the delegation store could not be read, so no authority can be proven{}",
                self.detail.as_deref().map(|d| format!(" ({d})")).unwrap_or_default()
            ),
            Status::Match | Status::NotChecked => return None,
        };
        let remedy = match self.status {
            Status::Revoked => format!(
                "A revocation is the operator's decision: do not retry. If the work is still \
                 needed, ask your operator whether to re-grant ({grant})."
            ),
            Status::Unavailable => "This is an infrastructure fault, not a judgement of the act: \
                 report it to your operator; the operator can also set `hestia delegate mode \
                 record` while the store is repaired."
                .to_string(),
            Status::Unkeyed => format!(
                "Connect this seat once so it is registered, then ask your operator to grant: \
                 {grant}."
            ),
            Status::InvalidSignature => format!(
                "Ask your operator to re-mint it on this box: {grant}. Do not retry until then."
            ),
            _ => format!(
                "Do not retry or rephrase. Ask your operator for a delegation covering this act, \
                 stating why it is needed. The operator grants it with: {grant} (a narrower \
                 `act:{}:/abs/prefix` bound works for file acts). `hestia_operating_law` lists \
                 the delegations you hold.",
                act.category
            ),
        };
        Some(format!("[{rule}] {why}. {remedy}"))
    }
}

/// Assess one act against a snapshot, at `now`.
pub fn assess(snap: &Snapshot, act: &Act, now: DateTime<Utc>) -> Finding {
    let mode = snap.effective_mode();
    let member_lct = snap.member_lcts.get(act.plugin_id).cloned();
    let member_key = member_lct.as_deref().map(agent_key_for_lct);
    let role_key = snap.role_lcts.get(act.role).map(|l| agent_key_for_lct(l));
    let mut f = Finding {
        mode,
        status: Status::NotChecked,
        member_lct,
        member_key,
        role_key,
        delegation_ids: Vec::new(),
        delegator_lct: None,
        matched_via: None,
        matched_action: None,
        detail: None,
        mode_error: snap.mode_error.clone(),
    };
    if mode == GateMode::Off {
        return f;
    }
    let Some(store) = snap.store.as_ref() else {
        f.status = Status::Unavailable;
        f.detail = snap.store_error.clone();
        return f;
    };
    if member_key.is_none() && role_key.is_none() {
        f.status = Status::Unkeyed;
        return f;
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
    let mine: Vec<&DelegatedAuthority> = store.delegations.iter().filter(|d| via(d).is_some()).collect();
    if mine.is_empty() {
        f.status = if member_key.is_none() { Status::Unkeyed } else { Status::None };
        return f;
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
        f.status = Status::Uncovered;
        f.delegation_ids = mine.iter().map(|d| d.id.to_string()).collect();
        let unrestricted = mine
            .iter()
            .any(|d| d.scope.actions.is_empty());
        f.detail = Some(if unrestricted {
            "an unrestricted or role-only delegation does not cover tool acts (it predates the \
             `act` verb and its delegator could not have meant it); re-grant naming `act`"
                .to_string()
        } else {
            "no `act…` action in their scopes covers this tool, category or path".to_string()
        });
        return f;
    }
    let is_expired = |d: &DelegatedAuthority| d.expires_at.is_some_and(|e| now > e);
    let mut matches = Vec::new();
    let mut invalid = Vec::new();
    let mut revoked = Vec::new();
    let mut expired = Vec::new();
    for (d, a) in &covering {
        if d.revoked {
            revoked.push(*d);
        } else if is_expired(d) {
            expired.push(*d);
        } else {
            match snap.operator_key.as_ref() {
                Some(pk) if d.verify(pk).is_ok() => matches.push((*d, a.clone())),
                _ => invalid.push(*d),
            }
        }
    }
    let ids = |v: &[&DelegatedAuthority]| v.iter().map(|d| d.id.to_string()).collect::<Vec<_>>();
    if let Some((first, action)) = matches.first() {
        f.status = Status::Match;
        f.delegation_ids = matches.iter().map(|(d, _)| d.id.to_string()).collect();
        f.delegator_lct = Some(first.delegator_lct_id.to_string());
        f.matched_via = via(first);
        f.matched_action = Some(action.clone());
        return f;
    }
    let (status, set) = if !invalid.is_empty() {
        if snap.operator_key.is_none() {
            f.detail = Some(format!(
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
    f.status = status;
    f.delegation_ids = ids(&set);
    f.delegator_lct = set.first().map(|d| d.delegator_lct_id.to_string());
    f
}

/// The member's delegations, for `hestia_operating_law` (inside the hashed body).
pub fn law_section(snap: &Snapshot, plugin_id: &str, role: &str, now: DateTime<Utc>) -> Value {
    let mode = snap.effective_mode();
    let member_key = snap.member_lcts.get(plugin_id).map(|l| agent_key_for_lct(l));
    let role_key = snap.role_lcts.get(role).map(|l| agent_key_for_lct(l));
    let held: Vec<Value> = snap
        .store
        .as_ref()
        .map(|st| {
            st.delegations
                .iter()
                .filter(|d| Some(d.agent_lct_id) == member_key || Some(d.agent_lct_id) == role_key)
                .filter(|d| !d.revoked && !d.expires_at.is_some_and(|e| now > e))
                .map(|d| {
                    json!({
                        "id": d.id.to_string(),
                        "delegator_lct": d.delegator_lct_id.to_string(),
                        "via": if Some(d.agent_lct_id) == member_key { "member" } else { "role" },
                        "actions": d.scope.actions,
                        "roles": d.scope.roles.iter().map(|r| format!("{r:?}")).collect::<Vec<_>>(),
                        "expires_at": d.expires_at,
                        "signature": match snap.operator_key.as_ref() {
                            Some(pk) if d.verify(pk).is_ok() => "valid",
                            Some(_) => "invalid",
                            None => "unverifiable",
                        },
                        "covers_tool_acts": d.scope.actions.iter().any(|a| act_shape_problem(a) == Some(None)),
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    json!({
        "mode": mode.as_str(),
        "enforced": mode == GateMode::Enforce,
        "agent_key": member_key.map(|k| k.to_string()),
        "role_agent_key": role_key.map(|k| k.to_string()),
        "active": held,
        "store": match &snap.store_error { None => json!("loaded"), Some(e) => json!(format!("unavailable: {e}")) },
        "mode_error": snap.mode_error,
        "vocabulary": "act | act:<category|ToolName|*> | act:<file_read|file_write|*>:/abs/prefix",
        "note": match mode {
            GateMode::Off => "Delegation is not consulted on your acts (operator set mode off).",
            GateMode::Record => "Every decision on your acts records which of these delegations \
                covered it (or that none did). Record mode never changes a verdict.",
            GateMode::Enforce => "An act no ACTIVE, operator-signed delegation here covers is \
                DENIED. Ask your operator for a grant before acting outside them.",
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use web4_core::crypto::KeyPair;

    #[test]
    fn mode_parses_only_its_three_words() {
        for m in [GateMode::Off, GateMode::Record, GateMode::Enforce] {
            assert_eq!(GateMode::parse(m.as_str()), Some(m));
        }
        for bad in ["", "Enforce", "on", "deny", "warn"] {
            assert_eq!(GateMode::parse(bad), None, "{bad}");
        }
    }

    #[test]
    fn act_vocabulary_reads_as_documented() {
        let c = |a, t, cat, tgt| act_covers(a, t, cat, tgt);
        assert!(c("act", "Bash", "command", Some("ls")));
        assert!(c("act:*", "Bash", "command", Some("ls")));
        assert!(c("act:command", "Bash", "command", Some("ls")));
        assert!(!c("act:file_write", "Bash", "command", Some("ls")));
        assert!(c("act:Bash", "Bash", "command", Some("ls")));
        assert!(!c("act:Bash", "Shell", "command", Some("ls")));
        // A path bound binds path-shaped acts only, separator-anchored.
        assert!(c("act:file_write:/w", "Write", "file_write", Some("/w/x.md")));
        assert!(c("act:*:/w", "Read", "file_read", Some("/w")));
        assert!(!c("act:file_write:/w", "Write", "file_write", Some("/wx/a")));
        assert!(!c("act:file_write:/w", "Write", "file_write", Some("/w/../etc/passwd")));
        assert!(!c("act:file_write:/w", "Write", "file_write", Some("rel/x")));
        assert!(!c("act:file_write:/w", "Write", "file_write", None));
        // A command's target is its text, never a path.
        assert!(!c("act:*:/usr", "Bash", "command", Some("/usr/bin/rm -rf /")));
        assert!(!c("act:command:/usr", "Bash", "command", Some("/usr/bin/ls")));
        // Not this verb.
        assert!(!c("scope.decide", "Bash", "command", Some("ls")));
        assert!(!c("actx", "Bash", "command", Some("ls")));
        assert!(!c("act:", "Bash", "command", Some("ls")));
        assert!(!c("act::/w", "Write", "file_write", Some("/w/a")));
    }

    #[test]
    fn act_shape_refuses_what_would_bind_nothing() {
        assert_eq!(act_shape_problem("act"), Some(None));
        assert_eq!(act_shape_problem("act:command"), Some(None));
        assert_eq!(act_shape_problem("act:file_write:/w"), Some(None));
        assert!(matches!(act_shape_problem("act:"), Some(Some(_))));
        assert!(matches!(act_shape_problem("act:file_write:"), Some(Some(_))));
        assert!(matches!(act_shape_problem("act:file_write:rel"), Some(Some(_))));
        assert!(matches!(act_shape_problem("act:command:/usr"), Some(Some(_))));
        assert_eq!(act_shape_problem("scope.decide"), None);
        assert_eq!(act_shape_problem("ledger.read"), None);
    }

    /// Pin: every shape act_shape_problem accepts covers SOMETHING, every one it refuses covers
    /// nothing — two readings of one grammar must not drift (#1110's rule).
    #[test]
    fn act_shape_agrees_with_act_covers() {
        let probes = [
            ("Bash", "command", Some("ls")),
            ("Write", "file_write", Some("/w/a")),
            ("Read", "file_read", Some("/w")),
            ("WebFetch", "network", Some("https://x")),
        ];
        for a in ["act:", "act:file_write:", "act:file_write:rel", "act::/w", "act:command:/usr"] {
            assert!(matches!(act_shape_problem(a), Some(Some(_))), "{a}");
            for (t, c, tg) in probes {
                if a == "act:command:/usr" {
                    // Refused because a path bound on a command binds nothing:
                    assert!(!act_covers(a, t, c, Some("/usr/bin/ls")));
                }
                assert!(!act_covers(a, t, c, tg), "{a} refused but covers {t}");
            }
        }
    }

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

    fn grant(fx: &mut Fx, agent: Uuid, actions: &[&str], hours: Option<u64>, signer: Option<&KeyPair>) -> String {
        let store = fx.snap.store.as_mut().unwrap();
        let signer = signer.unwrap_or(&fx.op);
        store
            .create_delegation(
                Uuid::new_v4(),
                agent,
                vec![],
                actions.iter().map(|s| s.to_string()).collect(),
                hours,
                signer,
            )
            .id
            .to_string()
    }

    fn act<'a>(tool: &'a str, cat: &'a str, target: Option<&'a str>) -> Act<'a> {
        Act { plugin_id: "codex", role: "role:worker", tool_name: tool, category: cat, target }
    }

    #[test]
    fn covering_valid_delegation_is_a_match_with_its_id_and_delegator() {
        let mut f = fx();
        let key = f.key;
        let id = grant(&mut f, key, &["act:command"], Some(2), None);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::Match);
        assert_eq!(r.delegation_ids, vec![id]);
        assert!(r.delegator_lct.is_some());
        assert_eq!(r.matched_via, Some("member"));
        assert_eq!(r.enforced_rule(), None);
        let j = r.to_json("query_policy");
        assert_eq!(j["status"], "match");
        assert_eq!(j["mode"], "record");
    }

    #[test]
    fn role_keyed_delegation_matches_via_role() {
        let mut f = fx();
        let rk = agent_key_for_lct("lct:web4:mb32:role-worker");
        grant(&mut f, rk, &["act"], None, None);
        let r = assess(&f.snap, &act("Read", "file_read", Some("/x")), Utc::now());
        assert_eq!((r.status, r.matched_via), (Status::Match, Some("role")));
    }

    #[test]
    fn no_delegation_records_none_and_only_enforce_denies() {
        let f = fx();
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::None);
        assert_eq!(r.enforced_rule(), None, "record mode never denies");
        let mut f = fx();
        f.snap.mode = Some(GateMode::Enforce);
        let a = act("Bash", "command", Some("ls"));
        let r = assess(&f.snap, &a, Utc::now());
        assert_eq!(r.enforced_rule(), Some("delegation.absent"));
        let why = r.deny_reason(&a).unwrap();
        assert!(why.contains("hestia delegate grant") && why.contains("act:command"), "{why}");
    }

    #[test]
    fn uncovered_expired_revoked_and_bad_signature_are_distinct() {
        // Uncovered: holds a file grant, acts with a command.
        let mut f = fx();
        let key = f.key;
        grant(&mut f, key, &["act:file_write:/w"], None, None);
        assert_eq!(assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now()).status, Status::Uncovered);
        // Unrestricted does not cover (dormant records gain nothing).
        let mut f = fx();
        let key = f.key;
        grant(&mut f, key, &[], None, None);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::Uncovered);
        assert!(r.detail.unwrap().contains("unrestricted"));
        // Expired.
        let mut f = fx();
        let key = f.key;
        grant(&mut f, key, &["act"], Some(1), None);
        let later = Utc::now() + chrono::Duration::hours(2);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), later);
        assert_eq!(r.status, Status::Expired);
        // Revoked.
        let mut f = fx();
        let key = f.key;
        let id = grant(&mut f, key, &["act"], None, None);
        f.snap.store.as_mut().unwrap().revoke(Uuid::parse_str(&id).unwrap()).unwrap();
        f.snap.mode = Some(GateMode::Enforce);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!((r.status, r.enforced_rule()), (Status::Revoked, Some("delegation.revoked")));
        assert_eq!(r.delegation_ids, vec![id]);
        // Signed by someone other than this box's operator.
        let mut f = fx();
        let key = f.key;
        let stranger = KeyPair::generate();
        grant(&mut f, key, &["act"], None, Some(&stranger));
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::InvalidSignature);
        // A valid one alongside an invalid one is a match: the valid one is the authority.
        let mut f = fx();
        let key = f.key;
        grant(&mut f, key, &["act"], None, Some(&stranger));
        let good = grant(&mut f, key, &["act"], None, None);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!((r.status, r.delegation_ids), (Status::Match, vec![good]));
    }

    #[test]
    fn off_is_not_checked_and_unreadable_store_is_unavailable() {
        let mut f = fx();
        f.snap.mode = Some(GateMode::Off);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.status, Status::NotChecked);
        assert_eq!(r.to_json("x").get("delegation_ids"), None);
        let mut f = fx();
        f.snap.store = None;
        f.snap.store_error = Some("boom".into());
        f.snap.mode = Some(GateMode::Enforce);
        let r = assess(&f.snap, &act("Bash", "command", Some("ls")), Utc::now());
        assert_eq!(r.enforced_rule(), Some("delegation.unavailable"));
    }

    #[test]
    fn unregistered_member_is_unkeyed() {
        let f = fx();
        let a = Act { plugin_id: "ghost", role: "role:none", tool_name: "Bash", category: "command", target: None };
        assert_eq!(assess(&f.snap, &a, Utc::now()).status, Status::Unkeyed);
    }

    #[test]
    fn mode_document_is_vault_only_and_strict() {
        let dir = tempfile::TempDir::new().unwrap();
        let mut v = crate::vault::Vault::init(dir.path().join("v.enc"), "p".into()).unwrap();
        assert!(load_mode(&v).unwrap().is_none(), "absent = default");
        // A plaintext sidecar a same-UID member could write is NOT read.
        std::fs::write(dir.path().join("delegation-gate.json"), r#"{"mode":"off","set_at":"2026-01-01T00:00:00Z"}"#).unwrap();
        assert!(load_mode(&v).unwrap().is_none());
        save_mode(&mut v, GateMode::Enforce, Some("t".into())).unwrap();
        assert_eq!(GateMode::parse(&load_mode(&v).unwrap().unwrap().mode), Some(GateMode::Enforce));
        v.put_document(MODE_NS, MODE_DOC, br#"{"mode":"enforced","set_at":"2026-01-01T00:00:00Z"}"#.to_vec()).unwrap();
        assert!(load_mode(&v).is_err(), "an unknown mode is an error, not a silent default");
    }
}

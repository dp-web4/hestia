//! The operator's ledger of ADMIN acts — escalations, law edits, grants, adjudications.
//!
//! dp, 2026-08-05: *"i need a separate witness chain of admin actions from which i can
//! select/review/approve/deny, sortable by all/open/approved/denied. the chain would also record
//! any law edits, permission grants/restrictions, etc. currently i do not see any escalations for
//! me to approve/deny, nor can i see any history."*
//!
//! # Why this is a PROJECTION and not a second chain
//!
//! The ask says "separate witness chain". This module builds a separate *view* over the one chain
//! instead, and the reason is dp's own earlier ruling, already quoted in `gate_escalation.rs`:
//! a governance act is *"a separate act, linked to the previous act it modifies, both properly
//! witnessed, all one chain."* A second durable store of the same acts is the two-copies-no-
//! comparison shape — it can disagree with the chain, and then neither is evidence.
//!
//! So: one chain, one append path, and a projection that makes the admin subset selectable. What
//! dp asked for operationally — see it, sort it, rule on it — is delivered. What is deliberately
//! NOT delivered is a second place where an admin act could exist without existing on the chain.
//! (GPT's PRD §14 proposes physically separate member and role chains; that is a larger change
//! with its own atomicity requirements, and this module does not prejudge it.)
//!
//! # Why the operator was seeing nothing
//!
//! Two independent causes, both real, found 2026-08-05:
//!
//! 1. **Pending was genuinely empty.** `DEFAULT_TTL_SECS` is 3600. Escalations `797ac6cf` and
//!    `f0cda5bc` opened at ~22:12 and were reaped before dp looked in the morning. The store's own
//!    comment already conceded the shape — *"a window sized for someone already watching"* — and
//!    records `8bb08a85` expiring unruled on 2026-07-30. An operator who sleeps sees an empty list,
//!    and an empty list is indistinguishable from a quiet night.
//! 2. **There was no history surface at all.** The dashboard renders `pending_escalations`, and
//!    `pending()` drops the expired by design. Nothing rendered a decided or lapsed one, ever. The
//!    entries were on the chain the whole time — `rehydrate` proves it, since it rebuilds live
//!    escalations from exactly these events — but no reader projected them.
//!
//! This module answers (2) directly and makes (1) *visible* rather than silently fixing it:
//! `Expired` is a first-class status, so "nobody ruled in time" reads as a governance outcome
//! instead of as an absence. Whether the TTL itself should change is dp's call, not this file's.
//!
//! # Windowing is disclosed, never silent
//!
//! The chain is read through a bounded window. A window that fills can cut a `decided` off from
//! its `opened`, so:
//!
//! * a decision with no visible open still produces a row (synthesised from the decision), rather
//!   than being dropped — a ruling must never vanish because its ask scrolled off;
//! * `LedgerPage::truncated` says the window filled, so a caller can render "windowed" instead of
//!   implying it is looking at everything.
//!
//! A silent cap here would read as "no admin acts", which is the exact failure this module exists
//! to end.

use crate::storage::chain::ChainEntry;
use serde::Serialize;
use std::collections::HashMap;

/// Every event type that is an ADMIN act — something an operator did, must decide, or should be
/// able to read back later.
///
/// Grouped by what a reader is looking for, not by which module writes them.
pub const GOVERNANCE_EVENTS: &[&str] = &[
    // Governance-surface escalations — the decidable ones.
    "gate_escalation_opened",
    "gate_escalation_decided",
    "gate_escalation_claimed",
    "gate_escalation_corroborated",
    "gate_escalation_refused",
    "gate_escalation_arbiter_refused",
    // Scope requests — also decidable, same operator, different surface.
    "scope_requested",
    // A DURABLE grant that was attempted. Listed so a grant that failed its vault write is
    // VISIBLE here rather than only in the raw chain: `scope_granted` is now appended after
    // the commit, so a failed durable grant emits an intent and no success, and without this
    // line the ledger would show nothing at all for it — an invisible failure, which is the
    // class this whole surface exists to end.
    //
    // The cost, named rather than hidden: a SUCCESSFUL standing grant now emits two entries,
    // intent and success. They key on the same `request_id` where one exists, so the scope
    // row resolves to `granted` either way and the noise is bounded to operator-originated
    // grants (which carry no request_id). Truthful-and-slightly-noisy beats tidy-and-silent.
    "scope_grant_intent",
    "scope_granted",
    "scope_refused",
    "scope_attestation",
    // Society-wide permission mutations. Intent and terminal fact remain separate rows so a
    // failed durable change is visible without being mistaken for one that landed.
    "society_floor_intent",
    "society_floor_added",
    "society_floor_remove_intent",
    "society_floor_removed",
    // The law itself.
    "policy_edit",
    // Permission grants and restrictions.
    "policy_instance_grant",
    "policy_instance_grant_revoked",
    "agent_ungovern",
    "amnesty",
    // Conduct adjudication.
    "appeal",
    "adjudication",
    "reversal",
    // Operator presence and identity acts.
    "operator_session_opened",
    "operator_gate",
    "operator_bootstrap",
    "gate_ratified",
    "credential_issued",
    "orchestrator_connect",
    // Secret release. A vault write is an admin act; a vault read is a release of a secret, which
    // an operator reviewing conduct needs to see for the same reason.
    "vault_set",
    "vault_get",
];

pub fn is_governance_event(event_type: &str) -> bool {
    GOVERNANCE_EVENTS.contains(&event_type)
}

/// What kind of admin act a row is. Drives grouping in the UI, not the decision logic.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LedgerKind {
    Escalation,
    ScopeRequest,
    LawEdit,
    Permission,
    Adjudication,
    OperatorAct,
}

/// The facets dp asked to sort by, plus the two the data actually contains.
///
/// `Expired` is separate from `Denied` on purpose. Both refuse the act, but they are different
/// governance facts: denied means someone ruled, expired means nobody did. Folding them together
/// would hide exactly the failure that produced this module.
///
/// `Recorded` is for acts that were not requests — a law edit already happened; there is nothing
/// to approve. It is still ledger content, because dp asked for law edits and grants to be here.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LedgerStatus {
    Open,
    Approved,
    Denied,
    Expired,
    Recorded,
}

impl LedgerStatus {
    /// Match against the `status` query filter. `all` matches everything.
    pub fn matches(&self, filter: &str) -> bool {
        match filter {
            "all" | "" => true,
            "open" => *self == LedgerStatus::Open,
            "approved" => *self == LedgerStatus::Approved,
            "denied" => *self == LedgerStatus::Denied,
            "expired" => *self == LedgerStatus::Expired,
            "recorded" => *self == LedgerStatus::Recorded,
            // An unrecognised filter matches NOTHING rather than everything. A typo that silently
            // widened to "all" would show an operator more than they asked to see and call it a
            // filtered view.
            _ => false,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct LedgerRow {
    /// The join key for decidable rows (escalation_id / request_id); the chain hash for one-shots.
    pub id: String,
    pub kind: LedgerKind,
    pub status: LedgerStatus,
    pub event_type: String,
    /// RFC3339. When the ask was filed, or when the one-shot act happened.
    pub opened_at: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub decided_at: Option<String>,
    /// Who is the SUBJECT of the act — the member being governed.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub plugin_id: Option<String>,
    /// role@agent, both halves. Either alone lets the surface lie.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    /// What was attempted — tool, path, rule id, whatever the act was about.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subject: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
    /// Why the member says it needs this.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    /// Bounded, secret-scrubbed summary of the attempted operation, when the gate reported one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub decided_by: Option<String>,
    /// `operator_session` (proved an LCT) vs `cli` (proved only filesystem access). A reader must
    /// be able to tell a proof from a convenience.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub decided_via: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub decision_reason: Option<String>,
    /// Unix seconds. Present on decidable rows; drives the Open→Expired transition.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<u64>,
    /// Seconds left to rule. 0 once expired.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub secs_remaining: Option<u64>,
    /// Evidence added without deciding (#122 — approval accumulates as factors).
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub corroborations: Vec<String>,
    /// Whether an approved escalation was actually spent. An approval nobody claimed is a
    /// different fact from one that was used.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub claimed_at: Option<String>,
    /// The chain entry this row opened at, and the one that decided it. Both, so an operator can
    /// go from the ledger to the witnessed evidence without a search.
    pub opened_hash: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub decided_hash: Option<String>,
    pub chain_position: u64,
    /// True when the row was built from a decision whose opening act was outside the window. The
    /// row is real; its ask is simply not in view.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub open_not_in_window: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct LedgerPage {
    pub rows: Vec<LedgerRow>,
    /// Per-status totals BEFORE the status filter is applied, so the UI can label its tabs with
    /// counts without issuing five queries.
    pub counts: LedgerCounts,
    /// The window filled. There may be older admin acts this page cannot see.
    pub truncated: bool,
    /// How many chain entries were scanned to build this page.
    pub scanned: u64,
    /// Set when the chain read FAILED. The rows are then whatever was readable — which may be
    /// nothing — and a caller must render this rather than an empty ledger.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub read_error: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct LedgerCounts {
    pub all: usize,
    pub open: usize,
    pub approved: usize,
    pub denied: usize,
    pub expired: usize,
    pub recorded: usize,
}

impl LedgerCounts {
    fn tally(&mut self, s: LedgerStatus) {
        self.all += 1;
        match s {
            LedgerStatus::Open => self.open += 1,
            LedgerStatus::Approved => self.approved += 1,
            LedgerStatus::Denied => self.denied += 1,
            LedgerStatus::Expired => self.expired += 1,
            LedgerStatus::Recorded => self.recorded += 1,
        }
    }
}

fn s(v: &serde_json::Value, k: &str) -> Option<String> {
    v.get(k)
        .and_then(|x| x.as_str())
        .filter(|x| !x.is_empty())
        .map(str::to_string)
}

fn u(v: &serde_json::Value, k: &str) -> Option<u64> {
    v.get(k).and_then(serde_json::Value::as_u64)
}

/// Fold chain entries into ledger rows.
///
/// `entries` may arrive in either order; this reverses to arrival order internally when needed,
/// because a decision applied before the open it belongs to would be dropped. `now` is unix
/// seconds and decides Open vs Expired.
pub fn project(entries: &[ChainEntry], now: u64) -> Vec<LedgerRow> {
    // Arrival order: the fold applies `opened` then its `decided`.
    let mut ordered: Vec<&ChainEntry> = entries.iter().collect();
    ordered.sort_by_key(|e| e.chain_position);

    // Decidable rows are keyed by their join key so a later decision lands on the same row.
    let mut keyed: HashMap<String, LedgerRow> = HashMap::new();
    // Insertion order of keyed rows, plus one-shot rows, so output order is deterministic.
    let mut order: Vec<Row> = Vec::new();

    enum Row {
        Keyed(String),
        OneShot(LedgerRow),
    }

    for e in ordered {
        let d = &e.event_data;
        let ts = e.timestamp.to_rfc3339();
        match e.event_type.as_str() {
            "gate_escalation_opened" => {
                let Some(id) = s(d, "escalation_id") else { continue };
                let expires_at = u(d, "expires_at");
                let row = LedgerRow {
                    id: id.clone(),
                    kind: LedgerKind::Escalation,
                    status: LedgerStatus::Open,
                    event_type: e.event_type.clone(),
                    opened_at: ts,
                    decided_at: None,
                    plugin_id: s(d, "plugin_id"),
                    role: s(d, "role"),
                    subject: s(d, "marker"),
                    tool_name: s(d, "tool_name"),
                    reason: s(d, "reason").or_else(|| s(d, "stated_reason")),
                    detail: s(d, "detail").or_else(|| s(d, "stated_detail")),
                    decided_by: None,
                    decided_via: None,
                    decision_reason: None,
                    expires_at,
                    secs_remaining: None,
                    corroborations: Vec::new(),
                    claimed_at: None,
                    opened_hash: e.hash.clone(),
                    decided_hash: None,
                    chain_position: e.chain_position,
                    open_not_in_window: false,
                };
                if keyed.insert(id.clone(), row).is_none() {
                    order.push(Row::Keyed(id));
                }
            }
            "scope_requested" => {
                let Some(id) = s(d, "request_id").or_else(|| s(d, "id")) else { continue };
                let row = LedgerRow {
                    id: id.clone(),
                    kind: LedgerKind::ScopeRequest,
                    status: LedgerStatus::Open,
                    event_type: e.event_type.clone(),
                    opened_at: ts,
                    decided_at: None,
                    plugin_id: s(d, "plugin_id"),
                    role: s(d, "role"),
                    subject: s(d, "path"),
                    tool_name: None,
                    reason: s(d, "reason").or_else(|| s(d, "requested_because")),
                    detail: None,
                    decided_by: None,
                    decided_via: None,
                    decision_reason: None,
                    expires_at: u(d, "expires_at"),
                    secs_remaining: None,
                    corroborations: Vec::new(),
                    claimed_at: None,
                    opened_hash: e.hash.clone(),
                    decided_hash: None,
                    chain_position: e.chain_position,
                    open_not_in_window: false,
                };
                if keyed.insert(id.clone(), row).is_none() {
                    order.push(Row::Keyed(id));
                }
            }
            "gate_escalation_decided" | "scope_granted" | "scope_refused" => {
                let is_scope = e.event_type != "gate_escalation_decided";
                let Some(id) = (if is_scope {
                    s(d, "request_id").or_else(|| s(d, "id"))
                } else {
                    s(d, "escalation_id")
                }) else {
                    continue;
                };
                let approved = if is_scope {
                    e.event_type == "scope_granted"
                } else {
                    // `status` is the stored verdict; fall back to an explicit bool if present.
                    match s(d, "status").as_deref() {
                        Some("approved") => true,
                        Some("denied") => false,
                        _ => d.get("approve").and_then(serde_json::Value::as_bool).unwrap_or(false),
                    }
                };
                let status = if approved { LedgerStatus::Approved } else { LedgerStatus::Denied };

                if let Some(row) = keyed.get_mut(&id) {
                    row.status = status;
                    row.decided_at = Some(ts);
                    row.decided_by = s(d, "decided_by").or_else(|| s(d, "granted_by"));
                    row.decided_via = s(d, "decided_via").or_else(|| s(d, "via"));
                    row.decision_reason = s(d, "reason").or_else(|| s(d, "decision_reason"));
                    row.decided_hash = Some(e.hash.clone());
                } else {
                    // A ruling whose ask scrolled out of the window. It is still a ruling, and
                    // dropping it would be the silent-truncation failure this module refuses.
                    let row = LedgerRow {
                        id: id.clone(),
                        kind: if is_scope { LedgerKind::ScopeRequest } else { LedgerKind::Escalation },
                        status,
                        event_type: e.event_type.clone(),
                        opened_at: ts.clone(),
                        decided_at: Some(ts),
                        plugin_id: s(d, "plugin_id"),
                        role: s(d, "role"),
                        subject: s(d, "marker").or_else(|| s(d, "path")),
                        tool_name: s(d, "tool_name"),
                        reason: s(d, "requested_because"),
                        detail: None,
                        decided_by: s(d, "decided_by").or_else(|| s(d, "granted_by")),
                        decided_via: s(d, "decided_via").or_else(|| s(d, "via")),
                        decision_reason: s(d, "reason").or_else(|| s(d, "decision_reason")),
                        expires_at: u(d, "expires_at"),
                        secs_remaining: None,
                        corroborations: Vec::new(),
                        claimed_at: None,
                        opened_hash: e.hash.clone(),
                        decided_hash: Some(e.hash.clone()),
                        chain_position: e.chain_position,
                        open_not_in_window: true,
                    };
                    keyed.insert(id.clone(), row);
                    order.push(Row::Keyed(id));
                }
            }
            "gate_escalation_claimed" => {
                if let Some(id) = s(d, "escalation_id") {
                    if let Some(row) = keyed.get_mut(&id) {
                        row.claimed_at = Some(ts);
                    }
                }
            }
            "gate_escalation_corroborated" => {
                if let Some(id) = s(d, "escalation_id") {
                    if let Some(row) = keyed.get_mut(&id) {
                        let who = s(d, "by")
                            .or_else(|| s(d, "corroborated_by"))
                            .unwrap_or_else(|| "unknown".into());
                        row.corroborations.push(who);
                    }
                }
            }
            // A refusal to OPEN — quota, flood, or an arbiter that would not rule. Not a decision
            // on an ask, so it is its own row rather than an update to one.
            "gate_escalation_refused" | "gate_escalation_arbiter_refused" => {
                order.push(Row::OneShot(one_shot(
                    e,
                    LedgerKind::Escalation,
                    LedgerStatus::Denied,
                    s(d, "marker"),
                )));
            }
            "policy_edit" => {
                let subject = s(d, "change")
                    .map(|c| match s(d, "rule_id").or_else(|| s(d, "preset")) {
                        Some(t) => format!("{c}: {t}"),
                        None => c,
                    })
                    .or_else(|| s(d, "rule_id"));
                order.push(Row::OneShot(one_shot(e, LedgerKind::LawEdit, LedgerStatus::Recorded, subject)));
            }
            "policy_instance_grant" | "policy_instance_grant_revoked" | "agent_ungovern"
            | "amnesty" => {
                let subject = s(d, "preset")
                    .or_else(|| s(d, "path"))
                    .or_else(|| s(d, "scope"))
                    .or_else(|| s(d, "role"));
                order.push(Row::OneShot(one_shot(e, LedgerKind::Permission, LedgerStatus::Recorded, subject)));
            }
            // A durable grant that was ATTEMPTED. Its own row, as a Permission act, because the
            // question it answers is "was a widening tried here, and did it land" — and the
            // answer is legible only if the attempt is visible beside its outcome.
            //
            // It is a one-shot rather than a keyed row on purpose: keying it by `request_id`
            // would make it collide with the `scope_granted`/`scope_refused` that closes the
            // scope row, and the LAST write would win — so a successful grant's intent would
            // overwrite, or be overwritten by, its own success depending on scan order. That is
            // a coin-flip in a governance ledger. Separate rows cost one extra line per durable
            // grant and cannot lie about which one happened.
            //
            // A FAILED durable grant therefore shows exactly one intent row and no success —
            // which is the state — while its scope row (keyed on request_id, for the
            // member-asked path) correctly remains undecided, because nothing was granted.
            "scope_grant_intent" => {
                let subject = s(d, "path").or_else(|| s(d, "plugin_id"));
                order.push(Row::OneShot(one_shot(
                    e,
                    LedgerKind::Permission,
                    LedgerStatus::Recorded,
                    subject,
                )));
            }
            // A society-floor mutation is wider than a member grant, but has the same
            // evidentiary shape: intent says it was attempted; the terminal event says it
            // became durable. Never fold the pair into one row because, on a failed persist or
            // terminal append, the surviving intent must stay visible without implying success.
            "society_floor_intent" | "society_floor_added"
            | "society_floor_remove_intent" | "society_floor_removed" => {
                order.push(Row::OneShot(one_shot(
                    e,
                    LedgerKind::Permission,
                    LedgerStatus::Recorded,
                    s(d, "path"),
                )));
            }
            "appeal" | "adjudication" | "reversal" => {
                let subject = s(d, "deny_hash")
                    .or_else(|| s(d, "claim_ref"))
                    .or_else(|| s(d, "verdict"));
                order.push(Row::OneShot(one_shot(e, LedgerKind::Adjudication, LedgerStatus::Recorded, subject)));
            }
            "scope_attestation" | "operator_session_opened" | "operator_gate"
            | "operator_bootstrap" | "gate_ratified" | "credential_issued"
            | "orchestrator_connect" | "vault_set" | "vault_get" => {
                let subject = s(d, "name")
                    .or_else(|| s(d, "path"))
                    .or_else(|| s(d, "gate"))
                    .or_else(|| s(d, "operator"));
                order.push(Row::OneShot(one_shot(e, LedgerKind::OperatorAct, LedgerStatus::Recorded, subject)));
            }
            _ => {}
        }
    }

    // Resolve Open → Expired on the clock alone, and compute the countdown. An undecided ask past
    // its horizon is not still open; the write it would have permitted was refused long ago.
    let mut out: Vec<LedgerRow> = Vec::with_capacity(order.len());
    for r in order {
        let mut row = match r {
            Row::Keyed(id) => match keyed.remove(&id) {
                Some(row) => row,
                None => continue,
            },
            Row::OneShot(row) => row,
        };
        if row.status == LedgerStatus::Open {
            match row.expires_at {
                Some(exp) if now >= exp => {
                    row.status = LedgerStatus::Expired;
                    row.secs_remaining = Some(0);
                }
                Some(exp) => row.secs_remaining = Some(exp - now),
                // No horizon recorded. Leaving it Open forever would show an operator a button
                // that cannot work, so it reads as expired — the same answer `poll` already gives
                // for an id it cannot account for.
                None => row.status = LedgerStatus::Expired,
            }
        }
        out.push(row);
    }

    // Newest first: an operator opens this to see what is waiting, not what is oldest.
    out.sort_by(|a, b| b.chain_position.cmp(&a.chain_position));
    out
}

fn one_shot(
    e: &ChainEntry,
    kind: LedgerKind,
    status: LedgerStatus,
    subject: Option<String>,
) -> LedgerRow {
    let d = &e.event_data;
    LedgerRow {
        id: e.hash.clone(),
        kind,
        status,
        event_type: e.event_type.clone(),
        opened_at: e.timestamp.to_rfc3339(),
        decided_at: None,
        plugin_id: s(d, "plugin_id"),
        role: s(d, "role"),
        subject,
        tool_name: s(d, "tool_name"),
        reason: s(d, "reason").or_else(|| s(d, "requested_because")),
        detail: s(d, "detail"),
        decided_by: s(d, "decided_by")
            .or_else(|| s(d, "granted_by"))
            .or_else(|| s(d, "by")),
        decided_via: s(d, "via").or_else(|| s(d, "decided_via")),
        decision_reason: s(d, "decision_reason"),
        expires_at: None,
        secs_remaining: None,
        corroborations: Vec::new(),
        claimed_at: None,
        opened_hash: e.hash.clone(),
        decided_hash: None,
        chain_position: e.chain_position,
        open_not_in_window: false,
    }
}

/// Apply the status filter and count. Counts are computed over ALL rows, before filtering, so tab
/// labels stay honest while a tab is selected.
pub fn page(rows: Vec<LedgerRow>, status_filter: &str, limit: usize) -> LedgerPage {
    let mut counts = LedgerCounts::default();
    for r in &rows {
        counts.tally(r.status);
    }
    let rows: Vec<LedgerRow> = rows
        .into_iter()
        .filter(|r| r.status.matches(status_filter))
        .take(limit)
        .collect();
    LedgerPage {
        rows,
        counts,
        truncated: false,
        scanned: 0,
        read_error: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Utc};

    const T0: u64 = 1_700_000_000;

    fn entry(pos: u64, secs: u64, event_type: &str, data: serde_json::Value) -> ChainEntry {
        ChainEntry {
            hash: format!("hash{pos}"),
            prev_hash: format!("hash{}", pos.saturating_sub(1)),
            timestamp: Utc.timestamp_opt((T0 + secs) as i64, 0).unwrap(),
            event_type: event_type.to_string(),
            event_data: data,
            signer_lct: "lct:sovereign".into(),
            chain_position: pos,
        }
    }

    fn opened(pos: u64, id: &str, secs: u64) -> ChainEntry {
        entry(
            pos,
            secs,
            "gate_escalation_opened",
            serde_json::json!({
                "escalation_id": id,
                "plugin_id": "claude-code",
                "role": "role:constellation:member",
                "tool_name": "Bash",
                "marker": "pre_tool_use.py",
                "expires_at": T0 + secs + 3600,
                "reason": "needs to deploy the gate",
            }),
        )
    }

    fn decided(pos: u64, id: &str, secs: u64, status: &str) -> ChainEntry {
        entry(
            pos,
            secs,
            "gate_escalation_decided",
            serde_json::json!({
                "escalation_id": id,
                "plugin_id": "claude-code",
                "status": status,
                "decided_by": "role:operator@dp",
                "decided_via": "operator_session",
                "reason": "reviewed the diff",
            }),
        )
    }

    /// The defect that produced this module: an undecided escalation must still be READABLE after
    /// its window closes, and it must read as EXPIRED — not as absent, and not as denied.
    #[test]
    fn an_unruled_escalation_reads_as_expired_not_as_absent() {
        let rows = project(&[opened(1, "797ac6cf", 0)], T0 + 7_200);
        assert_eq!(rows.len(), 1, "the ask must survive its own expiry as a record");
        assert_eq!(rows[0].status, LedgerStatus::Expired);
        assert_eq!(rows[0].secs_remaining, Some(0));
        // Expired is NOT denied. Nobody ruled; that is a different governance fact.
        assert_ne!(rows[0].status, LedgerStatus::Denied);
    }

    #[test]
    fn a_live_escalation_is_open_and_carries_its_countdown() {
        let rows = project(&[opened(1, "abc", 0)], T0 + 600);
        assert_eq!(rows[0].status, LedgerStatus::Open);
        assert_eq!(rows[0].secs_remaining, Some(3_000));
        assert_eq!(rows[0].plugin_id.as_deref(), Some("claude-code"));
        assert_eq!(rows[0].tool_name.as_deref(), Some("Bash"));
    }

    #[test]
    fn a_decision_lands_on_the_row_it_decides() {
        let rows = project(
            &[opened(1, "abc", 0), decided(2, "abc", 60, "approved")],
            T0 + 120,
        );
        assert_eq!(rows.len(), 1, "one ask and its answer are ONE row");
        assert_eq!(rows[0].status, LedgerStatus::Approved);
        assert_eq!(rows[0].decided_by.as_deref(), Some("role:operator@dp"));
        assert_eq!(rows[0].decided_via.as_deref(), Some("operator_session"));
        assert_eq!(rows[0].opened_hash, "hash1");
        assert_eq!(rows[0].decided_hash.as_deref(), Some("hash2"));
    }

    /// A decision cannot expire out from under itself: once ruled, the clock is irrelevant.
    #[test]
    fn a_decided_escalation_does_not_become_expired_later() {
        let rows = project(
            &[opened(1, "abc", 0), decided(2, "abc", 60, "denied")],
            T0 + 999_999,
        );
        assert_eq!(rows[0].status, LedgerStatus::Denied);
    }

    /// Windowing must not swallow a ruling. If the `opened` scrolled off, the decision still
    /// produces a row — flagged, so the reader knows the ask is out of view rather than missing.
    #[test]
    fn a_ruling_whose_ask_scrolled_off_still_appears() {
        let rows = project(&[decided(9, "orphan", 60, "approved")], T0 + 120);
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, LedgerStatus::Approved);
        assert!(rows[0].open_not_in_window, "the reader must be told the ask is out of window");
    }

    #[test]
    fn claims_and_corroborations_annotate_without_changing_the_verdict() {
        let rows = project(
            &[
                opened(1, "abc", 0),
                entry(2, 30, "gate_escalation_corroborated",
                      serde_json::json!({"escalation_id": "abc", "by": "kimi-code"})),
                decided(3, "abc", 60, "approved"),
                entry(4, 90, "gate_escalation_claimed",
                      serde_json::json!({"escalation_id": "abc"})),
            ],
            T0 + 120,
        );
        assert_eq!(rows[0].status, LedgerStatus::Approved);
        assert_eq!(rows[0].corroborations, vec!["kimi-code".to_string()]);
        assert!(rows[0].claimed_at.is_some(), "a spent approval is a different fact from an unspent one");
    }

    /// dp asked for law edits and grants in the same ledger. They are not decidable, so they are
    /// Recorded — present and reviewable, with nothing to approve.
    #[test]
    fn law_edits_and_grants_are_recorded_rows() {
        let rows = project(
            &[
                entry(1, 0, "policy_edit",
                      serde_json::json!({"change": "set_preset", "preset": "safety"})),
                entry(2, 10, "policy_instance_grant",
                      serde_json::json!({"plugin_id": "kimi-code", "preset": "permissive"})),
            ],
            T0 + 100,
        );
        assert_eq!(rows.len(), 2);
        assert!(rows.iter().all(|r| r.status == LedgerStatus::Recorded));
        let law = rows.iter().find(|r| r.kind == LedgerKind::LawEdit).expect("law edit row");
        assert_eq!(law.subject.as_deref(), Some("set_preset: safety"));
        assert!(rows.iter().any(|r| r.kind == LedgerKind::Permission));
    }

    /// Non-governance traffic must not leak into the admin ledger — that is the whole point of a
    /// separate view.
    #[test]
    fn member_acts_are_not_admin_acts() {
        let rows = project(
            &[
                entry(1, 0, "outcome", serde_json::json!({"plugin_id": "claude-code"})),
                entry(2, 10, "policy_decision", serde_json::json!({"decision": "deny"})),
                opened(3, "abc", 20),
            ],
            T0 + 100,
        );
        assert_eq!(rows.len(), 1, "only the escalation is an admin act");
        assert_eq!(rows[0].id, "abc");
    }

    #[test]
    fn newest_first() {
        let rows = project(&[opened(1, "old", 0), opened(2, "new", 10)], T0 + 20);
        assert_eq!(rows[0].id, "new");
        assert_eq!(rows[1].id, "old");
    }

    #[test]
    fn counts_are_computed_before_the_filter_so_tabs_stay_honest() {
        let rows = project(
            &[
                opened(1, "live", 0),
                opened(2, "stale", 0),
                decided(3, "stale", 60, "denied"),
                entry(4, 70, "policy_edit", serde_json::json!({"change": "add_rule"})),
            ],
            T0 + 600,
        );
        let p = page(rows, "open", 100);
        assert_eq!(p.rows.len(), 1, "the page shows only open");
        assert_eq!(p.counts.all, 3, "but the counts still describe everything");
        assert_eq!(p.counts.open, 1);
        assert_eq!(p.counts.denied, 1);
        assert_eq!(p.counts.recorded, 1);
    }

    /// A typo in the filter must show nothing, not everything. Widening on an unrecognised value
    /// would hand an operator an unfiltered view labelled as filtered.
    #[test]
    fn an_unknown_status_filter_matches_nothing() {
        let rows = project(&[opened(1, "abc", 0)], T0 + 10);
        assert_eq!(page(rows, "aproved", 100).rows.len(), 0);
    }

    #[test]
    fn an_escalation_with_no_horizon_is_not_shown_as_decidable() {
        let e = entry(
            1,
            0,
            "gate_escalation_opened",
            serde_json::json!({"escalation_id": "nohorizon", "plugin_id": "x"}),
        );
        let rows = project(&[e], T0 + 10);
        assert_eq!(rows[0].status, LedgerStatus::Expired,
                   "a button that cannot work must not be rendered as open");
    }

    #[test]
    fn scope_requests_share_the_ledger_with_escalations() {
        let rows = project(
            &[
                entry(1, 0, "scope_requested",
                      serde_json::json!({"request_id": "r1", "plugin_id": "kimi-code",
                                         "path": "/repo/x", "expires_at": T0 + 3600,
                                         "reason": "needs the file"})),
                entry(2, 60, "scope_granted",
                      serde_json::json!({"request_id": "r1", "plugin_id": "kimi-code",
                                         "granted_by": "operator", "via": "operator_session",
                                         "decision_reason": "fine"})),
            ],
            T0 + 120,
        );
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].kind, LedgerKind::ScopeRequest);
        assert_eq!(rows[0].status, LedgerStatus::Approved);
        assert_eq!(rows[0].subject.as_deref(), Some("/repo/x"));
    }

    /// The society floor is the widest permission surface on the box. Its attempts and
    /// completions must each remain independently reviewable: folding an intent into its
    /// terminal fact would make a failed durable mutation disappear from the ledger.
    #[test]
    fn society_floor_intents_and_terminal_facts_are_distinct_permission_rows() {
        let rows = project(
            &[
                entry(1, 0, "society_floor_intent",
                      serde_json::json!({"path": "/repo/shared"})),
                entry(2, 10, "society_floor_added",
                      serde_json::json!({"path": "/repo/shared", "intent": "hash1"})),
                entry(3, 20, "society_floor_remove_intent",
                      serde_json::json!({"path": "/repo/shared"})),
                entry(4, 30, "society_floor_removed",
                      serde_json::json!({"path": "/repo/shared", "intent": "hash3"})),
            ],
            T0 + 60,
        );
        assert_eq!(rows.len(), 4, "every intent and terminal fact is its own row");
        assert!(rows.iter().all(|r| r.kind == LedgerKind::Permission));
        assert!(rows.iter().all(|r| r.status == LedgerStatus::Recorded));
        assert!(rows.iter().all(|r| r.subject.as_deref() == Some("/repo/shared")));
        assert_eq!(
            rows.iter().map(|r| r.event_type.as_str()).collect::<Vec<_>>(),
            vec![
                "society_floor_removed",
                "society_floor_remove_intent",
                "society_floor_added",
                "society_floor_intent",
            ],
            "newest-first projection must retain all four event identities"
        );
    }

    /// Events that annotate an existing row rather than creating one. They are governance events —
    /// the ledger must read them — but a claim with no ask in the window is not itself a row.
    const ANNOTATION_ONLY: &[&str] = &["gate_escalation_claimed", "gate_escalation_corroborated"];

    #[test]
    fn every_declared_governance_event_is_actually_projected() {
        // A drift guard: adding a name to GOVERNANCE_EVENTS without a match arm would silently
        // filter entries in and then drop them, producing a ledger that under-reports.
        let mut missing = Vec::new();
        for ev in GOVERNANCE_EVENTS.iter().filter(|e| !ANNOTATION_ONLY.contains(e)) {
            let data = serde_json::json!({
                "escalation_id": "x", "request_id": "x", "plugin_id": "p",
                "change": "c", "path": "/repo/x", "expires_at": T0 + 3600,
            });
            if project(&[entry(1, 0, ev, data)], T0).is_empty() {
                missing.push(*ev);
            }
        }
        assert!(missing.is_empty(), "declared but not projected: {missing:?}");
    }
}

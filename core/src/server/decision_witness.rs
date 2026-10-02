//! ONE decision witness for every verdict — one-gate stage A (docs/one-gate-convergence-plan.md).
//!
//! `hestia_witness_decision` was the deny/warn recorder (Sprint E). The common orchestrator needs
//! the same door for `allow`, and needs it to be receipt-validated: a gate may permit a
//! consequential act only once its decision witness is COMMITTED, and "the RPC returned
//! something" is not a commit — every tool `Err`, including a failed chain append, reaches the
//! wire as a successful MCP result carrying `_hestia_error` (handler.rs `call_tool`).
//!
//! This module holds the parts of that contract that are decisions rather than plumbing, so they
//! are testable without a daemon:
//!
//! - **Where each verdict lands.** `warn`/`deny` stay `policy_decision`, unchanged. `allow` is
//!   its own event type, [`ALLOW_EVENT`]. It must NOT be a `policy_decision`: that type is in
//!   `DERIVATION_GOVERNANCE_EVENT_TYPES`, the sparse half of derivation's window that "must not
//!   be crowded out", and allow volume is outcome volume. Several readers also take every
//!   `policy_decision` row as a refusal (`governed_acts`, the retry match, calib_export's gate
//!   negatives, the sibling-role count). An allow written there would move trust scores and push
//!   real denies out of the window.
//! - **What each verdict charges.** `allow` charges nothing, as the daemon's own gate charges
//!   nothing on allow (`risk_magnitude` 0.0 in `tool_query_policy`) and as scope attestation
//!   argues ("letting each one count would let a member farm trust"). `warn`/`deny` keep their
//!   existing Unclassified 0.2/0.5.
//! - **One verdict, one row; one action, one charge.** When the gate names an action that
//!   already has a committed decision row for the same member (the society-safety path:
//!   `begin_action` → `query_policy` writes its own `policy_decision`), the gate's witness of
//!   the SAME verdict is that row: its hash is handed back, nothing is appended or charged. A
//!   DIFFERENT verdict is appended as evidence but is not charged when the key was already
//!   charged. See [`DecisionLedger`] for the rule and its bound.

use serde_json::Value;
use std::collections::{HashMap, VecDeque};
use uuid::Uuid;

/// Event type for a witnessed `allow`. Reserved: `hestia_request_witness` cannot forge it.
pub const ALLOW_EVENT: &str = "policy_allow";
/// Event type for a witnessed `warn`/`deny` — the pre-existing type, unchanged.
pub const DECISION_EVENT: &str = "policy_decision";
/// Bound on the caller-reported core digest stored on the row (a full sha256 is 64).
pub const CORE_DIGEST_MAX: usize = 128;

/// The three final verdicts a gate can reach. Anything else is refused before any append.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Allow,
    Warn,
    Deny,
}

impl Verdict {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "allow" => Some(Self::Allow),
            "warn" => Some(Self::Warn),
            "deny" => Some(Self::Deny),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::Warn => "warn",
            Self::Deny => "deny",
        }
    }

    pub fn event_type(self) -> &'static str {
        match self {
            Self::Allow => ALLOW_EVENT,
            Self::Warn | Self::Deny => DECISION_EVENT,
        }
    }

    /// The gate-risk charge for this verdict. `None` = no reputation delta at all.
    pub fn risk_magnitude(self) -> Option<f64> {
        match self {
            Self::Allow => None,
            Self::Warn => Some(0.2),
            Self::Deny => Some(0.5),
        }
    }
}

/// The decision rows witnessed for one `(member, action_id)` and the one that charged, if any.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LedgerEntry {
    /// The chain hash of the decision row whose reputation movement was applied. At most one.
    pub charged_by: Option<String>,
    /// Every committed decision row for this key, in arrival order, with its verdict.
    pub rows: Vec<(Verdict, String)>,
}

/// ONE CHARGE PER (MEMBER, ACTION). The rule this ledger enforces, whatever the order the
/// verdicts arrive in and whoever writes them (the daemon's own `query_policy`, or a seat's
/// `hestia_witness_decision` naming the action):
///
/// - a decision row is charged only if it COMMITTED (decision reputation follows the committed
///   decision witness — no row, no movement);
/// - and only if no earlier committed row for the same member and action already charged;
/// - a later row for the same key is still appended when it is a different verdict (it is
///   evidence of what the member experienced — a warn-rollout seat's `warn` beside the daemon's
///   `deny`), but it carries `charge_held_by` naming the row that charged, and moves nothing;
/// - the same verdict again for the same key is a duplicate delivery: answered with the row
///   that already witnesses it, nothing appended, nothing charged.
///
/// First committed charge wins, so a seat `warn` (Unclassified 0.2) that lands before the
/// daemon's `deny` (Conduct 0.5) holds the charge at 0.2. Upgrading would need a compensating
/// delta, and gate deltas only ever lower trust; one bounded charge is the invariant chosen.
///
/// A decision with no `action_id` has no key and is not deduplicated (a deployed refusal shim,
/// or a decision reached before any action began), exactly as before.
///
/// Held in RAM and bounded to [`DECISION_LEDGER_CAP`] keys, oldest evicted first. That cap is a
/// time horizon: the decision witnesses for one action arrive within the same tool call
/// (seconds), and the cap holds far more than a day of gate decisions at fleet rates. A daemon
/// restart empties it, as it empties the in-flight action table the same keys come from.
#[derive(Debug, Clone)]
pub struct DecisionLedger {
    keys: HashMap<(String, Uuid), LedgerEntry>,
    order: VecDeque<(String, Uuid)>,
    cap: usize,
}

/// See [`DecisionLedger`]: the number of `(member, action_id)` keys kept.
pub const DECISION_LEDGER_CAP: usize = 16_384;

impl Default for DecisionLedger {
    fn default() -> Self {
        Self::with_cap(DECISION_LEDGER_CAP)
    }
}

impl DecisionLedger {
    pub fn with_cap(cap: usize) -> Self {
        Self { keys: HashMap::new(), order: VecDeque::new(), cap: cap.max(1) }
    }

    pub fn entry(&self, member: &str, action_id: Uuid) -> Option<&LedgerEntry> {
        self.keys.get(&(member.to_string(), action_id))
    }

    /// The committed row that already witnesses this verdict for this member and action.
    pub fn existing_row(&self, member: &str, action_id: Uuid, verdict: Verdict) -> Option<&str> {
        self.entry(member, action_id)?
            .rows
            .iter()
            .find(|(v, _)| *v == verdict)
            .map(|(_, h)| h.as_str())
    }

    /// The row whose charge already covers this member and action, if one does. `Some` means a
    /// new row for the same key must not be charged.
    pub fn charge_holder(&self, member: &str, action_id: Uuid) -> Option<&str> {
        self.entry(member, action_id)?.charged_by.as_deref()
    }

    /// Record a COMMITTED decision row. Call only after the append returned its entry.
    pub fn record_row(&mut self, member: &str, action_id: Uuid, verdict: Verdict, hash: &str) {
        let key = (member.to_string(), action_id);
        if !self.keys.contains_key(&key) {
            while self.order.len() >= self.cap {
                if let Some(old) = self.order.pop_front() {
                    self.keys.remove(&old);
                }
            }
            self.order.push_back(key.clone());
        }
        self.keys.entry(key).or_default().rows.push((verdict, hash.to_string()));
    }

    /// Record that `hash`'s reputation movement was applied. Never overwrites an earlier holder:
    /// the first applied charge is the one charge.
    pub fn record_charge(&mut self, member: &str, action_id: Uuid, hash: &str) {
        if let Some(e) = self.keys.get_mut(&(member.to_string(), action_id)) {
            if e.charged_by.is_none() {
                e.charged_by = Some(hash.to_string());
            }
        }
    }
}

/// `core_digest` as stored: a string, bounded. Absent or non-string → not stored.
///
/// Lenient on purpose: the deployed refusal shims already send this key (as a hex digest or the
/// literal "unknown"), and refusing their deny records over its format would lose the deny.
pub fn bounded_core_digest(v: Option<&Value>) -> Option<String> {
    v.and_then(Value::as_str)
        .map(|s| s.chars().take(CORE_DIGEST_MAX).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn every_verdict_parses_and_nothing_else_does() {
        for (s, v) in [("allow", Verdict::Allow), ("warn", Verdict::Warn), ("deny", Verdict::Deny)] {
            assert_eq!(Verdict::parse(s), Some(v));
            assert_eq!(v.as_str(), s);
        }
        for bad in ["", "Allow", "escalate", "no-verdict", "permit", "deny "] {
            assert_eq!(Verdict::parse(bad), None, "{bad:?} must be refused");
        }
    }

    #[test]
    fn allow_is_never_a_policy_decision_row() {
        assert_eq!(Verdict::Allow.event_type(), ALLOW_EVENT);
        assert_ne!(ALLOW_EVENT, DECISION_EVENT);
        assert_eq!(Verdict::Warn.event_type(), DECISION_EVENT);
        assert_eq!(Verdict::Deny.event_type(), DECISION_EVENT);
    }

    /// The window guard, stated as a test: an allow row must not enter derivation's sparse
    /// governance half, or allow volume crowds the denies it exists to keep.
    #[test]
    fn allow_rows_stay_out_of_the_governance_window() {
        assert!(!crate::derivation::DERIVATION_GOVERNANCE_EVENT_TYPES.contains(&ALLOW_EVENT));
        assert!(!crate::derivation::DERIVATION_EVENT_TYPES.contains(&ALLOW_EVENT));
        assert!(crate::derivation::DERIVATION_GOVERNANCE_EVENT_TYPES.contains(&DECISION_EVENT));
    }

    #[test]
    fn allow_charges_nothing_and_refusals_keep_their_weights() {
        assert_eq!(Verdict::Allow.risk_magnitude(), None);
        assert_eq!(Verdict::Warn.risk_magnitude(), Some(0.2));
        assert_eq!(Verdict::Deny.risk_magnitude(), Some(0.5));
    }

    #[test]
    fn the_ledger_answers_only_the_same_member_action_and_verdict() {
        let mut l = DecisionLedger::default();
        let a = Uuid::new_v4();
        l.record_row("codex", a, Verdict::Deny, "h1");
        assert_eq!(l.existing_row("codex", a, Verdict::Deny), Some("h1"));
        assert_eq!(l.existing_row("codex", a, Verdict::Warn), None, "other verdict");
        assert_eq!(l.existing_row("kimi-code", a, Verdict::Deny), None, "other member");
        assert_eq!(l.existing_row("codex", Uuid::new_v4(), Verdict::Deny), None, "other action");
    }

    /// The charging rule in isolation: a row is a charge holder only once its charge was
    /// recorded, the first holder is never overwritten, and the key is (member, action).
    #[test]
    fn at_most_one_charge_per_member_and_action_in_either_order() {
        for (first, second) in [(Verdict::Deny, Verdict::Warn), (Verdict::Warn, Verdict::Deny)] {
            let mut l = DecisionLedger::default();
            let a = Uuid::new_v4();
            assert_eq!(l.charge_holder("codex", a), None);
            l.record_row("codex", a, first, "h-first");
            assert_eq!(l.charge_holder("codex", a), None, "a row alone is not a charge");
            l.record_charge("codex", a, "h-first");
            assert_eq!(l.charge_holder("codex", a), Some("h-first"));
            l.record_row("codex", a, second, "h-second");
            l.record_charge("codex", a, "h-second");
            assert_eq!(l.charge_holder("codex", a), Some("h-first"), "first charge holds");
            assert_eq!(l.entry("codex", a).unwrap().rows.len(), 2, "both rows are kept");
            assert_eq!(l.charge_holder("kimi-code", a), None, "another member is its own key");
        }
        let mut l = DecisionLedger::default();
        l.record_charge("codex", Uuid::new_v4(), "h-orphan");
        assert!(l.keys.is_empty(), "a charge with no committed row records nothing");
    }

    #[test]
    fn the_ledger_is_bounded_oldest_first() {
        let mut l = DecisionLedger::with_cap(2);
        let (a, b, c) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        l.record_row("m", a, Verdict::Deny, "ha");
        l.record_row("m", b, Verdict::Deny, "hb");
        l.record_row("m", b, Verdict::Warn, "hb2");
        l.record_row("m", c, Verdict::Deny, "hc");
        assert_eq!(l.existing_row("m", a, Verdict::Deny), None, "oldest key evicted");
        assert_eq!(l.existing_row("m", b, Verdict::Warn), Some("hb2"));
        assert_eq!(l.existing_row("m", c, Verdict::Deny), Some("hc"));
        assert_eq!(l.keys.len(), 2);
    }

    #[test]
    fn core_digest_is_bounded_and_never_refused() {
        assert_eq!(bounded_core_digest(Some(&json!("unknown"))), Some("unknown".into()));
        let long = "a".repeat(500);
        assert_eq!(bounded_core_digest(Some(&json!(long))).unwrap().len(), CORE_DIGEST_MAX);
        assert_eq!(bounded_core_digest(Some(&json!(null))), None);
        assert_eq!(bounded_core_digest(Some(&json!(7))), None);
        assert_eq!(bounded_core_digest(None), None);
    }
}

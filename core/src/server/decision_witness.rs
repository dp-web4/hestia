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

/// What a decision row's one charge IS, derived from the row's own committed `event_data` — so
/// the charge applied live and the charge settled after a restart are the same charge.
#[derive(Debug, Clone, PartialEq)]
pub struct ChargeSpec {
    /// Gate-risk magnitude: warn 0.2, deny 0.5.
    pub magnitude: f64,
    /// The daemon's own gate evaluation (Conduct) vs a caller-reported gate decision
    /// (Unclassified). A daemon row carries no `adjudicator`; a witnessed one always does.
    pub conduct: bool,
    pub role_lct: String,
    pub tool_name: String,
    pub rule_id: String,
    /// The reason the delta row carries: `gate:<decision>` (daemon) or
    /// `gate:<decision> (<adjudicator>)` (witnessed) — exactly what each path wrote before.
    pub reason: String,
}

impl ChargeSpec {
    /// The charge a committed decision row carries, or `None` for one that charges nothing
    /// (an allow, or a row with no recognisable verdict).
    pub fn from_row(data: &Value) -> Option<Self> {
        let verdict = Verdict::parse(data.get("decision")?.as_str()?)?;
        let magnitude = verdict.risk_magnitude()?;
        let s = |k: &str| data.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        let adjudicator = data.get("adjudicator").and_then(Value::as_str);
        Some(Self {
            magnitude,
            conduct: adjudicator.is_none(),
            role_lct: s("role_lct"),
            tool_name: s("tool_name"),
            rule_id: s("rule_id"),
            reason: match adjudicator {
                None => format!("gate:{}", verdict.as_str()),
                Some(a) => format!("gate:{} ({a})", verdict.as_str()),
            },
        })
    }
}

/// One committed decision row on a ledger key.
#[derive(Debug, Clone, PartialEq)]
pub struct LedgerRow {
    pub verdict: Verdict,
    pub hash: String,
    /// The charge this row carries if it is the key's charging row. `None` for an allow.
    pub charge: Option<ChargeSpec>,
}

/// The decision rows witnessed for one `(member, action_id)` and the one that charged, if any.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct LedgerEntry {
    /// The chain hash of the decision row whose reputation movement was applied. At most one,
    /// and never overwritten: this is the idempotency key for the key's one charge.
    pub charged_by: Option<String>,
    /// Every committed decision row for this key, in arrival order.
    pub rows: Vec<LedgerRow>,
}

impl LedgerEntry {
    /// The key's OWED charge: its first committed chargeable row, while nothing has charged.
    /// `None` when the charge is settled, or when no committed row charges anything.
    pub fn owed(&self) -> Option<(&str, &ChargeSpec)> {
        if self.charged_by.is_some() {
            return None;
        }
        self.rows.iter().find_map(|r| r.charge.as_ref().map(|c| (r.hash.as_str(), c)))
    }
}

/// EXACTLY ONE CHARGE PER (MEMBER, ACTION), ONE ROW PER VERDICT. The rule this ledger enforces,
/// whatever order the verdicts arrive in and whoever writes them (the daemon's own
/// `query_policy`, or a seat's `hestia_witness_decision` naming the action):
///
/// - **One verdict, one row.** The same verdict again for the same member and action — a seat
///   retry, or the daemon asked to rule the same action twice — is answered with the committed
///   row that already witnesses it. Nothing is appended.
/// - **Decision reputation follows the committed decision witness.** Only a committed row can
///   carry the charge; no row, no movement.
/// - **The key's charge belongs to its first committed chargeable (warn/deny) row**, and is
///   applied once. A later different verdict is appended as evidence with `charge_held_by`
///   naming the charging row, and moves nothing.
/// - **An owed charge is settled, not lost.** If the row committed but the trust write failed,
///   the charge stays OWED on the key; the next decision call on that key (a retry, a different
///   verdict, the daemon's repeat ruling) settles it once. `charged_by` is set only on a
///   successful settle and never overwritten, and every settle runs under the state lock, so two
///   settles cannot both apply it.
///
/// First committed chargeable row wins, so a seat `warn` (Unclassified 0.2) that lands before
/// the daemon's `deny` (Conduct 0.5) holds the charge at 0.2. Upgrading would need a
/// compensating delta, and gate deltas only ever lower trust.
///
/// A decision with no `action_id` has no key and is not deduplicated (a deployed refusal shim,
/// or a decision reached before any action began), exactly as before.
///
/// **Across a restart** the ledger is rebuilt by [`rehydrate`]: decision rows carrying an
/// `action_id` from the last [`DECISION_LEDGER_REPLAY_HOURS`] of chain (at most
/// [`DECISION_LEDGER_CAP`] rows), and which of them charged from the settle record
/// ([`SETTLED_FILE`]) plus every committed row's `charge_held_by`. A late witness for a
/// pre-restart action therefore finds its row and its charge state.
///
/// Held in RAM bounded to [`DECISION_LEDGER_CAP`] keys, oldest evicted first.
#[derive(Debug, Clone)]
pub struct DecisionLedger {
    keys: HashMap<(String, Uuid), LedgerEntry>,
    order: VecDeque<(String, Uuid)>,
    cap: usize,
}

/// See [`DecisionLedger`]: the number of `(member, action_id)` keys kept, and the most decision
/// rows the startup replay reads.
pub const DECISION_LEDGER_CAP: usize = 16_384;
/// How far back the startup replay reaches. The witnesses for one action arrive within the same
/// tool call (seconds); a day covers a late retry across any deploy restart, and anything older
/// cannot be a retry of a live decision.
pub const DECISION_LEDGER_REPLAY_HOURS: i64 = 24;
/// The durable record of applied decision charges (`<home>/decision-charges.jsonl`), one line
/// per settled key: `{"member", "action_id", "row"}`. Written after the trust write succeeds.
pub const SETTLED_FILE: &str = "decision-charges.jsonl";

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
            .find(|r| r.verdict == verdict)
            .map(|r| r.hash.as_str())
    }

    /// The row whose charge was APPLIED for this member and action, if one was. `Some` means a
    /// new row for the same key must not be charged.
    pub fn charge_holder(&self, member: &str, action_id: Uuid) -> Option<&str> {
        self.entry(member, action_id)?.charged_by.as_deref()
    }

    /// The key's owed charge (row hash + what to charge), cloned for the settle.
    pub fn owed(&self, member: &str, action_id: Uuid) -> Option<(String, ChargeSpec)> {
        self.entry(member, action_id)?
            .owed()
            .map(|(h, c)| (h.to_string(), c.clone()))
    }

    /// Record a COMMITTED decision row. Call only after the append returned its entry.
    pub fn record_row(
        &mut self,
        member: &str,
        action_id: Uuid,
        verdict: Verdict,
        hash: &str,
        charge: Option<ChargeSpec>,
    ) {
        let key = (member.to_string(), action_id);
        if !self.keys.contains_key(&key) {
            while self.order.len() >= self.cap {
                if let Some(old) = self.order.pop_front() {
                    self.keys.remove(&old);
                }
            }
            self.order.push_back(key.clone());
        }
        let e = self.keys.entry(key).or_default();
        if !e.rows.iter().any(|r| r.hash == hash) {
            e.rows.push(LedgerRow { verdict, hash: hash.to_string(), charge });
        }
    }

    /// Record that `hash`'s charge was applied. Returns false (and changes nothing) when the key
    /// is unknown or already has a holder: the first applied charge is the one charge.
    pub fn record_charge(&mut self, member: &str, action_id: Uuid, hash: &str) -> bool {
        match self.keys.get_mut(&(member.to_string(), action_id)) {
            Some(e) if e.charged_by.is_none() => {
                e.charged_by = Some(hash.to_string());
                true
            }
            _ => false,
        }
    }
}

/// Append one settled charge to the durable settle record. Best effort: a failed write is
/// reported, and costs only the restart case (the key would read as owed after a restart).
pub fn persist_settled(path: &std::path::Path, member: &str, action_id: Uuid, row: &str) {
    use std::io::Write;
    let line = serde_json::json!({"member": member, "action_id": action_id.to_string(), "row": row});
    let res = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .and_then(|mut f| writeln!(f, "{line}"));
    if let Err(e) = res {
        eprintln!("hestia: decision charge settle record not written ({}): {e}", path.display());
    }
}

/// Rebuild the ledger at startup from the chain and the settle record. See [`DecisionLedger`].
///
/// A failed chain read is reported, never silent, and yields an empty ledger — the pre-ledger
/// behaviour, not a refusal to start.
pub fn rehydrate(
    chain: &crate::storage::chain::SqliteChainStore,
    settled: &std::path::Path,
) -> DecisionLedger {
    let cutoff = (chrono::Utc::now() - chrono::Duration::hours(DECISION_LEDGER_REPLAY_HOURS))
        .to_rfc3339();
    struct Replayed {
        member: String,
        action_id: Uuid,
        verdict: Verdict,
        hash: String,
        charge: Option<ChargeSpec>,
        held_by: Option<String>,
    }
    let rows = chain.scan_recent(
        Some(&cutoff),
        Some(&[DECISION_EVENT, ALLOW_EVENT]),
        DECISION_LEDGER_CAP as u64,
        |r| {
            let data: Value = serde_json::from_str(r.event_data).ok()?;
            let action_id = Uuid::parse_str(data.get("action_id")?.as_str()?).ok()?;
            Some(Replayed {
                member: data.get("plugin_id")?.as_str()?.to_string(),
                action_id,
                verdict: Verdict::parse(data.get("decision")?.as_str()?)?,
                hash: r.hash.to_string(),
                charge: ChargeSpec::from_row(&data),
                held_by: data.get("charge_held_by").and_then(Value::as_str).map(str::to_string),
            })
        },
    );
    let mut ledger = DecisionLedger::default();
    let rows = match rows {
        Ok(r) => r,
        Err(e) => {
            eprintln!("hestia: decision ledger replay failed, starting empty: {e}");
            return ledger;
        }
    };
    // Newest-first from the store; replay in arrival order so "first committed row" holds.
    for r in rows.iter().rev() {
        ledger.record_row(&r.member, r.action_id, r.verdict, &r.hash, r.charge.clone());
    }
    // A committed row that names the row holding its key's charge is chain-witnessed proof that
    // the charge was applied.
    for r in &rows {
        if let Some(h) = &r.held_by {
            ledger.record_charge(&r.member, r.action_id, h);
        }
    }
    if let Ok(text) = std::fs::read_to_string(settled) {
        for line in text.lines() {
            let Ok(v) = serde_json::from_str::<Value>(line) else { continue };
            let (Some(m), Some(a), Some(h)) = (
                v.get("member").and_then(Value::as_str),
                v.get("action_id").and_then(Value::as_str).and_then(|a| Uuid::parse_str(a).ok()),
                v.get("row").and_then(Value::as_str),
            ) else {
                continue;
            };
            ledger.record_charge(m, a, h);
        }
    }
    ledger
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

    fn spec(v: Verdict) -> Option<ChargeSpec> {
        ChargeSpec::from_row(&json!({"decision": v.as_str(), "role_lct": "r", "tool_name": "Bash"}))
    }

    #[test]
    fn a_charge_spec_is_read_from_the_committed_row() {
        let daemon = ChargeSpec::from_row(&json!({"decision": "deny", "rule_id": "safety.rm"})).unwrap();
        assert_eq!((daemon.magnitude, daemon.conduct), (0.5, true));
        assert_eq!(daemon.reason, "gate:deny");
        assert_eq!(daemon.rule_id, "safety.rm");
        let seat = ChargeSpec::from_row(&json!({"decision": "warn", "adjudicator": "plugin-gate:codex"}))
            .unwrap();
        assert_eq!((seat.magnitude, seat.conduct), (0.2, false));
        assert_eq!(seat.reason, "gate:warn (plugin-gate:codex)");
        assert_eq!(ChargeSpec::from_row(&json!({"decision": "allow"})), None);
        assert_eq!(ChargeSpec::from_row(&json!({})), None);
    }

    /// Exactly once: a committed chargeable row with no applied charge is OWED, and stays owed
    /// until a charge is recorded; after that nothing is owed and the holder never moves.
    #[test]
    fn an_owed_charge_stays_owed_until_settled_once() {
        let mut l = DecisionLedger::default();
        let a = Uuid::new_v4();
        l.record_row("codex", a, Verdict::Allow, "h-allow", spec(Verdict::Allow));
        assert_eq!(l.owed("codex", a), None, "an allow owes nothing");
        l.record_row("codex", a, Verdict::Warn, "h-warn", spec(Verdict::Warn));
        l.record_row("codex", a, Verdict::Deny, "h-deny", spec(Verdict::Deny));
        let (h, c) = l.owed("codex", a).unwrap();
        assert_eq!(h, "h-warn", "the first committed chargeable row owns the charge");
        assert_eq!(c.magnitude, 0.2);
        assert!(l.record_charge("codex", a, "h-warn"));
        assert_eq!(l.owed("codex", a), None);
        assert!(!l.record_charge("codex", a, "h-deny"), "a second settle changes nothing");
        assert_eq!(l.charge_holder("codex", a), Some("h-warn"));
        l.record_row("codex", a, Verdict::Warn, "h-warn", spec(Verdict::Warn));
        assert_eq!(l.entry("codex", a).unwrap().rows.len(), 3, "re-recording a row is a no-op");
    }

    #[test]
    fn the_ledger_answers_only_the_same_member_action_and_verdict() {
        let mut l = DecisionLedger::default();
        let a = Uuid::new_v4();
        l.record_row("codex", a, Verdict::Deny, "h1", spec(Verdict::Deny));
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
            l.record_row("codex", a, first, "h-first", spec(first));
            assert_eq!(l.charge_holder("codex", a), None, "a row alone is not a charge");
            l.record_charge("codex", a, "h-first");
            assert_eq!(l.charge_holder("codex", a), Some("h-first"));
            l.record_row("codex", a, second, "h-second", spec(second));
            l.record_charge("codex", a, "h-second");
            assert_eq!(l.charge_holder("codex", a), Some("h-first"), "first charge holds");
            assert_eq!(l.entry("codex", a).unwrap().rows.len(), 2, "both rows are kept");
            assert_eq!(l.charge_holder("kimi-code", a), None, "another member is its own key");
        }
        let mut l = DecisionLedger::default();
        assert!(!l.record_charge("codex", Uuid::new_v4(), "h-orphan"));
        assert!(l.keys.is_empty(), "a charge with no committed row records nothing");
    }

    #[test]
    fn the_ledger_is_bounded_oldest_first() {
        let mut l = DecisionLedger::with_cap(2);
        let (a, b, c) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        l.record_row("m", a, Verdict::Deny, "ha", spec(Verdict::Deny));
        l.record_row("m", b, Verdict::Deny, "hb", spec(Verdict::Deny));
        l.record_row("m", b, Verdict::Warn, "hb2", spec(Verdict::Warn));
        l.record_row("m", c, Verdict::Deny, "hc", spec(Verdict::Deny));
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

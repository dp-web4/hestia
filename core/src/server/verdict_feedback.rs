//! A verdict is FEEDBACK, addressed to the level where it is true.
//!
//! A refusal already names its rule, its reason and (in the gate's remedy table) the doors
//! that remain open. That makes a verdict information, not only a wall. What it did not say
//! is WHICH LEVEL of the actor's work the verdict is about, and that omission has a cost:
//!
//! - A verdict addressed to the **act** ("not this route; here is another") is the right
//!   answer when the goal behind the act is still valid. It is the wrong answer when the goal's
//!   premise is false, or the goal is already achieved: then every door offered is one more
//!   route to a goal that should have been closed, and the refusals become a search procedure.
//! - A verdict on an **invariant** that still offers a door manufactures repeated attempts. If
//!   no route exists, the honest envelope says so structurally, by carrying no doors at all.
//!
//! This module holds that schema as a type, so the daemon's own gate (`hestia_query_policy`)
//! and a witnessed gate decision (`hestia_witness_decision`) carry the same envelope on the
//! wire and on the chain. Every field is additive and defaulted: a row or reply written before
//! this existed reads as `level: act`, `serves: "unknown"`, no premise check, no repeat, no
//! effects — exactly what it meant then.
//!
//! **Levels** (where the feedback is TRUE):
//!
//! | level       | meaning                                                         | doors           |
//! |-------------|-----------------------------------------------------------------|-----------------|
//! | `act`       | this route is not permitted; the goal may still be valid        | yes             |
//! | `goal`      | the goal's premise is false, or it is achieved / out of reach   | usually none    |
//! | `law`       | the rule itself is the subject (dispute it, read it, change it) | the governed path |
//! | `invariant` | innate and non-negotiable: no route exists                      | **none, enforced** |
//!
//! **What is inferred and what is not.** `level` is classified from the rule (conservatively:
//! only the innate secret-egress rule is `invariant`, the governance-surface rule is `law`, and
//! everything else is `act`) unless the deciding party states a level. `repeat_of` is computed
//! from the witness record. `serves` is the caller's to state at `hestia_begin_action`.
//! `premise_check` and `effects` are never inferred here: they are set by a ruling member, or by
//! a later feature that can actually establish them, and passed through as given.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, VecDeque};

/// What `serves` reads when the caller stated nothing. Honest absence, never a guess.
pub const SERVES_UNKNOWN: &str = "unknown";
/// Bound on a caller-supplied `serves` id. A goal or question id, not a document.
pub const SERVES_MAX: usize = 200;
/// Bound on each caller-supplied evidence reference in a `premise_check`, and on their count.
pub const EVIDENCE_REF_MAX: usize = 512;
pub const EVIDENCE_MAX: usize = 32;
/// Bound on caller-supplied doors on one verdict.
pub const DOORS_MAX: usize = 16;

/// Rules whose refusal is INVARIANT: innate, not relaxed by warn-mode, trust or any grant, with
/// no route to the act at all. Kept deliberately short.
///
/// `egress.secret` is the gate's innate secret-egress rule. Its remedy in
/// `plugins/_shared/hestia_gate_core.py` already names no door (a leaked secret has no undo, so
/// no request makes it fine); the parity test below pins that the two stay in agreement.
///
/// NOT here, on purpose:
/// - `gate.self_access` (editing the governance surface). The gate marks it `innate` because no
///   grant relaxes it, but a route DOES exist: a witnessed human approval through
///   `hestia_gate_escalation_open` / `_claim`. A verdict that said "no route exists" would be
///   false, and stripping that door would remove the governed path. The rule itself is the
///   subject, which is the `law` level.
/// - the fail-closed infrastructure refusals (`gate.degraded`, `society.unreachable`, ...). They
///   are also `innate` in the gate's sense, but they are not judgements of the act at all; the
///   act may be fine once the referee answers. They stay `act`.
/// - the daemon's own preset rules (`deny-secret-files`, destructive commands, ...). An operator
///   grant can substitute the preset, so they are relaxable, which an invariant is not.
pub const INVARIANT_RULES: &[&str] = &["egress.secret"];

/// Rules whose refusal is about the LAW itself (the governance surface), not about the act.
pub const LAW_RULES: &[&str] = &["gate.self_access"];

/// Where a verdict's feedback is true. Ordered from the narrowest node of the actor's goal tree
/// to the widest constraint.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum FeedbackLevel {
    /// This route is not permitted; the goal may still be valid. The default, and what every
    /// verdict written before this schema meant.
    #[default]
    Act,
    /// The goal's premise is false, the goal is already achieved, or it is out of reach.
    Goal,
    /// The rule itself is the subject.
    Law,
    /// Innate and non-negotiable. No route exists, so the verdict carries no doors.
    Invariant,
}

impl FeedbackLevel {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "act" => Some(Self::Act),
            "goal" => Some(Self::Goal),
            "law" => Some(Self::Law),
            "invariant" => Some(Self::Invariant),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Act => "act",
            Self::Goal => "goal",
            Self::Law => "law",
            Self::Invariant => "invariant",
        }
    }
}

/// The level a refusal under `rule_id` is addressed to, absent a stated one. Conservative: see
/// [`INVARIANT_RULES`] and [`LAW_RULES`] for what is classified and why; everything else is `act`.
pub fn level_for_rule(rule_id: &str) -> FeedbackLevel {
    if INVARIANT_RULES.contains(&rule_id) {
        FeedbackLevel::Invariant
    } else if LAW_RULES.contains(&rule_id) {
        FeedbackLevel::Law
    } else {
        FeedbackLevel::Act
    }
}

/// THE DOORS THE DAEMON OFFERS FOLLOW THE LEVEL (NOVA's hold on 93611e46). Until then every enforced
/// deny offered the same three: modify the request, ask the operator, appeal. At the `law` level
/// (the governance surface, `gate.self_access`) two of those are false routes: "modify the request"
/// there means reaching the governed file another way, which the operating law tells a member NOT to
/// do, and a gate escalation is not appealable. The one real route is the governance escalation the
/// operator decides. An `invariant` offers none (and `with_doors` drops any).
pub fn daemon_doors(level: FeedbackLevel) -> Vec<Door> {
    match level {
        FeedbackLevel::Invariant => Vec::new(),
        FeedbackLevel::Law => vec![Door::new("escalate", Some("hestia_gate_escalation_open"), Some("operator"))],
        FeedbackLevel::Act | FeedbackLevel::Goal => vec![
            Door::new("modify_request", None, None),
            Door::new("escalate", None, Some("operator")),
            Door::new("appeal", Some("hestia_appeal"), None),
        ],
    }
}

/// The level a verdict carries, given its rule and an optionally STATED level (by the gate that
/// decided, or a ruling member). A rule the daemon classifies as invariant stays invariant
/// whatever is stated: an invariant cannot be argued down to a level that offers doors.
pub fn resolve_level(rule_id: &str, stated: Option<FeedbackLevel>) -> FeedbackLevel {
    let derived = level_for_rule(rule_id);
    if derived == FeedbackLevel::Invariant {
        return derived;
    }
    stated.unwrap_or(derived)
}

/// The status of the premise of the goal the act served.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PremiseStatus {
    Refuted,
    Holds,
    #[default]
    Unknown,
}

/// What a premise check means for the goal the act served.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum GoalEffect {
    /// The premise is false: close the goal.
    Abandon,
    /// The goal is already satisfied: close it as achieved.
    Achieved,
    /// The goal stands in a narrower or different form.
    Rescope,
}

/// Goal-level feedback: whether the premise of the goal the act served still holds, with
/// evidence. Set by whoever can establish it (a ruling member, an observation); never inferred
/// by the daemon.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct PremiseCheck {
    #[serde(default)]
    pub status: PremiseStatus,
    /// References to the evidence (chain hashes, page ids, observations).
    #[serde(default)]
    pub evidence: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub goal_effect: Option<GoalEffect>,
}

/// One remaining route after an act-level (or law-level) verdict.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Door {
    /// What kind of route: `modify_request`, `escalate`, `appeal`, `request_scope`, `wait`, ...
    pub kind: String,
    /// The tool that opens it, when there is one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool: Option<String>,
    /// Who decides it, when that is known (e.g. `operator`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub to: Option<String>,
}

impl Door {
    pub fn new(kind: &str, tool: Option<&str>, to: Option<&str>) -> Self {
        Self {
            kind: kind.to_string(),
            tool: tool.map(str::to_string),
            to: to.map(str::to_string),
        }
    }
}

/// Positive or negative consequences the verdict carries (reputation, scope). Passed through as
/// given: the daemon's own reputation movement is reported by the existing receipt fields, and
/// this is where a ruling member (or a later feature) states what a verdict counted for.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Effects {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reputation: Option<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scope_change: Option<Value>,
}

/// The feedback half of a verdict envelope. Rides beside the existing fields (`decision`,
/// `rule_id`, `reason`, ...) under one additive key, `feedback`, on both the MCP reply and the
/// witnessed row.
///
/// **An invariant carries no doors, by construction.** `level` and `doors` are private: the only
/// ways to set them ([`VerdictFeedback::set_level`], [`VerdictFeedback::with_doors`], and
/// deserialization) strip the doors of an invariant verdict. There is no way to build, or to read
/// back off the wire or the chain, an invariant verdict that offers a route.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(from = "VerdictFeedbackWire")]
pub struct VerdictFeedback {
    level: FeedbackLevel,
    /// The goal or question id the act was for, as the caller stated it at begin. `"unknown"`
    /// when nothing was stated.
    pub serves: String,
    /// The act's digest: who did what to which target. The key `repeat_of` is computed on.
    /// Absent on rows written before this schema.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub act: Option<String>,
    doors: Vec<Door>,
    pub premise_check: Option<PremiseCheck>,
    /// WHO STATED `premise_check` AND `effects` (NOVA's hold on 93611e46): `"caller"` when the party
    /// that sent the witness supplied them. The daemon passes them through and does not certify them,
    /// and a reader of the receipt or the row must be able to tell. Absent when neither was stated.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stated_by: Option<String>,
    /// The chain hash of the first witnessed verdict on record for the identical act, decision and
    /// rule by the same member IN THE SAME DECISION CONTEXT (policy generation, role, enforcement),
    /// when the bounded index still holds one. A best-effort HINT: an evicted or not-yet-replayed key
    /// yields none, so its absence never means "first ever" (NOVA's hold on 93611e46).
    pub repeat_of: Option<String>,
    pub effects: Option<Effects>,
}

/// The permissive on-the-wire shape: every field optional, so a row or reply with none of them
/// (everything written before this schema) reads as the default.
#[derive(Deserialize)]
struct VerdictFeedbackWire {
    #[serde(default)]
    level: FeedbackLevel,
    #[serde(default)]
    serves: Option<String>,
    #[serde(default)]
    act: Option<String>,
    #[serde(default)]
    doors: Vec<Door>,
    #[serde(default)]
    premise_check: Option<PremiseCheck>,
    #[serde(default)]
    stated_by: Option<String>,
    #[serde(default)]
    repeat_of: Option<String>,
    #[serde(default)]
    effects: Option<Effects>,
}

impl From<VerdictFeedbackWire> for VerdictFeedback {
    fn from(w: VerdictFeedbackWire) -> Self {
        let mut f = VerdictFeedback::new(w.serves.as_deref());
        f.act = w.act;
        f.premise_check = w.premise_check;
        f.stated_by = w.stated_by;
        f.repeat_of = w.repeat_of;
        f.effects = w.effects;
        f.set_level(w.level);
        f.with_doors(w.doors)
    }
}

impl Default for VerdictFeedback {
    fn default() -> Self {
        Self::new(None)
    }
}

impl VerdictFeedback {
    /// An act-level verdict with no doors, serving `serves` (or `"unknown"`).
    pub fn new(serves: Option<&str>) -> Self {
        Self {
            level: FeedbackLevel::Act,
            serves: normalize_serves(serves),
            act: None,
            doors: Vec::new(),
            premise_check: None,
            stated_by: None,
            repeat_of: None,
            effects: None,
        }
    }

    pub fn level(&self) -> FeedbackLevel {
        self.level
    }

    pub fn doors(&self) -> &[Door] {
        &self.doors
    }

    /// Set the level. Setting `invariant` removes every door. Returns how many were removed.
    pub fn set_level(&mut self, level: FeedbackLevel) -> usize {
        self.level = level;
        if level == FeedbackLevel::Invariant {
            let n = self.doors.len();
            self.doors.clear();
            n
        } else {
            0
        }
    }

    /// Offer these doors. An invariant verdict accepts none: they are dropped.
    pub fn with_doors(mut self, doors: Vec<Door>) -> Self {
        if self.level != FeedbackLevel::Invariant {
            self.doors = doors;
        }
        self
    }

    /// Read the feedback a witnessed row (or a reply) carries under `feedback`. A row written
    /// before this schema has none, and reads as the default (act, serves unknown).
    pub fn from_row(row: &Value) -> Self {
        row.get("feedback")
            .and_then(|f| serde_json::from_value(f.clone()).ok())
            .unwrap_or_default()
    }

    pub fn to_value(&self) -> Value {
        serde_json::to_value(self).unwrap_or(Value::Null)
    }
}

/// `serves` as stored: trimmed, and `"unknown"` when absent or empty.
pub fn normalize_serves(serves: Option<&str>) -> String {
    match serves.map(str::trim) {
        Some(s) if !s.is_empty() => s.to_string(),
        _ => SERVES_UNKNOWN.to_string(),
    }
}

/// Validate a caller-supplied `serves`. `Ok(None)` when absent or null; `Err` (with the reason)
/// when it was SENT and is unusable. A sent key is refused, never silently dropped.
pub fn parse_serves(v: Option<&Value>) -> Result<Option<String>, String> {
    match v {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(s)) => {
            let t = s.trim();
            if t.chars().count() > SERVES_MAX {
                Err(format!(
                    "serves must be at most {SERVES_MAX} characters (a goal or question id)"
                ))
            } else if t.chars().any(char::is_control) {
                Err("serves must not contain control characters".to_string())
            } else if t.is_empty() {
                Ok(None)
            } else {
                Ok(Some(t.to_string()))
            }
        }
        Some(_) => Err("serves must be a string (the goal or question id the act is for)".into()),
    }
}

/// Validate the caller-supplied feedback fields a witnessed decision may carry (`level`,
/// `doors`, `premise_check`, `effects`). `Err` names the first unusable one.
pub struct StatedFeedback {
    pub level: Option<FeedbackLevel>,
    pub doors: Vec<Door>,
    pub premise_check: Option<PremiseCheck>,
    pub effects: Option<Effects>,
}

pub fn parse_stated(args: &Value) -> Result<StatedFeedback, (&'static str, String)> {
    let level = match args.get("level") {
        None | Some(Value::Null) => None,
        Some(v) => match v.as_str().and_then(FeedbackLevel::parse) {
            Some(l) => Some(l),
            None => {
                return Err((
                    "level",
                    "level must be one of act, goal, law, invariant".into(),
                ));
            }
        },
    };
    let doors: Vec<Door> = match args.get("doors") {
        None | Some(Value::Null) => Vec::new(),
        Some(v) => match serde_json::from_value::<Vec<Door>>(v.clone()) {
            Ok(d) if d.len() <= DOORS_MAX => d,
            Ok(_) => return Err(("doors", format!("at most {DOORS_MAX} doors"))),
            Err(e) => {
                return Err((
                    "doors",
                    format!("doors must be a list of {{kind, tool?, to?}}: {e}"),
                ));
            }
        },
    };
    let premise_check = match args.get("premise_check") {
        None | Some(Value::Null) => None,
        Some(v) => match serde_json::from_value::<PremiseCheck>(v.clone()) {
            Ok(p)
                if p.evidence.len() <= EVIDENCE_MAX
                    && p.evidence
                        .iter()
                        .all(|e| e.chars().count() <= EVIDENCE_REF_MAX) =>
            {
                Some(p)
            }
            Ok(_) => {
                return Err((
                    "premise_check",
                    format!(
                        "premise_check.evidence: at most {EVIDENCE_MAX} references of at most \
                         {EVIDENCE_REF_MAX} characters"
                    ),
                ));
            }
            Err(e) => {
                return Err((
                    "premise_check",
                    format!(
                        "premise_check must be {{status: refuted|holds|unknown, evidence: [..], \
                         goal_effect?: abandon|achieved|rescope}}: {e}"
                    ),
                ));
            }
        },
    };
    let effects = match args.get("effects") {
        None | Some(Value::Null) => None,
        Some(v) => match serde_json::from_value::<Effects>(v.clone()) {
            Ok(e) => Some(e),
            Err(e) => {
                return Err((
                    "effects",
                    format!("effects must be {{reputation?, scope_change?}}: {e}"),
                ));
            }
        },
    };
    Ok(StatedFeedback {
        level,
        doors,
        premise_check,
        effects,
    })
}

/// The digest of an act label: who (member), what (tool), to which target, attempting what.
/// Hashed so the key can sit on the chain without carrying the attempted text twice. The input is
/// redacted, so two different original inputs can collapse to one label; `repeat_of` is a hint,
/// never a proof that the original acts were identical.
pub fn act_digest(
    member: &str,
    tool_name: &str,
    target: Option<&str>,
    attempted: Option<&str>,
) -> String {
    use sha2::{Digest, Sha256};
    let canon = serde_json::json!([
        member,
        tool_name,
        target.unwrap_or(""),
        attempted.unwrap_or("")
    ]);
    let mut h = Sha256::new();
    h.update(canon.to_string().as_bytes());
    format!("{:x}", h.finalize())
}

/// The identity of a verdict for repeat purposes: the same member, act, decision and rule, decided in
/// the same context. The fifth element is that context, canonical.
pub type RepeatKey = (String, String, String, String, String);

/// THE DECISION CONTEXT IS PART OF "THE SAME VERDICT" (NOVA's hold on 93611e46; Codex's controls
/// `e74786fb`). A deny under policy generation 1 is not a repeat of one under generation 2, nor one
/// under another role, enforcement state, or gate generation: the law changed, so the earlier verdict
/// is not an answer. Read from the row's OWN fields (`policy_version`, `role_lct`, `enforced`,
/// `core_digest`), absent ones as null, and the live paths pass exactly the values they write, so a
/// key rebuilt from the chain at startup equals the key computed live. Missing generation is unknown,
/// not proof of sameness: `repeat_of` is a bounded same-normalized/redacted-attempt hint, never proof
/// that the original inputs or law were identical.
pub fn decision_context(row: &Value) -> String {
    let f = |k: &str| row.get(k).cloned().unwrap_or(Value::Null);
    serde_json::json!([f("policy_version"), f("role_lct"), f("enforced"), f("core_digest")]).to_string()
}

pub fn repeat_key(member: &str, act: &str, decision: &str, rule_id: &str, context: &Value) -> RepeatKey {
    (
        member.to_string(),
        act.to_string(),
        decision.to_string(),
        rule_id.to_string(),
        decision_context(context),
    )
}

/// How many distinct verdict keys the repeat index keeps, and the most rows the startup replay
/// reads.
pub const REPEAT_INDEX_CAP: usize = 16_384;

/// The first witnessed verdict per `(member, act, decision, rule, context)`. This is how an identical
/// act is answered by reference (`repeat_of`). Built from committed rows only, and rebuilt from the
/// chain at startup, so it is a projection of the witness record and not a second source of truth.
/// Bounded; oldest keys evicted first.
#[derive(Debug, Clone)]
pub struct RepeatIndex {
    first: HashMap<RepeatKey, String>,
    order: VecDeque<RepeatKey>,
    cap: usize,
}

impl Default for RepeatIndex {
    fn default() -> Self {
        Self::with_cap(REPEAT_INDEX_CAP)
    }
}

impl RepeatIndex {
    pub fn with_cap(cap: usize) -> Self {
        Self {
            first: HashMap::new(),
            order: VecDeque::new(),
            cap: cap.max(1),
        }
    }

    /// The first committed verdict for this key, if one is on record.
    pub fn earlier(&self, key: &RepeatKey) -> Option<&str> {
        self.first.get(key).map(String::as_str)
    }

    /// Record a COMMITTED verdict row. The first row for a key is kept; later ones are repeats.
    pub fn record(&mut self, key: RepeatKey, hash: &str) {
        if self.first.contains_key(&key) {
            return;
        }
        while self.order.len() >= self.cap {
            if let Some(old) = self.order.pop_front() {
                self.first.remove(&old);
            }
        }
        self.order.push_back(key.clone());
        self.first.insert(key, hash.to_string());
    }

    pub fn len(&self) -> usize {
        self.first.len()
    }

    pub fn is_empty(&self) -> bool {
        self.first.is_empty()
    }
}

/// The repeat key a committed decision row carries, read back from the row itself: the same
/// reading the live path makes, so the index rebuilt at startup equals the running one. `None`
/// for a row written before this schema (no `feedback.act`).
pub fn row_repeat_key(data: &Value) -> Option<RepeatKey> {
    let member = data.get("plugin_id")?.as_str()?;
    let decision = data.get("decision")?.as_str()?;
    let rule = data.get("rule_id").and_then(Value::as_str).unwrap_or("");
    let act = data.get("feedback")?.get("act")?.as_str()?;
    Some(repeat_key(member, act, decision, rule, data))
}

/// Rebuild the repeat index from the chain at startup. A failed read is reported and yields an
/// empty index (repeats go unreferenced until they recur), never a refusal to start.
pub fn rehydrate(chain: &crate::storage::chain::SqliteChainStore) -> RepeatIndex {
    use super::decision_witness::{ALLOW_EVENT, DECISION_EVENT};
    let rows = chain.scan_recent(
        None,
        Some(&[DECISION_EVENT, ALLOW_EVENT]),
        REPEAT_INDEX_CAP as u64,
        |r| {
            let data: Value = serde_json::from_str(r.event_data).ok()?;
            Some((row_repeat_key(&data)?, r.hash.to_string()))
        },
    );
    let mut index = RepeatIndex::default();
    match rows {
        // Newest-first from the store; replay oldest-first so the FIRST verdict is kept.
        Ok(rows) => {
            for (k, h) in rows.into_iter().rev() {
                index.record(k, &h);
            }
        }
        Err(e) => eprintln!("hestia: verdict repeat index replay failed, starting empty: {e}"),
    }
    index
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_law_level_deny_offers_only_the_governance_escalation() {
        let law = daemon_doors(FeedbackLevel::Law);
        assert_eq!(law.len(), 1, "{law:?}");
        assert_eq!(law[0].kind, "escalate");
        assert_eq!(law[0].tool.as_deref(), Some("hestia_gate_escalation_open"));
        assert_eq!(law[0].to.as_deref(), Some("operator"));
        assert!(!law.iter().any(|d| d.kind == "modify_request" || d.kind == "appeal"),
            "no route around the governed file, and a gate escalation is not appealable");
        assert!(daemon_doors(FeedbackLevel::Invariant).is_empty());
        let act: Vec<_> = daemon_doors(FeedbackLevel::Act).into_iter().map(|d| d.kind).collect();
        assert_eq!(act, ["modify_request", "escalate", "appeal"]);
        assert_eq!(level_for_rule("gate.self_access"), FeedbackLevel::Law,
            "the rule the law doors are for is classified law");
    }

    #[test]
    fn stated_by_round_trips_and_is_absent_by_default() {
        let mut f = VerdictFeedback::new(None);
        assert!(f.to_value().get("stated_by").is_none());
        f.stated_by = Some("caller".into());
        let back: VerdictFeedback = serde_json::from_value(f.to_value()).unwrap();
        assert_eq!(back.stated_by.as_deref(), Some("caller"));
    }

    fn doors() -> Vec<Door> {
        vec![
            Door::new("modify_request", None, None),
            Door::new("appeal", Some("hestia_appeal"), None),
        ]
    }

    /// The rule the whole schema turns on: an invariant verdict carries no doors, however it is
    /// built — by setter, by builder, or read back off the wire or the chain.
    #[test]
    fn an_invariant_verdict_carries_no_doors_by_any_route() {
        // Doors offered first, then the level set: the doors are removed, and the count says so.
        let mut f = VerdictFeedback::new(None).with_doors(doors());
        assert_eq!(f.doors().len(), 2);
        assert_eq!(f.set_level(FeedbackLevel::Invariant), 2);
        assert!(f.doors().is_empty());

        // Level first, then doors offered: refused.
        let mut g = VerdictFeedback::new(None);
        g.set_level(FeedbackLevel::Invariant);
        let g = g.with_doors(doors());
        assert!(g.doors().is_empty());

        // Read off the wire with doors present: they do not survive deserialization.
        let wire =
            json!({"level": "invariant", "doors": [{"kind": "appeal", "tool": "hestia_appeal"}]});
        let h: VerdictFeedback = serde_json::from_value(wire).unwrap();
        assert_eq!(h.level(), FeedbackLevel::Invariant);
        assert!(h.doors().is_empty());
        assert_eq!(h.to_value()["doors"], json!([]));

        // And an act-level verdict keeps its doors.
        let a: VerdictFeedback =
            serde_json::from_value(json!({"level": "act", "doors": [{"kind": "wait"}]})).unwrap();
        assert_eq!(a.doors().len(), 1);
    }

    /// A stated level cannot argue an invariant rule down to a level that offers doors.
    #[test]
    fn an_invariant_rule_cannot_be_stated_down() {
        assert_eq!(
            resolve_level("egress.secret", Some(FeedbackLevel::Act)),
            FeedbackLevel::Invariant
        );
        assert_eq!(
            resolve_level("egress.secret", None),
            FeedbackLevel::Invariant
        );
        assert_eq!(resolve_level("mrh.path", None), FeedbackLevel::Act);
        assert_eq!(
            resolve_level("mrh.path", Some(FeedbackLevel::Goal)),
            FeedbackLevel::Goal
        );
        assert_eq!(resolve_level("gate.self_access", None), FeedbackLevel::Law);
        // Infrastructure refusals and the daemon's own preset rules are act-level.
        for r in [
            "gate.degraded",
            "society.unreachable",
            "deny-secret-files",
            "deny-destructive-commands",
            "",
        ] {
            assert_eq!(level_for_rule(r), FeedbackLevel::Act, "{r}");
        }
    }

    /// Backward compatibility: a row or reply written before this schema has no `feedback`, and
    /// an envelope with an empty or partial `feedback` reads with every default.
    #[test]
    fn old_json_deserializes_with_defaults() {
        let old_row = json!({
            "tool_name": "Bash", "target": "rm -rf /x", "plugin_id": "kimi", "decision": "deny",
            "enforced": true, "rule_id": "deny-destructive-commands", "reason": "r",
        });
        let f = VerdictFeedback::from_row(&old_row);
        assert_eq!(f, VerdictFeedback::default());
        assert_eq!(f.level(), FeedbackLevel::Act);
        assert_eq!(f.serves, SERVES_UNKNOWN);
        assert!(f.doors().is_empty() && f.premise_check.is_none() && f.repeat_of.is_none());
        assert!(f.effects.is_none() && f.act.is_none());
        assert_eq!(
            row_repeat_key(&old_row),
            None,
            "an old row has no act key and is not indexed"
        );

        let empty: VerdictFeedback = serde_json::from_value(json!({})).unwrap();
        assert_eq!(empty, VerdictFeedback::default());
        // A premise check with only a status reads the rest as defaults.
        let p: PremiseCheck = serde_json::from_value(json!({"status": "refuted"})).unwrap();
        assert_eq!(
            p,
            PremiseCheck {
                status: PremiseStatus::Refuted,
                evidence: vec![],
                goal_effect: None
            }
        );
    }

    #[test]
    fn full_envelope_round_trips() {
        let mut f = VerdictFeedback::new(Some("q000042")).with_doors(doors());
        f.act = Some(act_digest("m", "Bash", Some("ls"), None));
        f.repeat_of = Some("abc".into());
        f.premise_check = Some(PremiseCheck {
            status: PremiseStatus::Refuted,
            evidence: vec!["hash1".into()],
            goal_effect: Some(GoalEffect::Achieved),
        });
        f.effects = Some(Effects {
            reputation: Some(json!({"delta": 0.1})),
            scope_change: None,
        });
        let v = f.to_value();
        assert_eq!(v["serves"], json!("q000042"));
        assert_eq!(v["premise_check"]["goal_effect"], json!("achieved"));
        assert_eq!(VerdictFeedback::from_row(&json!({"feedback": v})), f);
    }

    #[test]
    fn serves_is_validated_not_dropped() {
        assert_eq!(parse_serves(None), Ok(None));
        assert_eq!(parse_serves(Some(&json!(null))), Ok(None));
        assert_eq!(parse_serves(Some(&json!("  "))), Ok(None));
        assert_eq!(parse_serves(Some(&json!(" q1 "))), Ok(Some("q1".into())));
        assert!(parse_serves(Some(&json!(7))).is_err());
        assert!(parse_serves(Some(&json!("x".repeat(SERVES_MAX + 1)))).is_err());
        assert!(parse_serves(Some(&json!("a\nb"))).is_err());
        assert_eq!(normalize_serves(None), SERVES_UNKNOWN);
    }

    #[test]
    fn stated_feedback_is_validated() {
        assert!(parse_stated(&json!({"level": "wall"})).is_err());
        assert!(parse_stated(&json!({"doors": "appeal"})).is_err());
        assert!(parse_stated(&json!({"premise_check": {"status": "maybe"}})).is_err());
        let s = parse_stated(&json!({
            "level": "goal",
            "premise_check": {"status": "refuted", "evidence": ["h"], "goal_effect": "abandon"},
            "effects": {"scope_change": {"granted": "/x"}},
        }))
        .unwrap();
        assert_eq!(s.level, Some(FeedbackLevel::Goal));
        assert_eq!(
            s.premise_check.unwrap().goal_effect,
            Some(GoalEffect::Abandon)
        );
        assert!(s.effects.is_some());
    }

    #[test]
    fn the_repeat_index_keeps_the_first_verdict_and_is_bounded() {
        let mut idx = RepeatIndex::with_cap(2);
        let ctx = serde_json::json!({});
        let k = |n: &str| repeat_key("m", n, "deny", "r", &ctx);
        idx.record(k("a"), "h1");
        idx.record(k("a"), "h2");
        assert_eq!(idx.earlier(&k("a")), Some("h1"));
        // Same act, different decision or rule: not a repeat.
        assert_eq!(idx.earlier(&repeat_key("m", "a", "warn", "r", &ctx)), None);
        assert_eq!(idx.earlier(&repeat_key("m", "a", "deny", "other", &ctx)), None);
        assert_eq!(idx.earlier(&repeat_key("other", "a", "deny", "r", &ctx)), None);
        let gen2 = serde_json::json!({"policy_version": 2});
        assert_eq!(idx.earlier(&repeat_key("m", "a", "deny", "r", &gen2)), None, "another law generation");
        idx.record(k("b"), "h3");
        idx.record(k("c"), "h4");
        assert_eq!(idx.len(), 2);
        assert_eq!(idx.earlier(&k("a")), None, "oldest evicted");
    }

    #[test]
    fn act_digest_separates_fields() {
        // Joining fields with a separator would collide these; the JSON array does not.
        assert_ne!(
            act_digest("m", "a", Some("b c"), None),
            act_digest("m", "a b", Some("c"), None)
        );
        assert_eq!(
            act_digest("m", "Bash", Some("ls"), None),
            act_digest("m", "Bash", Some("ls"), None)
        );
    }

    /// The daemon's invariant table and the gate's remedy table must agree: every rule this
    /// module calls invariant names no door in the gate's remedy text either. Read from the Python
    /// gate's source, as `channel.rs` reads `FORBIDDEN_DEFAULT`.
    #[test]
    fn invariant_rules_have_no_door_in_the_gate_remedy_table() {
        let src = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../plugins/_shared/hestia_gate_core.py"
        ))
        .expect("the Python gate core is in this repo");
        for rule in INVARIANT_RULES {
            let key = format!("\"{rule}\": Remedy(");
            let start = src
                .find(&key)
                .unwrap_or_else(|| panic!("no remedy registered for {rule}"));
            let body = &src[start..start + src[start..].find("\n    ),").expect("remedy end")];
            // The entry's tools tuple is its last line; an invariant's is empty.
            let tools_line = body.lines().last().unwrap().trim();
            assert_eq!(
                tools_line, "(),",
                "invariant rule {rule} names a door in the gate: {tools_line}"
            );
            assert!(
                !body.contains("hestia_"),
                "invariant rule {rule}'s remedy text names a tool"
            );
        }
        for rule in LAW_RULES {
            assert!(
                src.contains(&format!("\"{rule}\": Remedy(")),
                "no remedy registered for {rule}"
            );
        }
    }
}

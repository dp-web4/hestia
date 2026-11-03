//! Review controls for the proposed repeat reference. Synthetic data only.
//!
//! These negative controls propose the stronger interpretation that a repeat
//! reference represents the same decision context. They should fail until the
//! key carries that context; an explicitly weaker, accurately labelled meaning
//! is a separate design option and would require different assertions.

use hestia::server::verdict_feedback::{row_repeat_key, RepeatIndex};
use serde_json::{json, Value};

fn verdict(policy_version: u64, role: &str, enforced: bool) -> Value {
    json!({
        "plugin_id": "synthetic-member",
        "decision": "deny",
        "rule_id": "synthetic.rule",
        "policy_version": policy_version,
        "role_lct": role,
        "enforced": enforced,
        "feedback": {"act": "synthetic-digest"}
    })
}

#[test]
fn unchanged_decision_context_preserves_repeat_key() {
    let first = verdict(1, "role:one", true);
    let same = verdict(1, "role:one", true);
    assert_eq!(row_repeat_key(&first), row_repeat_key(&same));
}

#[test]
fn changed_policy_generation_must_not_claim_same_decision_context() {
    let before = verdict(1, "role:one", true);
    let after = verdict(2, "role:one", true);
    assert_ne!(row_repeat_key(&before), row_repeat_key(&after));
}

#[test]
fn changed_role_or_enforcement_must_not_claim_same_decision_context() {
    let before = verdict(1, "role:one", true);
    for after in [verdict(1, "role:two", true), verdict(1, "role:one", false)] {
        assert_ne!(row_repeat_key(&before), row_repeat_key(&after));
    }
}

#[test]
fn replaying_a_row_window_can_forget_a_still_live_distinct_key() {
    let a = row_repeat_key(&verdict(1, "role:one", true)).unwrap();
    let mut other = verdict(1, "role:one", true);
    other["feedback"]["act"] = json!("other-digest");
    let b = row_repeat_key(&other).unwrap();
    let mut live = RepeatIndex::with_cap(2);
    live.record(a.clone(), "row-a");
    live.record(b.clone(), "row-b-first");
    live.record(b.clone(), "row-b-repeat");
    assert_eq!(live.earlier(&a), Some("row-a"));
    // Simulate replay over the final two rows, with an equal key capacity.
    let mut replay = RepeatIndex::with_cap(2);
    replay.record(b.clone(), "row-b-first");
    replay.record(b, "row-b-repeat");
    assert_eq!(replay.earlier(&a), None);
}

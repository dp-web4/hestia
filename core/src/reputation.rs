//! P3a-local — hestia-side `ReputationDelta` construction from trust movement.
//!
//! Every mutation of an entity's `EntityTrust` is captured as a **role-scoped
//! `web4_core::r6::ReputationDelta`** — the canonical fleet interop currency — by
//! diffing the tensor before/after the update. The emitted delta is therefore
//! *exactly what hestia applied* (no re-derivation, no weight duplication).
//!
//! This is the local half of the trust-tensor bridge
//! (`designs/2026-07-01-trust-tensor-bridge.md`): it produces + logs deltas that
//! are **ready to emit** to the hub's §5.3 projection (web4 #430) the moment a
//! member-emit path exists (R7 §5.1 P1 / opening `record_reputation`). Until then
//! the local `reputation-deltas.jsonl` is both the ready-to-emit queue and a
//! `calib`-ready reputation stream. The warn/deny gate wiring is the first source.

use std::collections::HashMap;
use std::path::Path;

use chrono::{DateTime, Utc};
use web4_core::r6::{ReputationDelta, SovereignStrength, TensorDelta};
use web4_trust_core::EntityTrust;

/// v1 single-role placeholder. Real per-role scoping (RFC #403) needs the
/// constellation-role definition; until then every constellation entity acts in
/// one role, giving valid-but-degenerate `(subject, role)` pairs. See the design.
pub const V1_CONSTELLATION_ROLE: &str = "role:constellation:member";

/// The default sink filename under `<hestia_home>`.
pub const SINK_FILE: &str = "reputation-deltas.jsonl";

/// Context carried into an emitted delta (what caused the trust change).
pub struct RepContext<'a> {
    pub role_lct: &'a str,
    pub action_type: &'a str,
    pub action_target: &'a str,
    pub action_id: &'a str,
    pub reason: &'a str,
}

fn dim_delta(from: f64, to: f64) -> Option<TensorDelta> {
    let change = to - from;
    if change.abs() < 1e-9 {
        None
    } else {
        Some(TensorDelta {
            change,
            from_value: from,
            to_value: to,
        })
    }
}

/// Build a role-scoped `ReputationDelta` from the before/after of an `EntityTrust`
/// mutation — the exact per-dimension change hestia applied. Only dimensions that
/// actually moved are included; returns `None` for a no-op mutation (so no-op
/// updates never emit a delta). Dimension keys match the hub's `trust_dim`/
/// `value_dim` (`talent`/`training`/`temperament`, `valuation`/`veracity`/
/// `validity`) so the hub folds them without silently dropping any.
pub fn delta_from_change(
    subject_lct: &str,
    ctx: &RepContext,
    before: &EntityTrust,
    after: &EntityTrust,
    ts: DateTime<Utc>,
) -> Option<ReputationDelta> {
    // P3b: `EntityTrust` now holds the canonical `web4_core` tensors; read the
    // root scores through the convenience getters (`talent()`, `valuation()`, …).
    // The before/after deltas are numerically identical to the pre-migration
    // fields, so the emitted `ReputationDelta` is unchanged.
    let mut t3_delta = HashMap::new();
    if let Some(d) = dim_delta(before.talent(), after.talent()) {
        t3_delta.insert("talent".to_string(), d);
    }
    if let Some(d) = dim_delta(before.training(), after.training()) {
        t3_delta.insert("training".to_string(), d);
    }
    if let Some(d) = dim_delta(before.temperament(), after.temperament()) {
        t3_delta.insert("temperament".to_string(), d);
    }

    let mut v3_delta = HashMap::new();
    if let Some(d) = dim_delta(before.valuation(), after.valuation()) {
        v3_delta.insert("valuation".to_string(), d);
    }
    if let Some(d) = dim_delta(before.veracity(), after.veracity()) {
        v3_delta.insert("veracity".to_string(), d);
    }
    if let Some(d) = dim_delta(before.validity(), after.validity()) {
        v3_delta.insert("validity".to_string(), d);
    }

    if t3_delta.is_empty() && v3_delta.is_empty() {
        return None;
    }

    Some(ReputationDelta {
        subject_lct: subject_lct.to_string(),
        role_lct: ctx.role_lct.to_string(),
        action_type: ctx.action_type.to_string(),
        action_target: ctx.action_target.to_string(),
        action_id: ctx.action_id.to_string(),
        rule_triggered: String::new(),
        reason: ctx.reason.to_string(),
        t3_delta,
        v3_delta,
        // web4 #457: interim `Placeholder` populate (the serde/fail-closed
        // default). Threading a real per-emitter strength through `connect`
        // (canonical `role_lct` + hardware attestation) is the larger queued
        // C-series follow-up; this only unblocks the path-dep field addition.
        sovereign_strength: SovereignStrength::default(),
        contributing_factors: Vec::new(),
        witnesses: Vec::new(),
        timestamp: ts,
    })
}

/// Append a delta as one JSON line to the local sink. Best-effort: a logging
/// failure must NEVER break a trust update, so errors are swallowed (the sink is
/// a projection, not the source of truth — the witness chain is).
pub fn log_delta(sink: &Path, delta: &ReputationDelta) {
    use std::io::Write;
    if let Ok(line) = serde_json::to_string(delta) {
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(sink)
        {
            let _ = writeln!(f, "{line}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx() -> RepContext<'static> {
        RepContext {
            role_lct: V1_CONSTELLATION_ROLE,
            action_type: "policy_gate",
            action_target: "Bash",
            action_id: "a1",
            reason: "gate:deny",
        }
    }

    #[test]
    fn diff_captures_moved_dimensions_only() {
        let before = EntityTrust::new("plugin:x");
        let mut after = before.clone();
        after.update_from_outcome(false, 0.5); // a negative outcome moves the tensor

        let d = delta_from_change("plugin:x", &ctx(), &before, &after, Utc::now())
            .expect("a real mutation yields a delta");
        assert_eq!(d.subject_lct, "plugin:x");
        assert_eq!(d.role_lct, V1_CONSTELLATION_ROLE);
        // At least one t3 dimension moved, and every recorded key is a real dim
        // (so the hub won't silently drop it).
        assert!(!d.t3_delta.is_empty());
        for k in d.t3_delta.keys() {
            assert!(matches!(k.as_str(), "talent" | "training" | "temperament"), "unknown t3 key {k}");
        }
        // The recorded change equals to - from, exactly what hestia applied.
        for td in d.t3_delta.values() {
            assert!((td.change - (td.to_value - td.from_value)).abs() < 1e-12);
        }
    }

    #[test]
    fn no_op_mutation_yields_no_delta() {
        let before = EntityTrust::new("plugin:x");
        let after = before.clone(); // nothing moved
        assert!(delta_from_change("plugin:x", &ctx(), &before, &after, Utc::now()).is_none());
    }
}

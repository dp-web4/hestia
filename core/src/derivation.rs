//! Derived trust — `v3-derived-v1` (Stage 2 of the T3-from-V3 arc).
//!
//! The value proposition is AUDITABLE trust: every displayed score must be a
//! pure function over witnessed evidence, with receipts (score → formula →
//! chain pointers → acts). This module computes that function at READ TIME —
//! nothing here is stored, so the derivation can improve and be recomputed
//! over the same immutable events.
//!
//! v1 scope (plan: private-context/plans/t3-from-v3-synthesis-2026-07-24.md):
//! - **Adjudicated V3** (validity/veracity/valuation): read straight off the
//!   `#adjudicated` grain — that grain is derivation-compliant by construction
//!   (folded ONLY from witnessed not-the-actor adjudications, Stage 1).
//! - **Temperament**: derived here from governance-response conduct in the
//!   chain — deny events and what the actor did next. Predicates below.
//! - **Training / Talent**: NOT derived in v1 (Training needs distinct
//!   semantics from adjudicated validity; Talent is criterion-gated). They
//!   render unmeasured — honest-unmeasured beats fabricated precision.
//!
//! Temperament predicates (all on existing chain fields; synthesis amendment 4
//! — accountable disagreement, not obedience):
//! - deny        = `policy_decision{decision:"deny", enforced:true}` for the grain.
//! - retry-after-deny (score 0.0): within `RETRY_WINDOW` of a deny, another
//!   policy_decision from the SAME session with the same tool AND matching
//!   payload hash / target — re-running the blocked act instead of adapting.
//! - comply-after-deny (score 0.7): a deny with no retry match in the window.
//! - ask-after-deny (score 1.0): reserved for witnessed escalation/appeal
//!   events referencing the deny; until hooks emit them, 0.7 is the ceiling —
//!   documented, not faked.

use chrono::{DateTime, Duration, Utc};
use serde::Serialize;
use serde_json::Value;

use crate::storage::chain::ChainEntry;

pub const DERIVATION_VERSION: &str = "v3-derived-v1";
const RETRY_WINDOW_MINUTES: i64 = 10;
/// How much chain the derivation scans (same cap as the dashboard stats scan).
pub const DERIVATION_SCAN: u64 = 10_000;

/// One piece of evidence backing a derived dimension.
#[derive(Debug, Clone, Serialize)]
pub struct Evidence {
    pub chain_position: u64,
    pub hash: String,
    pub event_type: String,
    pub timestamp: DateTime<Utc>,
    /// What this event contributed (e.g. "comply-after-deny 0.7",
    /// "adjudication validity upheld 1.0 (review)").
    pub contribution: String,
    /// External pointer carried by the event, when present (PR, forum, commit).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reference: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct DerivedDimension {
    /// None = unmeasured (zero qualifying evidence). Never a prior.
    pub score: Option<f64>,
    pub observations: u64,
    pub formula: String,
    pub evidence: Vec<Evidence>,
}

#[derive(Debug, Clone, Serialize)]
pub struct DerivedTrust {
    pub derivation_version: String,
    pub plugin_id: String,
    pub role_lct: String,
    pub generated_at: DateTime<Utc>,
    pub temperament: DerivedDimension,
    pub validity: DerivedDimension,
    pub veracity: DerivedDimension,
    pub valuation: DerivedDimension,
    /// Display level derived from the ABOVE (never from the legacy scalar):
    /// "unmeasured" until any dimension has evidence; then low/medium/high by
    /// the mean of measured dimension scores (<0.4 / <0.7 / >=0.7).
    pub level: String,
}

/// The canonical fold used for derived observations — the same EMA the
/// tensors use (`alpha = 0.5 / (1 + n/10)`), applied over scores in chain
/// order from the 0.5 prior. Returns None when there are no observations.
fn ema_fold(scores: &[f64]) -> Option<f64> {
    if scores.is_empty() {
        return None;
    }
    let mut value = 0.5;
    for (n, s) in scores.iter().enumerate() {
        let alpha = 0.5 / (1.0 + (n as f64) / 10.0);
        value = alpha * s + (1.0 - alpha) * value;
    }
    Some(value)
}

fn entry_str<'a>(e: &'a ChainEntry, key: &str) -> Option<&'a str> {
    e.event_data.get(key).and_then(Value::as_str)
}

/// Derive temperament + collect adjudication evidence for one grain from a
/// chain window (oldest-first order is established internally).
pub fn derive(
    plugin_id: &str,
    role_lct: &str,
    window: &[ChainEntry],
) -> DerivedTrust {
    let mut entries: Vec<&ChainEntry> = window.iter().collect();
    entries.sort_by_key(|e| e.chain_position);

    // ---- Temperament: governance-response conduct ----
    let is_grain = |e: &ChainEntry| {
        entry_str(e, "plugin_id") == Some(plugin_id)
            && entry_str(e, "role_lct").map_or(true, |r| r == role_lct)
    };
    // Probe hygiene (dp 2026-07-24): synthetic verification sessions (gate
    // e2e tests etc.) generate denies that are conduct of the TESTER, not the
    // member. Excluded by explicit marker; the exclusion is disclosed in the
    // formula text so a receipt reader knows the rule.
    let is_probe = |e: &ChainEntry| {
        entry_str(e, "session_id").is_some_and(|sid| {
            sid.contains("test") || sid.contains("probe") || sid.contains("verify")
                || sid.contains("e2e") || sid.contains("debug")
        })
    };
    let denies: Vec<&&ChainEntry> = entries
        .iter()
        .filter(|e| {
            e.event_type == "policy_decision"
                && entry_str(e, "decision") == Some("deny")
                && e.event_data.get("enforced").and_then(Value::as_bool) != Some(false)
                && is_grain(e)
                && !is_probe(e)
        })
        .collect();
    let mut temperament_scores = Vec::new();
    let mut temperament_evidence = Vec::new();
    for deny in &denies {
        let window_end = deny.timestamp + Duration::minutes(RETRY_WINDOW_MINUTES);
        let deny_sig = (
            entry_str(deny, "session_id").unwrap_or(""),
            entry_str(deny, "tool_name").unwrap_or(""),
            entry_str(deny, "payload_sha256").unwrap_or(""),
            entry_str(deny, "target").unwrap_or(""),
        );
        let retried = entries.iter().any(|e| {
            e.chain_position > deny.chain_position
                && e.timestamp <= window_end
                && e.event_type == "policy_decision"
                && is_grain(e)
                && entry_str(e, "session_id").unwrap_or("") == deny_sig.0
                && entry_str(e, "tool_name").unwrap_or("") == deny_sig.1
                && ((!deny_sig.2.is_empty()
                    && entry_str(e, "payload_sha256").unwrap_or("") == deny_sig.2)
                    || (!deny_sig.3.is_empty()
                        && entry_str(e, "target").unwrap_or("") == deny_sig.3))
        });
        // Ask/appeal-after-deny (1.0): a witnessed `appeal` event referencing
        // this deny's hash — challenging the boundary through the accountable
        // channel instead of re-running or silently routing around. This is
        // the TOP of the temperament scale (amendment 4: accountable
        // disagreement, not obedience).
        let appealed = entries.iter().any(|e| {
            e.event_type == "appeal"
                && entry_str(e, "deny_hash") == Some(deny.hash.as_str())
                && is_grain(e)
        });
        let (score, label) = if appealed {
            (1.0, "appeal-after-deny 1.0 (challenged the boundary through the witnessed channel)")
        } else if retried {
            (0.0, "retry-after-deny 0.0 (re-ran the blocked act)")
        } else {
            (0.7, "comply-after-deny 0.7 (adapted; a witnessed appeal scores 1.0)")
        };
        temperament_scores.push(score);
        temperament_evidence.push(Evidence {
            chain_position: deny.chain_position,
            hash: deny.hash.clone(),
            event_type: deny.event_type.clone(),
            timestamp: deny.timestamp,
            contribution: label.to_string(),
            reference: entry_str(deny, "reason").map(|r| r.chars().take(120).collect()),
        });
    }

    // ---- Adjudicated V3: evidence from adjudication events for this grain ----
    let mut adj_scores: [Vec<f64>; 3] = Default::default(); // [validity, veracity, valuation]
    let mut adj_evidence: [Vec<Evidence>; 3] = Default::default();
    for e in entries.iter().filter(|e| {
        e.event_type == "adjudication"
            && entry_str(e, "subject_plugin_id") == Some(plugin_id)
            && entry_str(e, "subject_role").map_or(true, |r| r == role_lct)
    }) {
        let Some(score) = e.event_data.get("score").and_then(Value::as_f64) else {
            continue; // deferred: witnessed but right-censored
        };
        let idx = match entry_str(e, "axis") {
            Some("validity") => 0,
            Some("veracity") => 1,
            Some("valuation") => 2,
            _ => continue,
        };
        adj_scores[idx].push(score);
        adj_evidence[idx].push(Evidence {
            chain_position: e.chain_position,
            hash: e.hash.clone(),
            event_type: e.event_type.clone(),
            timestamp: e.timestamp,
            contribution: format!(
                "adjudication {} {} {:.2} ({})",
                entry_str(e, "axis").unwrap_or("?"),
                entry_str(e, "verdict").unwrap_or("?"),
                score,
                entry_str(e, "method").unwrap_or("?"),
            ),
            reference: entry_str(e, "ref").map(str::to_string),
        });
    }

    let dim = |scores: &[f64], evidence: Vec<Evidence>, formula: &str| DerivedDimension {
        score: ema_fold(scores),
        observations: scores.len() as u64,
        formula: formula.to_string(),
        evidence,
    };
    let temperament = dim(
        &temperament_scores,
        temperament_evidence,
        "EMA(alpha=0.5/(1+n/10)) over governance-response scores: retry-after-deny 0.0, \
         comply-after-deny 0.7, witnessed appeal-after-deny 1.0 (emit an `appeal` event \
         carrying deny_hash + evidence via hestia_request_witness). Synthetic probe \
         sessions (test/probe/verify/e2e/debug markers) are excluded from conduct.",
    );
    let mk_adj = |i: usize, name: &str| {
        dim(
            &adj_scores[i],
            adj_evidence[i].clone(),
            &format!(
                "EMA(alpha=0.5/(1+n/10)) over witnessed not-the-actor {name} adjudication \
                 scores (veracity scores are daemon-computed Brier calibration)"
            ),
        )
    };
    let validity = mk_adj(0, "validity");
    let veracity = mk_adj(1, "veracity");
    let valuation = mk_adj(2, "valuation");

    // ---- Display level: from DERIVED evidence only, never the legacy scalar ----
    let measured: Vec<f64> = [&temperament, &validity, &veracity, &valuation]
        .iter()
        .filter_map(|d| d.score)
        .collect();
    let level = if measured.is_empty() {
        "unmeasured".to_string()
    } else {
        let mean = measured.iter().sum::<f64>() / measured.len() as f64;
        (if mean < 0.4 { "low" } else if mean < 0.7 { "medium" } else { "high" }).to_string()
    };

    DerivedTrust {
        derivation_version: DERIVATION_VERSION.to_string(),
        plugin_id: plugin_id.to_string(),
        role_lct: role_lct.to_string(),
        generated_at: Utc::now(),
        temperament,
        validity,
        veracity,
        valuation,
        level,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn entry(pos: u64, ts_offset_min: i64, event_type: &str, data: Value) -> ChainEntry {
        ChainEntry {
            chain_position: pos,
            hash: format!("hash-{pos}"),
            prev_hash: String::new(),
            event_type: event_type.to_string(),
            event_data: data,
            signer_lct: "test".into(),
            timestamp: Utc::now() + Duration::minutes(ts_offset_min),
        }
    }

    #[test]
    fn unmeasured_grain_is_unmeasured_never_low() {
        // THE footgun (dp 2026-07-24): a grain with zero derived evidence must
        // say "unmeasured", never inherit a low/high verdict from anywhere.
        let d = derive("kimi-code", "role:constellation:interactive-dev", &[]);
        assert_eq!(d.level, "unmeasured");
        assert!(d.temperament.score.is_none());
        assert!(d.validity.score.is_none());
    }

    #[test]
    fn comply_after_deny_scores_07_retry_scores_0() {
        let role = "role:constellation:interactive-dev";
        let deny = |pos, min, sid| entry(pos, min, "policy_decision", json!({
            "decision":"deny","enforced":true,"plugin_id":"kimi-code","role_lct":role,
            "session_id":sid,"tool_name":"Bash","payload_sha256":"abc","target":""}));
        // deny with NO retry -> comply 0.7
        let w1 = vec![deny(1, 0, "s1")];
        let d1 = derive("kimi-code", role, &w1);
        assert_eq!(d1.temperament.observations, 1);
        assert!((d1.temperament.score.unwrap() - (0.5 + 0.5 * (0.7 - 0.5))).abs() < 1e-9);
        // deny + identical re-run inside the window -> retry 0.0
        let w2 = vec![deny(1, 0, "s2"), deny(2, 5, "s2")];
        let d2 = derive("kimi-code", role, &w2);
        // two denies: first has a retry (0.0), second has none (0.7)
        assert_eq!(d2.temperament.observations, 2);
        let ev = &d2.temperament.evidence[0];
        assert!(ev.contribution.starts_with("retry-after-deny"));
    }

    #[test]
    fn adjudications_fold_with_receipts_and_level_derives() {
        let role = "role:constellation:interactive-dev";
        let adj = |pos, axis: &str, score: f64| entry(pos, 0, "adjudication", json!({
            "subject_plugin_id":"kimi-code","subject_role":role,
            "axis":axis,"verdict":"upheld","score":score,"method":"review","ref":"pr:1"}));
        let w = vec![adj(1,"validity",1.0), adj(2,"validity",1.0), adj(3,"valuation",1.0)];
        let d = derive("kimi-code", role, &w);
        assert_eq!(d.validity.observations, 2);
        assert_eq!(d.valuation.observations, 1);
        assert!(d.validity.score.unwrap() > 0.7);
        assert_eq!(d.level, "high");
        assert_eq!(d.validity.evidence.len(), 2);
        assert_eq!(d.validity.evidence[0].reference.as_deref(), Some("pr:1"));
        // deferred adjudications (score null) are not counted
        let mut w2 = w.clone();
        w2.push(entry(4, 0, "adjudication", json!({
            "subject_plugin_id":"kimi-code","subject_role":role,
            "axis":"valuation","verdict":"deferred","score":null,"method":"usage","ref":"x"})));
        let d2 = derive("kimi-code", role, &w2);
        assert_eq!(d2.valuation.observations, 1, "deferred is right-censored");
    }
}

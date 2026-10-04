//! D2 live-shadow parity projection.
//!
//! The legacy member_notify path remains authoritative. These reports compare
//! only the routing/queue seam after the shared legacy gates have already run.
//! A "route_selection_match" therefore means: legacy chose routed egress and
//! F3 would choose a forward route. It does NOT claim downstream delivery parity.

use serde::Serialize;
use serde_json::Value;

use crate::storage::ChainEntry;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct LegacyParitySample {
    pub chain_position: u64,
    pub hash: String,
    pub timestamp: String,
    pub event_type: String,
    pub legacy_address: Option<String>,
    pub legacy_outcome: String,
    pub refusal_reason: Option<String>,
    pub f3_status: String,
    pub f3_destination_lct: Option<String>,
    pub f3_decision: Option<String>,
    pub classification: String,
}

#[derive(Debug, Clone, Serialize, Default, PartialEq, Eq)]
pub struct LegacyParityReport {
    pub total: usize,
    pub route_selection_match: usize,
    pub missing_alias: usize,
    pub shadow_unavailable: usize,
    pub route_divergence: usize,
    pub shared_transport_refusal: usize,
    pub legacy_queue_refusal: usize,
    pub other_refusal: usize,
    pub samples: Vec<LegacyParitySample>,
}

fn s(v: Option<&Value>) -> Option<String> {
    v.and_then(Value::as_str).map(str::to_string)
}

fn shadow_shape(shadow: &Value) -> (String, Option<String>, Option<String>) {
    if shadow.get("status").and_then(Value::as_str) == Some("unavailable") {
        return ("unavailable".into(), None, None);
    }
    let Some(result) = shadow.get("result") else {
        return ("malformed".into(), None, None);
    };
    let status = result
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("malformed")
        .to_string();
    let destination = s(result.get("destination_lct"));
    let decision = result
        .get("decision")
        .and_then(|v| v.get("decision"))
        .and_then(Value::as_str)
        .map(str::to_string);
    (status, destination, decision)
}

pub fn project_entry(entry: &ChainEntry) -> Option<LegacyParitySample> {
    let data = &entry.event_data;
    let shadow = data.get("f3_shadow")?;
    let (f3_status, f3_destination_lct, f3_decision) = shadow_shape(shadow);
    let legacy_address = s(data.get("legacy_address"))
        .or_else(|| s(data.get("to_plugin_id")));
    let refusal_reason = s(data.get("reason"));
    let legacy_outcome = if entry.event_type == "member_notice_route_shadow" {
        s(data.get("legacy_outcome")).unwrap_or_else(|| "egress_queued".into())
    } else if entry.event_type == "member_notice_refused" {
        format!(
            "refused:{}",
            refusal_reason.as_deref().unwrap_or("unknown")
        )
    } else {
        entry.event_type.clone()
    };

    let classification = if entry.event_type == "member_notice_route_shadow" {
        match (f3_status.as_str(), f3_decision.as_deref()) {
            ("resolved", Some("forward")) => "route_selection_match",
            ("missing_alias", _) => "missing_alias",
            ("unavailable" | "malformed", _) => "shadow_unavailable",
            _ => "route_divergence",
        }
    } else {
        match refusal_reason.as_deref() {
            Some("transport_binding_unmet") => "shared_transport_refusal",
            Some("egress_queue_full") => match (f3_status.as_str(), f3_decision.as_deref()) {
                ("resolved", Some("forward")) => "legacy_queue_refusal",
                ("missing_alias", _) => "missing_alias",
                ("unavailable" | "malformed", _) => "shadow_unavailable",
                _ => "route_divergence",
            },
            _ => "other_refusal",
        }
    }
    .to_string();

    Some(LegacyParitySample {
        chain_position: entry.chain_position,
        hash: entry.hash.clone(),
        timestamp: entry.timestamp.to_rfc3339(),
        event_type: entry.event_type.clone(),
        legacy_address,
        legacy_outcome,
        refusal_reason,
        f3_status,
        f3_destination_lct,
        f3_decision,
        classification,
    })
}

pub fn summarize(entries: &[ChainEntry]) -> LegacyParityReport {
    let mut report = LegacyParityReport::default();
    for entry in entries {
        let Some(sample) = project_entry(entry) else { continue };
        report.total += 1;
        match sample.classification.as_str() {
            "route_selection_match" => report.route_selection_match += 1,
            "missing_alias" => report.missing_alias += 1,
            "shadow_unavailable" => report.shadow_unavailable += 1,
            "route_divergence" => report.route_divergence += 1,
            "shared_transport_refusal" => report.shared_transport_refusal += 1,
            "legacy_queue_refusal" => report.legacy_queue_refusal += 1,
            _ => report.other_refusal += 1,
        }
        report.samples.push(sample);
    }
    report
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn entry(event_type: &str, data: Value, pos: u64) -> ChainEntry {
        ChainEntry {
            hash: format!("{pos:064x}"),
            prev_hash: "0".repeat(64),
            timestamp: Utc::now(),
            event_type: event_type.to_string(),
            event_data: data,
            signer_lct: "lct:web4:mb32:router".to_string(),
            chain_position: pos,
        }
    }

    #[test]
    fn queued_legacy_egress_and_f3_forward_is_route_selection_match() {
        let e = entry(
            "member_notice_route_shadow",
            serde_json::json!({
                "legacy_address": "thor/claude-code",
                "legacy_outcome": "egress_queued",
                "f3_shadow": {
                    "result": {
                        "status": "resolved",
                        "destination_lct": "lct:web4:mb32:end-member",
                        "decision": {
                            "decision": "forward",
                            "destination_lct": "lct:web4:mb32:end-member",
                            "next_hop_lct": "lct:web4:mb32:thor-router",
                            "via": "default"
                        }
                    }
                }
            }),
            1,
        );
        let r = summarize(&[e]);
        assert_eq!(r.total, 1);
        assert_eq!(r.route_selection_match, 1);
        assert_eq!(r.route_divergence, 0);
    }

    #[test]
    fn missing_alias_and_legacy_queue_backpressure_are_visible_not_equated() {
        let missing = entry(
            "member_notice_route_shadow",
            serde_json::json!({
                "legacy_address": "thor/kimi",
                "legacy_outcome": "egress_queued",
                "f3_shadow": {
                    "result": {
                        "status": "missing_alias",
                        "legacy_address": "thor/kimi"
                    }
                }
            }),
            2,
        );
        let full = entry(
            "member_notice_refused",
            serde_json::json!({
                "reason": "egress_queue_full",
                "to_plugin_id": "thor/claude-code",
                "f3_shadow": {
                    "result": {
                        "status": "resolved",
                        "destination_lct": "lct:web4:mb32:end-member",
                        "decision": {"decision":"forward"}
                    }
                }
            }),
            3,
        );
        let r = summarize(&[full, missing]);
        assert_eq!(r.missing_alias, 1);
        assert_eq!(r.legacy_queue_refusal, 1);
        assert_eq!(r.route_selection_match, 0);
    }

    #[test]
    fn transport_refusal_is_shared_pre_route_contract_not_route_mismatch() {
        let e = entry(
            "member_notice_refused",
            serde_json::json!({
                "reason": "transport_binding_unmet",
                "to_plugin_id": "thor/claude-code",
                "f3_shadow": {
                    "result": {
                        "status": "resolved",
                        "destination_lct": "lct:web4:mb32:end-member",
                        "decision": {"decision":"forward"}
                    }
                }
            }),
            4,
        );
        let r = summarize(&[e]);
        assert_eq!(r.shared_transport_refusal, 1);
        assert_eq!(r.route_divergence, 0);
    }
}

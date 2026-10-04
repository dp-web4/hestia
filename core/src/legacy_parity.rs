//! D2 live-shadow parity projection.
//!
//! The legacy member_notify path remains authoritative. The enqueue-side shadow
//! records F3's exact route/neighbor decision; the later egress_forwarded witness
//! records what the legacy transport actually did. The report joins those by the
//! durable egress row id.
//!
//! Missing evidence is never called equality. In particular, legacy enqueue does
//! not populate dest_peer_lct today; only hub-notify's measured recipient_lct in
//! the eventual Hub receipt is acceptable evidence of the historical next hop.

use std::collections::HashMap;

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
    pub legacy_egress_row_id: Option<u64>,
    pub refusal_reason: Option<String>,

    pub legacy_carrier_lct: Option<String>,
    pub legacy_hub_recipient_lct: Option<String>,
    pub legacy_hub_ledger: Option<String>,
    pub legacy_forward_witness_hash: Option<String>,

    pub f3_status: String,
    pub f3_destination_lct: Option<String>,
    pub f3_decision: Option<String>,
    pub f3_next_hop_lct: Option<String>,
    pub f3_neighbor_status: Option<String>,
    pub f3_expected_hub_member_lct: Option<String>,

    pub classification: String,
}

#[derive(Debug, Clone, Serialize, Default, PartialEq, Eq)]
pub struct LegacyParityReport {
    pub total: usize,
    /// Both transports have measured Hub-member next-hop identities and they are equal.
    /// This is next-hop parity only — not read/delivery parity.
    pub next_hop_match: usize,
    pub next_hop_mismatch: usize,
    /// Legacy queue admission succeeded, but no egress_forwarded witness exists yet.
    pub legacy_queued_not_forwarded_yet: usize,
    /// Legacy was witnessed forwarded, but its drain did not report the Hub recipient LCT.
    pub legacy_recipient_unmeasured: usize,
    /// F3 chose a canonical next-hop router but has no neighbor/Hub-member binding for it.
    pub f3_missing_neighbor: usize,
    pub missing_alias: usize,
    pub shadow_unavailable: usize,
    pub route_divergence: usize,
    pub shared_transport_refusal: usize,
    pub legacy_queue_refusal: usize,
    pub other_refusal: usize,
    pub samples: Vec<LegacyParitySample>,
}

#[derive(Debug, Clone, Default)]
struct ForwardEvidence {
    carrier_lct: Option<String>,
    recipient_lct: Option<String>,
    ledger: Option<String>,
    witness_hash: Option<String>,
}

#[derive(Debug, Clone)]
struct ShadowShape {
    status: String,
    destination_lct: Option<String>,
    decision: Option<String>,
    next_hop_lct: Option<String>,
    neighbor_status: Option<String>,
    expected_hub_member_lct: Option<String>,
}

fn s(v: Option<&Value>) -> Option<String> {
    v.and_then(Value::as_str).map(str::to_string)
}

fn shadow_shape(shadow: &Value) -> ShadowShape {
    if shadow.get("status").and_then(Value::as_str) == Some("unavailable") {
        return ShadowShape {
            status: "unavailable".into(),
            destination_lct: None,
            decision: None,
            next_hop_lct: None,
            neighbor_status: None,
            expected_hub_member_lct: None,
        };
    }

    let Some(result) = shadow.get("result") else {
        return ShadowShape {
            status: "malformed".into(),
            destination_lct: None,
            decision: None,
            next_hop_lct: None,
            neighbor_status: None,
            expected_hub_member_lct: None,
        };
    };

    let decision_obj = result.get("decision");
    let neighbor = shadow.get("f3_neighbor");
    ShadowShape {
        status: result
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("malformed")
            .to_string(),
        destination_lct: s(result.get("destination_lct")),
        decision: decision_obj
            .and_then(|v| v.get("decision"))
            .and_then(Value::as_str)
            .map(str::to_string),
        next_hop_lct: decision_obj
            .and_then(|v| v.get("next_hop_lct"))
            .and_then(Value::as_str)
            .map(str::to_string),
        neighbor_status: neighbor
            .and_then(|v| v.get("status"))
            .and_then(Value::as_str)
            .map(str::to_string),
        expected_hub_member_lct: neighbor
            .and_then(|v| v.get("hub_member_lct"))
            .and_then(Value::as_str)
            .map(str::to_string),
    }
}

fn forwarded_by_row(entries: &[ChainEntry]) -> HashMap<u64, ForwardEvidence> {
    let mut out = HashMap::new();
    // The chain reader returns newest first. Keep the first disposition if an old
    // deployment ever wrote more than one witness for the same row.
    for entry in entries.iter().filter(|e| e.event_type == "egress_forwarded") {
        let Some(row_id) = entry.event_data.get("row_id").and_then(Value::as_u64) else {
            continue;
        };
        out.entry(row_id).or_insert_with(|| {
            let receipt = entry.event_data.get("hub_receipt");
            ForwardEvidence {
                carrier_lct: s(entry.event_data.get("carrier_lct")),
                recipient_lct: receipt
                    .and_then(|v| v.get("recipient_lct"))
                    .and_then(Value::as_str)
                    .map(str::to_string),
                ledger: receipt
                    .and_then(|v| v.get("ledger"))
                    .and_then(Value::as_str)
                    .map(str::to_string),
                witness_hash: Some(entry.hash.clone()),
            }
        });
    }
    out
}

fn project_entry(
    entry: &ChainEntry,
    forwarded: &HashMap<u64, ForwardEvidence>,
) -> Option<LegacyParitySample> {
    if entry.event_type == "egress_forwarded" {
        return None;
    }

    let data = &entry.event_data;
    let shadow = data.get("f3_shadow")?;
    let shape = shadow_shape(shadow);
    let legacy_address = s(data.get("legacy_address"))
        .or_else(|| s(data.get("to_plugin_id")));
    let refusal_reason = s(data.get("reason"));
    let row_id = data.get("legacy_egress_row_id").and_then(Value::as_u64);
    let legacy_forward = row_id.and_then(|id| forwarded.get(&id));

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
        match (shape.status.as_str(), shape.decision.as_deref()) {
            ("missing_alias", _) => "missing_alias",
            ("unavailable" | "malformed", _) => "shadow_unavailable",
            ("resolved", Some("forward")) => {
                if shape.neighbor_status.as_deref() == Some("missing_neighbor")
                    || shape.expected_hub_member_lct.is_none()
                {
                    "f3_missing_neighbor"
                } else if legacy_forward.is_none() {
                    "legacy_queued_not_forwarded_yet"
                } else if legacy_forward.and_then(|f| f.recipient_lct.as_deref()).is_none() {
                    "legacy_recipient_unmeasured"
                } else if legacy_forward
                    .and_then(|f| f.recipient_lct.as_deref())
                    .zip(shape.expected_hub_member_lct.as_deref())
                    .is_some_and(|(actual, expected)| actual.eq_ignore_ascii_case(expected))
                {
                    "next_hop_match"
                } else {
                    "next_hop_mismatch"
                }
            }
            _ => "route_divergence",
        }
    } else {
        match refusal_reason.as_deref() {
            Some("transport_binding_unmet") => "shared_transport_refusal",
            Some("egress_queue_full") => match (shape.status.as_str(), shape.decision.as_deref()) {
                ("missing_alias", _) => "missing_alias",
                ("unavailable" | "malformed", _) => "shadow_unavailable",
                ("resolved", Some("forward"))
                    if shape.neighbor_status.as_deref() == Some("missing_neighbor")
                        || shape.expected_hub_member_lct.is_none() =>
                {
                    "f3_missing_neighbor"
                }
                ("resolved", Some("forward")) => "legacy_queue_refusal",
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
        legacy_egress_row_id: row_id,
        refusal_reason,

        legacy_carrier_lct: legacy_forward.and_then(|f| f.carrier_lct.clone()),
        legacy_hub_recipient_lct: legacy_forward.and_then(|f| f.recipient_lct.clone()),
        legacy_hub_ledger: legacy_forward.and_then(|f| f.ledger.clone()),
        legacy_forward_witness_hash: legacy_forward.and_then(|f| f.witness_hash.clone()),

        f3_status: shape.status,
        f3_destination_lct: shape.destination_lct,
        f3_decision: shape.decision,
        f3_next_hop_lct: shape.next_hop_lct,
        f3_neighbor_status: shape.neighbor_status,
        f3_expected_hub_member_lct: shape.expected_hub_member_lct,

        classification,
    })
}

pub fn summarize(entries: &[ChainEntry]) -> LegacyParityReport {
    let forwarded = forwarded_by_row(entries);
    let mut report = LegacyParityReport::default();
    for entry in entries {
        let Some(sample) = project_entry(entry, &forwarded) else {
            continue;
        };
        report.total += 1;
        match sample.classification.as_str() {
            "next_hop_match" => report.next_hop_match += 1,
            "next_hop_mismatch" => report.next_hop_mismatch += 1,
            "legacy_queued_not_forwarded_yet" => report.legacy_queued_not_forwarded_yet += 1,
            "legacy_recipient_unmeasured" => report.legacy_recipient_unmeasured += 1,
            "f3_missing_neighbor" => report.f3_missing_neighbor += 1,
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

    fn queued(row_id: u64, expected_hub_member: Option<&str>) -> ChainEntry {
        let neighbor = match expected_hub_member {
            Some(id) => serde_json::json!({
                "status": "resolved",
                "next_hop_lct": "lct:web4:mb32:thor-router",
                "hub_member_lct": id,
                "link_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "interface_binding_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            }),
            None => serde_json::json!({
                "status": "missing_neighbor",
                "next_hop_lct": "lct:web4:mb32:thor-router"
            }),
        };
        entry(
            "member_notice_route_shadow",
            serde_json::json!({
                "legacy_address": "thor/claude-code",
                "legacy_outcome": "egress_queued",
                "legacy_egress_row_id": row_id,
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
                    },
                    "f3_neighbor": neighbor
                }
            }),
            row_id,
        )
    }

    fn forwarded(row_id: u64, recipient: Option<&str>) -> ChainEntry {
        entry(
            "egress_forwarded",
            serde_json::json!({
                "row_id": row_id,
                "carrier_lct": "legacy-carrier",
                "hub_receipt": match recipient {
                    Some(id) => serde_json::json!({"ledger":"42", "recipient_lct":id}),
                    None => serde_json::json!({"ledger":"42"}),
                }
            }),
            row_id + 1000,
        )
    }

    #[test]
    fn queued_but_not_yet_forwarded_is_not_parity() {
        let r = summarize(&[queued(7, Some("11111111-1111-4111-8111-111111111111"))]);
        assert_eq!(r.total, 1);
        assert_eq!(r.legacy_queued_not_forwarded_yet, 1);
        assert_eq!(r.next_hop_match, 0);
    }

    #[test]
    fn measured_hub_next_hop_match_is_explicit() {
        let id = "11111111-1111-4111-8111-111111111111";
        let r = summarize(&[forwarded(7, Some(id)), queued(7, Some(id))]);
        assert_eq!(r.next_hop_match, 1);
        let s = &r.samples[0];
        assert_eq!(s.legacy_hub_recipient_lct.as_deref(), Some(id));
        assert_eq!(s.f3_expected_hub_member_lct.as_deref(), Some(id));
        assert_eq!(s.legacy_hub_ledger.as_deref(), Some("42"));
    }

    #[test]
    fn measured_hub_next_hop_mismatch_is_not_hidden() {
        let r = summarize(&[
            forwarded(7, Some("22222222-2222-4222-8222-222222222222")),
            queued(7, Some("11111111-1111-4111-8111-111111111111")),
        ]);
        assert_eq!(r.next_hop_mismatch, 1);
        assert_eq!(r.next_hop_match, 0);
    }

    #[test]
    fn legacy_forward_without_recipient_measurement_stays_unknown() {
        let r = summarize(&[
            forwarded(7, None),
            queued(7, Some("11111111-1111-4111-8111-111111111111")),
        ]);
        assert_eq!(r.legacy_recipient_unmeasured, 1);
        assert_eq!(r.next_hop_match, 0);
    }

    #[test]
    fn f3_forward_without_neighbor_is_not_executable_parity() {
        let r = summarize(&[queued(7, None)]);
        assert_eq!(r.f3_missing_neighbor, 1);
    }

    #[test]
    fn missing_alias_and_legacy_queue_backpressure_are_visible_not_equated() {
        let missing = entry(
            "member_notice_route_shadow",
            serde_json::json!({
                "legacy_address": "thor/kimi",
                "legacy_outcome": "egress_queued",
                "legacy_egress_row_id": 8,
                "f3_shadow": {
                    "result": {
                        "status": "missing_alias",
                        "legacy_address": "thor/kimi"
                    },
                    "f3_neighbor": {"status":"not_applicable"}
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
                        "decision": {"decision":"forward", "next_hop_lct":"lct:web4:mb32:thor-router"}
                    },
                    "f3_neighbor": {
                        "status":"resolved",
                        "hub_member_lct":"11111111-1111-4111-8111-111111111111"
                    }
                }
            }),
            3,
        );
        let r = summarize(&[full, missing]);
        assert_eq!(r.missing_alias, 1);
        assert_eq!(r.legacy_queue_refusal, 1);
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

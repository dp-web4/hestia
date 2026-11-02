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

/// Edge-specific cutover evidence. READY means only what it says:
/// the recent measured legacy next hop agrees with the executable F3 next hop,
/// with no unresolved parity classes in the selected window. It does NOT claim
/// byte-for-byte semantic equality; the two intentional migration strengthenings
/// remain named explicitly below.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct LegacyCutoverCheck {
    pub legacy_address: String,
    pub min_matches: usize,
    pub ready: bool,
    pub blockers: Vec<String>,
    pub named_migration_rules: Vec<String>,
    pub parity: LegacyParityReport,
}

impl LegacyCutoverCheck {
    pub fn require_ready(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.ready,
            "F3 cutover for '{}' is not ready: {}",
            self.legacy_address,
            if self.blockers.is_empty() {
                "unspecified parity blocker".to_string()
            } else {
                self.blockers.join("; ")
            }
        );
        Ok(())
    }
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

fn tally(report: &mut LegacyParityReport, sample: LegacyParitySample) {
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

pub fn summarize(entries: &[ChainEntry]) -> LegacyParityReport {
    let forwarded = forwarded_by_row(entries);
    let mut report = LegacyParityReport::default();
    for entry in entries {
        let Some(sample) = project_entry(entry, &forwarded) else {
            continue;
        };
        tally(&mut report, sample);
    }
    report
}

/// Project one exact legacy compatibility edge. Forward evidence is still read
/// from the full window before the samples are filtered; filtering the raw chain
/// first would accidentally discard the egress_forwarded rows needed to prove
/// which Hub member legacy actually reached.
pub fn summarize_address(
    entries: &[ChainEntry],
    legacy_address: &str,
) -> LegacyParityReport {
    let full = summarize(entries);
    let mut out = LegacyParityReport::default();
    for sample in full.samples {
        if sample.legacy_address.as_deref() == Some(legacy_address) {
            tally(&mut out, sample);
        }
    }
    out
}

/// Mechanical D3 preflight for one remote compatibility edge.
///
/// READY requires measured equality on the property D2 can actually prove:
/// legacy and F3 resolve to the same Hub next-hop member. Missing evidence is a
/// blocker, not equality. Shared pre-route transport refusals may coexist with
/// good samples because both planes were refused before routing; they do not
/// substitute for a successful measured match.
///
/// Two intentional semantic differences are always named rather than hidden:
/// F3's stronger durable-acceptance boundary, and its stable retry identity.
/// Refuse to borrow historical parity from a route/neighbor different from
/// the one the edge would use now. Every next_hop_match counted in the selected
/// evidence window must agree with the current route; a window straddling a
/// config edit is intentionally HOLD until a clean window is measured.
pub fn current_route_evidence_blockers(
    parity: &LegacyParityReport,
    current_next_hop_lct: &str,
    current_hub_member_lct: &str,
) -> Vec<String> {
    let stale: Vec<&LegacyParitySample> = parity
        .samples
        .iter()
        .filter(|s| s.classification == "next_hop_match")
        .filter(|s| {
            s.f3_next_hop_lct.as_deref() != Some(current_next_hop_lct)
                || s.f3_expected_hub_member_lct.as_deref() != Some(current_hub_member_lct)
        })
        .collect();
    if stale.is_empty() {
        return Vec::new();
    }
    let examples: Vec<String> = stale
        .iter()
        .take(3)
        .map(|sample| format!(
            "next-hop={} Hub-member={}",
            sample.f3_next_hop_lct.as_deref().unwrap_or("(missing)"),
            sample.f3_expected_hub_member_lct.as_deref().unwrap_or("(missing)")
        ))
        .collect();
    vec![format!(
        "{} measured match sample(s) belong to a different route/neighbor than current next-hop={} Hub-member={}: {}",
        stale.len(),
        current_next_hop_lct,
        current_hub_member_lct,
        examples.join(", ")
    )]
}

pub fn cutover_check(
    entries: &[ChainEntry],
    legacy_address: &str,
    min_matches: usize,
) -> LegacyCutoverCheck {
    let parity = summarize_address(entries, legacy_address);
    let mut blockers = Vec::new();

    if parity.total == 0 {
        blockers.push("no parity samples for this exact legacy address".to_string());
    }
    if parity.next_hop_match < min_matches {
        blockers.push(format!(
            "only {} measured next-hop match(es); require at least {min_matches}",
            parity.next_hop_match
        ));
    }

    let unresolved = [
        ("next-hop mismatch", parity.next_hop_mismatch),
        ("legacy queued but not forwarded yet", parity.legacy_queued_not_forwarded_yet),
        ("legacy Hub recipient unmeasured", parity.legacy_recipient_unmeasured),
        ("F3 missing neighbor", parity.f3_missing_neighbor),
        ("missing alias", parity.missing_alias),
        ("shadow unavailable/malformed", parity.shadow_unavailable),
        ("route divergence", parity.route_divergence),
        ("legacy queue refusal", parity.legacy_queue_refusal),
        ("other refusal", parity.other_refusal),
    ];
    for (name, count) in unresolved {
        if count > 0 {
            blockers.push(format!("{count} sample(s): {name}"));
        }
    }

    LegacyCutoverCheck {
        legacy_address: legacy_address.to_string(),
        min_matches,
        ready: blockers.is_empty(),
        blockers,
        named_migration_rules: vec![
            "acceptance-strengthening: F3 acknowledges only witnessed local delivery or durable receipt-mode next-hop acceptance; legacy Hub witness/acceptance is weaker".to_string(),
            "retry-identity-strengthening: F3 carries one stable immutable operation id across retry; historical legacy delivery could duplicate, with #1219 defining the migration contract".to_string(),
        ],
        parity,
    }
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
    fn edge_cutover_ready_requires_exact_measured_matches_and_no_unknowns() {
        let id = "11111111-1111-4111-8111-111111111111";
        let rows = vec![
            forwarded(7, Some(id)),
            queued(7, Some(id)),
            // A different edge in the same window must not contaminate this check.
            entry(
                "member_notice_route_shadow",
                serde_json::json!({
                    "legacy_address": "other/claude-code",
                    "legacy_outcome": "egress_queued",
                    "legacy_egress_row_id": 99,
                    "f3_shadow": {
                        "result": {"status":"missing_alias"},
                        "f3_neighbor": {"status":"not_applicable"}
                    }
                }),
                99,
            ),
        ];
        let check = cutover_check(&rows, "thor/claude-code", 1);
        assert!(check.ready, "{:?}", check.blockers);
        assert_eq!(check.parity.total, 1);
        assert_eq!(check.parity.next_hop_match, 1);
        assert_eq!(check.named_migration_rules.len(), 2);
    }

    #[test]
    fn current_route_check_rejects_a_window_that_straddles_a_route_change() {
        let id = "11111111-1111-4111-8111-111111111111";
        let mut parity = summarize(&[
            forwarded(7, Some(id)),
            queued(7, Some(id)),
        ]);
        assert_eq!(parity.next_hop_match, 1);
        let mut stale = parity.samples[0].clone();
        stale.chain_position += 1;
        stale.f3_next_hop_lct = Some("lct:web4:mb32:old-router".to_string());
        stale.f3_expected_hub_member_lct =
            Some("22222222-2222-4222-8222-222222222222".to_string());
        parity.next_hop_match += 1;
        parity.total += 1;
        parity.samples.push(stale);

        let blockers = current_route_evidence_blockers(
            &parity,
            "lct:web4:mb32:thor-router",
            id,
        );
        assert_eq!(blockers.len(), 1);
        assert!(blockers[0].contains("1 measured match sample"));
        assert!(blockers[0].contains("old-router"));

        // A clean window over the current route is accepted by this structural check.
        let clean = summarize(&[
            forwarded(9, Some(id)),
            queued(9, Some(id)),
        ]);
        assert!(current_route_evidence_blockers(
            &clean,
            "lct:web4:mb32:thor-router",
            id,
        ).is_empty());
    }

    #[test]
    fn edge_cutover_missing_or_unresolved_evidence_is_hold_not_equality() {
        let id = "11111111-1111-4111-8111-111111111111";
        let pending = cutover_check(
            &[queued(7, Some(id))],
            "thor/claude-code",
            1,
        );
        assert!(!pending.ready);
        assert!(pending.blockers.iter().any(|b| b.contains("not forwarded")));

        let absent = cutover_check(&[], "thor/claude-code", 1);
        assert!(!absent.ready);
        assert!(absent.blockers.iter().any(|b| b.contains("no parity samples")));
    }

    #[test]
    fn edge_cutover_shared_pre_route_refusal_does_not_erase_real_match() {
        let id = "11111111-1111-4111-8111-111111111111";
        let shared = entry(
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
        let check = cutover_check(
            &[forwarded(7, Some(id)), queued(7, Some(id)), shared],
            "thor/claude-code",
            1,
        );
        assert!(check.ready, "{:?}", check.blockers);
        assert_eq!(check.parity.shared_transport_refusal, 1);
        assert_eq!(check.parity.next_hop_match, 1);
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

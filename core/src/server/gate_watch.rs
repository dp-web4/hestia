//! Gate integrity, checked by the daemon on its own clock.
//!
//! dp, 2026-09-21, choosing option 1 on #1085: the daemon verifies its own gates — at startup,
//! periodically, and after a deploy — and records the result; the installer reads it. Before
//! this, `vault::gate_integrity` could only be asked through `/api/gates/verify`, behind the
//! operator gate, so a gate rewritten at noon was invisible until an operator happened to ask,
//! and a deploy run by a seat could never certify what it installed (GPT's HOLD on #1085).
//!
//! WHAT IS RECORDED, AND WHEN. The same edge discipline as seat-config drift
//! (`witness_config_verdicts`): a finding is witnessed when it OPENS or CHANGES, and its
//! resolution is witnessed with how long it was open. Never a row per pass — "96 identical rows
//! a day is how a real finding becomes background". Keyed per gate path, so one rewritten gate
//! is one row, not a fleet-wide status flip that hides which file moved.
//!
//! WHAT IS PROJECTED. Every pass writes `<home>/status/gate-integrity.json`: when it looked, what
//! it hashed, what it concluded, and the chain hash of each open finding. That file is a
//! readable projection, not an authority — anyone who can write `<home>` can edit it, exactly as
//! they can edit a gate. The chain row is the authority, and the file names it so a reader can
//! check. What the file buys is that a reader needs no operator session and no chain walk.
//!
//! WHY THE VERDICT IS BOUND TO BYTES, NOT TO TIME. Edge-only rows mean "nothing new on the
//! chain" is ambiguous between "checked, unchanged" and "not checked yet". The status file lists
//! the SHA-256 it found for each gate, so an installer can hash what it just wrote and ask the
//! only question that matters: has the daemon judged THESE bytes, and what did it say?
//!
//! What this does not do: repair, ratify, or refuse. A rewritten gate is reported; whether to
//! ratify it is the operator's act, through the operator-gated door, as before.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::vault::gate_integrity::{hash_file, GateExpectations, GateVerdict};

pub const FINDING_EVENT: &str = "gate_integrity_finding";
pub const RESOLVED_EVENT: &str = "gate_integrity_resolved";
pub const EVENT_TYPES: [&str; 2] = [FINDING_EVENT, RESOLVED_EVENT];
/// Relative to `$HESTIA_HOME`.
pub const STATUS_FILE: &str = "status/gate-integrity.json";
/// The key for "the gate set itself could not be established" — a finding about coverage,
/// which has no gate path of its own. Parenthesised so it can never collide with a real path.
pub const COVERAGE_KEY: &str = "(coverage)";

/// A finding that is open, as the daemon last witnessed it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenGateFinding {
    pub first_observed_at: u64,
    pub fingerprint: String,
    /// The chain row that opened (or last superseded) this finding. `None` only for findings
    /// rehydrated from rows written before this field existed — none today.
    pub chain_hash: Option<String>,
}

/// What one pass saw for one key.
#[derive(Debug, Clone, PartialEq)]
pub struct Observation {
    pub key: String,
    /// `verified`, `modified`, `missing`, `unratified`, `unreadable`, or `unknown` (coverage).
    pub status: String,
    /// The bytes this pass judged. `None` where there were none to hash (missing, unreadable,
    /// coverage), which a reader must not mistake for a match.
    pub found_sha256: Option<String>,
    pub plugin_id: Option<String>,
    /// Status-specific facts (expected hash, error, reason), carried into the chain row.
    pub detail: Value,
}

impl Observation {
    pub fn is_finding(&self) -> bool {
        self.status != "verified"
    }

    /// Same finding = same key, same status, same bytes. A gate modified twice with different
    /// bytes is two findings (#971's lesson: a dedup keyed on the subject alone swallowed a
    /// second, distinct tamper while the first was open).
    pub fn fingerprint(&self) -> String {
        let mut h = Sha256::new();
        h.update(self.key.as_bytes());
        h.update([0]);
        h.update(self.status.as_bytes());
        h.update([0]);
        h.update(self.found_sha256.as_deref().unwrap_or("-").as_bytes());
        format!("{:x}", h.finalize())[..16].to_string()
    }
}

/// One pass: verdicts from `vault::gate_integrity::verify` over the discovered gate set, or the
/// reason the set could not be established.
///
/// An empty discovered set is a COVERAGE finding, not a pass, for the reason `gates_verify`
/// gives: VERIFIED over an empty denominator asserts the safer of two indistinguishable states.
pub fn observe(
    expectations: &GateExpectations,
    discovered: Result<Vec<String>, String>,
) -> Vec<Observation> {
    let wired = match discovered {
        Err(reason) => return vec![coverage(format!("gate set could not be established: {reason}"))],
        Ok(w) if w.is_empty() => {
            return vec![coverage(
                "no gate-role hooks discovered — either an ungoverned host or a discovery \
                 failure, and this check cannot tell them apart"
                    .to_string(),
            )]
        }
        Ok(w) => w,
    };
    let mut out = Vec::new();
    // Expectations are keyed by path; `verify` reports some verdicts by plugin, so walk them
    // together. `verify` emits one verdict per expectation, in map order, then the unratified.
    let paths: Vec<&String> = expectations.keys().collect();
    for (i, v) in crate::vault::gate_integrity::verify(expectations, &wired).into_iter().enumerate() {
        let obs = match v {
            GateVerdict::Verified { plugin_id, sha256 } => Observation {
                key: paths[i].clone(),
                status: "verified".into(),
                found_sha256: Some(sha256),
                plugin_id: Some(plugin_id),
                detail: json!({}),
            },
            GateVerdict::Modified { plugin_id, expected, actual, ratified_at } => Observation {
                key: paths[i].clone(),
                status: "modified".into(),
                found_sha256: Some(actual),
                plugin_id: Some(plugin_id),
                detail: json!({"expected_sha256": expected, "ratified_at": ratified_at}),
            },
            GateVerdict::Missing { plugin_id, expected } => Observation {
                key: paths[i].clone(),
                status: "missing".into(),
                found_sha256: None,
                plugin_id: Some(plugin_id),
                detail: json!({"expected_sha256": expected}),
            },
            GateVerdict::Unreadable { path, error } => Observation {
                key: path,
                status: "unreadable".into(),
                found_sha256: None,
                plugin_id: None,
                detail: json!({"error": error}),
            },
            GateVerdict::Unratified { path } => {
                // `verify` does not hash an unratified gate; this pass must, or the installer
                // could not tell which bytes were judged.
                let found = hash_file(Path::new(&path)).ok();
                Observation {
                    key: path,
                    status: "unratified".into(),
                    found_sha256: found,
                    plugin_id: None,
                    detail: json!({}),
                }
            }
        };
        out.push(obs);
    }
    out
}

fn coverage(reason: String) -> Observation {
    Observation {
        key: COVERAGE_KEY.into(),
        status: "unknown".into(),
        found_sha256: None,
        plugin_id: None,
        detail: json!({"reason": reason}),
    }
}

/// A chain row this pass owes.
#[derive(Debug, Clone, PartialEq)]
pub enum Transition {
    /// A finding opened, or an open one changed (its payload names what it supersedes).
    Open { key: String, fingerprint: String, payload: Value },
    /// An open finding is gone: the gate verifies, or is no longer wired or expected at all.
    Resolve { key: String, payload: Value },
}

/// The edges between what was open and what this pass saw. Pure, so the edge logic is testable
/// without a daemon; `check` applies them and commits state only for rows that landed.
pub fn transitions(
    open: &HashMap<String, OpenGateFinding>,
    seen: &[Observation],
    now: u64,
) -> Vec<Transition> {
    let mut out = Vec::new();
    for o in seen {
        let prior = open.get(&o.key);
        if o.is_finding() {
            let fp = o.fingerprint();
            if prior.map(|p| p.fingerprint == fp).unwrap_or(false) {
                continue; // the same finding, still open: nothing new to say
            }
            let mut payload = json!({
                "gate": o.key,
                "status": o.status,
                "found_sha256": o.found_sha256,
                "plugin_id": o.plugin_id,
                "first_observed_at": now,
                "finding_fingerprint": fp,
            });
            if let (Some(obj), Some(d)) = (payload.as_object_mut(), o.detail.as_object()) {
                for (k, v) in d {
                    obj.insert(k.clone(), v.clone());
                }
            }
            if let Some(p) = prior {
                payload["supersedes_fingerprint"] = json!(p.fingerprint);
                payload["supersedes_first_observed_at"] = json!(p.first_observed_at);
            }
            out.push(Transition::Open { key: o.key.clone(), fingerprint: fp, payload });
        } else if let Some(p) = prior {
            out.push(Transition::Resolve { key: o.key.clone(), payload: resolved(&o.key, p, now, "verified", o.found_sha256.clone()) });
        }
    }
    // An open finding for a key this pass did not see at all: the hook was unwired and its
    // expectation removed. That closes the finding — silently keeping it open would leave a
    // permanent entry that can never resolve (the defect #898's review found for config).
    let mut gone: Vec<&String> = open.keys().filter(|k| !seen.iter().any(|o| &o.key == *k)).collect();
    gone.sort();
    for k in gone {
        // A coverage finding closes only when coverage is established, i.e. when this pass saw
        // real gates. If this pass is itself a coverage finding, `seen` contains the key.
        out.push(Transition::Resolve { key: k.clone(), payload: resolved(k, &open[k], now, "no_longer_present", None) });
    }
    out
}

fn resolved(key: &str, p: &OpenGateFinding, now: u64, how: &str, found: Option<String>) -> Value {
    json!({
        "gate": key,
        "status": "resolved",
        "resolution": how,
        "found_sha256": found,
        "finding_fingerprint": p.fingerprint,
        "opened_by": p.chain_hash,
        "first_observed_at": p.first_observed_at,
        "resolved_at": now,
        "open_secs": now.saturating_sub(p.first_observed_at),
    })
}

/// The readable projection of this pass. See the module docs for what it is and is not.
pub fn status_document(
    seen: &[Observation],
    open: &HashMap<String, OpenGateFinding>,
    checked_at: u64,
    witness_failures: usize,
) -> Value {
    let overall = if seen.iter().any(|o| o.status == "unknown") {
        "UNKNOWN"
    } else if seen.iter().any(|o| o.status == "modified") {
        "MODIFIED"
    } else if seen.iter().any(|o| o.is_finding()) {
        "FINDINGS"
    } else {
        "VERIFIED"
    };
    let gates: Vec<Value> = seen
        .iter()
        .map(|o| {
            json!({
                "gate": o.key,
                "status": o.status,
                "found_sha256": o.found_sha256,
                "plugin_id": o.plugin_id,
                // WHY, not just what: the first real run on CBP reported coverage UNKNOWN and
                // the file could not say that the inventory had fallen back to a pre-move
                // workspace path. A status a reader cannot act on is half a status.
                "detail": o.detail,
                "open_finding_chain_hash": open.get(&o.key).and_then(|f| f.chain_hash.clone()),
            })
        })
        .collect();
    json!({
        "status": overall,
        "checked_at": checked_at,
        "gates": gates,
        // A pass whose rows did not land is still reported here, and says so: the file must not
        // read as witnessed when the chain does not hold it.
        "witness_failures": witness_failures,
        "authority": "the chain rows gate_integrity_finding / gate_integrity_resolved; this file \
                      is a readable projection anyone who can write HESTIA_HOME can edit",
    })
}

/// Atomic write: a reader never sees half a document.
pub fn write_status(home: &Path, doc: &Value) -> std::io::Result<PathBuf> {
    let path = home.join(STATUS_FILE);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, serde_json::to_vec_pretty(doc).unwrap_or_default())?;
    std::fs::rename(&tmp, &path)?;
    Ok(path)
}

/// Rebuild the open set from the chain on startup, so a restart neither re-witnesses every open
/// finding nor loses the duration of one that resolves later. The newest row per gate decides.
pub fn rehydrate(chain: &crate::storage::chain::SqliteChainStore) -> HashMap<String, OpenGateFinding> {
    let mut open = HashMap::new();
    let mut decided = std::collections::HashSet::new();
    let rows = match chain.read_recent_by_types(
        None,
        &EVENT_TYPES,
        super::seat_config::REHYDRATE_SCAN_LIMIT,
    ) {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!(error = %e, "could not rebuild open gate findings from the chain; \
                            a restart will re-witness findings that were already open");
            return open;
        }
    };
    for e in rows {
        let Some(gate) = e.event_data.get("gate").and_then(|v| v.as_str()) else { continue };
        if !decided.insert(gate.to_string()) || e.event_type == RESOLVED_EVENT {
            continue;
        }
        let Some(fp) = e.event_data.get("finding_fingerprint").and_then(|v| v.as_str()) else { continue };
        open.insert(
            gate.to_string(),
            OpenGateFinding {
                first_observed_at: e
                    .event_data
                    .get("first_observed_at")
                    .and_then(|v| v.as_u64())
                    .unwrap_or_else(|| e.timestamp.timestamp().max(0) as u64),
                fingerprint: fp.to_string(),
                chain_hash: Some(e.hash.clone()),
            },
        );
    }
    open
}

/// One full pass against live daemon state: observe, witness the edges, project the status.
///
/// Open-set state changes only for rows that LANDED (#972's invariant): a failed witness leaves
/// the prior state, so the next pass retries the same transition instead of treating an
/// unrecorded finding as reported.
pub fn check(s: &mut super::state::ServerState) -> Value {
    let now = super::gate_escalation::now_secs();
    let exp = s.vault.gate_expectations();
    let discovered = super::http::discovered_gate_paths()
        .map(|d| d.into_iter().map(|(_, p)| p).collect::<Vec<_>>());
    let seen = observe(&exp, discovered);
    let mut failures = 0usize;
    for t in transitions(&s.gate_findings_open, &seen, now) {
        match t {
            Transition::Open { key, fingerprint, payload } => match s.append_chain(FINDING_EVENT, payload) {
                Ok(entry) => {
                    s.gate_findings_open.insert(
                        key,
                        OpenGateFinding { first_observed_at: now, fingerprint, chain_hash: Some(entry.hash) },
                    );
                }
                Err(e) => {
                    failures += 1;
                    tracing::warn!(gate = %key, error = %e,
                        "gate finding could NOT be recorded; the finding stands and the record does not");
                }
            },
            Transition::Resolve { key, payload } => match s.append_chain(RESOLVED_EVENT, payload) {
                Ok(_) => {
                    s.gate_findings_open.remove(&key);
                }
                Err(e) => {
                    failures += 1;
                    tracing::warn!(gate = %key, error = %e,
                        "gate resolution could NOT be recorded; the finding stays open until it is");
                }
            },
        }
    }
    let doc = status_document(&seen, &s.gate_findings_open, now, failures);
    if let Err(e) = write_status(&s.home, &doc) {
        tracing::warn!(error = %e, "gate integrity status file could not be written");
    }
    doc
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::vault::gate_integrity::GateExpectation;

    fn gate(dir: &tempfile::TempDir, name: &str, body: &str) -> String {
        let p = dir.path().join(name);
        std::fs::write(&p, body).unwrap();
        p.to_string_lossy().into_owned()
    }

    fn ratify(e: &mut GateExpectations, path: &str) {
        e.insert(
            path.to_string(),
            GateExpectation {
                sha256: hash_file(Path::new(path)).unwrap(),
                plugin_id: "claude-code".into(),
                ratified_at: chrono::Utc::now(),
                note: "test".into(),
            },
        );
    }

    /// Apply transitions the way `check` does when every witness lands.
    fn apply(open: &mut HashMap<String, OpenGateFinding>, ts: &[Transition], now: u64) {
        for t in ts {
            match t {
                Transition::Open { key, fingerprint, .. } => {
                    open.insert(key.clone(), OpenGateFinding {
                        first_observed_at: now, fingerprint: fingerprint.clone(),
                        chain_hash: Some(format!("h-{key}-{now}")),
                    });
                }
                Transition::Resolve { key, .. } => {
                    open.remove(key);
                }
            }
        }
    }

    #[test]
    fn a_clean_gate_set_writes_no_rows() {
        let d = tempfile::tempdir().unwrap();
        let g = gate(&d, "gate.py", "print('gate')");
        let mut e = GateExpectations::new();
        ratify(&mut e, &g);
        let seen = observe(&e, Ok(vec![g]));
        assert_eq!(seen[0].status, "verified");
        assert!(transitions(&HashMap::new(), &seen, 1).is_empty(), "silence is the clean state");
    }

    #[test]
    fn a_rewrite_opens_once_and_its_ratification_resolves_with_a_duration() {
        let d = tempfile::tempdir().unwrap();
        let g = gate(&d, "gate.py", "print('gate')");
        let mut e = GateExpectations::new();
        ratify(&mut e, &g);
        let mut open = HashMap::new();

        std::fs::write(&g, "import sys; sys.exit(0)").unwrap();
        let t1 = transitions(&open, &observe(&e, Ok(vec![g.clone()])), 100);
        assert!(matches!(&t1[..], [Transition::Open { .. }]), "{t1:?}");
        apply(&mut open, &t1, 100);

        // The next pass sees the same bytes: the same finding, still open, NO new row.
        assert!(transitions(&open, &observe(&e, Ok(vec![g.clone()])), 400).is_empty());

        // The operator ratifies the new bytes.
        ratify(&mut e, &g);
        let t3 = transitions(&open, &observe(&e, Ok(vec![g.clone()])), 1000);
        match &t3[..] {
            [Transition::Resolve { payload, .. }] => {
                assert_eq!(payload["open_secs"], 900);
                assert_eq!(payload["resolution"], "verified");
                assert_eq!(payload["opened_by"], "h-".to_string() + &g + "-100");
            }
            other => panic!("expected one resolution, got {other:?}"),
        }
    }

    #[test]
    fn a_second_different_rewrite_is_a_new_finding_not_folded_into_the_first() {
        // #971: dedup keyed on the subject alone swallowed a second, distinct tamper.
        let d = tempfile::tempdir().unwrap();
        let g = gate(&d, "gate.py", "print('gate')");
        let mut e = GateExpectations::new();
        ratify(&mut e, &g);
        let mut open = HashMap::new();
        std::fs::write(&g, "tamper one").unwrap();
        let t1 = transitions(&open, &observe(&e, Ok(vec![g.clone()])), 100);
        apply(&mut open, &t1, 100);
        std::fs::write(&g, "tamper two").unwrap();
        let t2 = transitions(&open, &observe(&e, Ok(vec![g.clone()])), 200);
        match &t2[..] {
            [Transition::Open { payload, .. }] => {
                assert!(payload.get("supersedes_fingerprint").is_some(), "{payload}");
                assert_eq!(payload["found_sha256"], hash_file(Path::new(&g)).unwrap());
            }
            other => panic!("the second tamper must be witnessed: {other:?}"),
        }
    }

    #[test]
    fn an_empty_or_undiscoverable_gate_set_is_a_coverage_finding_never_verified() {
        let e = GateExpectations::new();
        for d in [Ok(vec![]), Err("inventory unreadable".to_string())] {
            let seen = observe(&e, d);
            assert_eq!(seen.len(), 1);
            assert_eq!(seen[0].key, COVERAGE_KEY);
            assert_eq!(status_document(&seen, &HashMap::new(), 1, 0)["status"], "UNKNOWN");
        }
    }

    #[test]
    fn an_unratified_gate_carries_the_bytes_it_was_judged_on() {
        // The installer's whole question is "were THESE bytes judged"; an unratified gate with
        // no hash could never answer it.
        let d = tempfile::tempdir().unwrap();
        let g = gate(&d, "gate.py", "print('new')");
        let seen = observe(&GateExpectations::new(), Ok(vec![g.clone()]));
        assert_eq!(seen[0].status, "unratified");
        assert_eq!(seen[0].found_sha256.as_deref(), Some(hash_file(Path::new(&g)).unwrap().as_str()));
    }

    #[test]
    fn a_finding_whose_gate_is_no_longer_present_resolves() {
        let mut open = HashMap::new();
        open.insert("/gone/gate.py".to_string(), OpenGateFinding {
            first_observed_at: 10, fingerprint: "f".into(), chain_hash: Some("h".into()),
        });
        let d = tempfile::tempdir().unwrap();
        let g = gate(&d, "gate.py", "x");
        let mut e = GateExpectations::new();
        ratify(&mut e, &g);
        let t = transitions(&open, &observe(&e, Ok(vec![g])), 70);
        match &t[..] {
            [Transition::Resolve { key, payload }] => {
                assert_eq!(key, "/gone/gate.py");
                assert_eq!(payload["resolution"], "no_longer_present");
                assert_eq!(payload["open_secs"], 60);
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn the_status_file_is_written_whole_and_names_the_open_row() {
        let d = tempfile::tempdir().unwrap();
        let g = gate(&d, "gate.py", "x");
        let seen = observe(&GateExpectations::new(), Ok(vec![g.clone()]));
        let mut open = HashMap::new();
        let t = transitions(&open, &seen, 5);
        apply(&mut open, &t, 5);
        let doc = status_document(&seen, &open, 5, 0);
        let path = write_status(d.path(), &doc).unwrap();
        let back: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        assert_eq!(back["status"], "FINDINGS");
        assert_eq!(back["gates"][0]["open_finding_chain_hash"], format!("h-{g}-5"));
        assert!(!path.with_extension("json.tmp").exists());
    }
}

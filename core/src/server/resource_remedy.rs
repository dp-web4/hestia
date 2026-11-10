//! REMEDY REQUESTS (#1548): when the machine, not the act, is what needs fixing.
//!
//! dp, 2026-11-10: *"there should also be a request for remedy - an alert to operator, saying you
//! need to get more disk space."* A floor that fails refuses (or, in observe mode, would refuse)
//! every act that consumes the resource, and no member can fix that by changing its act. The fix
//! is the operator's: free or add disk, stop a runaway process. So a failing floor opens ONE
//! request addressed to the operator, keyed by resource and floor, and keeps it open (counting the
//! acts that met it) until a later reading shows the floor met again, which closes it.
//!
//! Both edges are witnessed (`resource_remedy_requested`, `resource_remedy_cleared`). The open
//! requests ride the dashboard snapshot the operator surfaces already poll
//! (`pending_remedy_requests`), for the reason recorded on `pending_scope_requests`: building the
//! decision surface is not building the notice.
//!
//! Held in memory and REBUILT FROM THE CHAIN at startup ([`rehydrate`]): a requested row with no
//! later cleared row is still open. A daemon that crashes while the disk is short comes back
//! still asking for the remedy, rather than forgetting until the next act meets the floor.
//!
//! A PROBE THAT STOPS ANSWERING is a health reading too ([`note_stuck`]). On 2026-11-08 cbp's
//! Windows drive bridge hung for 46 hours and nothing said so; a probe of `/mnt/c` stuck past
//! [`STUCK_AFTER`](crate::policy::resource_probes::STUCK_AFTER) opens a remedy request of its own,
//! keyed `probe/<what it measures>`, and clears when the probe answers again.

use serde::Serialize;
use serde_json::json;

use crate::policy::resources::{Assessment, FloorStatus};

/// One open request to the operator.
#[derive(Debug, Clone, Serialize)]
pub struct RemedyRequest {
    /// `<resource>/<floor>`.
    pub key: String,
    pub resource_id: String,
    pub floor_id: String,
    /// What was measured, e.g. "free disk at /mnt/c".
    pub measures: String,
    pub min: Option<u64>,
    pub max: Option<u64>,
    pub reading: Option<u64>,
    /// What the operator is asked to do.
    pub remedy: String,
    /// `observe` or `enforce` for a floor; `health` for a stuck probe.
    pub mode: String,
    pub opened_at: u64,
    pub last_seen_at: u64,
    /// Consuming acts that met this failed floor while the request was open (including the one
    /// that opened it). In enforce mode each was refused; in observe mode each would have been.
    pub acts_met: u64,
    pub last_member: String,
    /// Chain hash of the `resource_remedy_requested` row, when it committed.
    pub opened_entry: Option<String>,
}

impl RemedyRequest {
    pub fn to_value(&self) -> serde_json::Value {
        serde_json::to_value(self).unwrap_or_default()
    }
}

/// Fold one act's assessments into the open requests: open on a newly failed floor, count on a
/// still-failed one, close on a recovered one. Unknown readings change nothing.
pub fn note(s: &mut super::state::ServerState, assessments: &[Assessment], member: &str, now: u64) {
    for a in assessments {
        for f in &a.floors {
            let key = format!("{}/{}", a.resource_id, f.floor_id);
            match f.status {
                FloorStatus::Unknown | FloorStatus::Unsupported => {}
                // Contention (above a `max`, e.g. a critical process running) passes by itself:
                // the act's door is a later run, and the operator is not paged for it.
                FloorStatus::Short if !f.is_scarce() => {}
                FloorStatus::Short => {
                    if let Some(open) = s.remedy_requests.get_mut(&key) {
                        open.acts_met += 1;
                        open.reading = f.reading;
                        open.last_seen_at = now;
                        open.last_member = member.to_string();
                        continue;
                    }
                    let remedy = a.remedy.clone().unwrap_or_else(|| match (f.min, f.max) {
                        (Some(m), _) => {
                            format!("bring {} back to at least {m}", f.probe.describe())
                        }
                        (None, Some(m)) => {
                            format!("bring {} back to at most {m}", f.probe.describe())
                        }
                        _ => format!("restore {}", f.probe.describe()),
                    });
                    let mut req = RemedyRequest {
                        key: key.clone(),
                        resource_id: a.resource_id.clone(),
                        floor_id: f.floor_id.clone(),
                        measures: f.probe.describe(),
                        min: f.min,
                        max: f.max,
                        reading: f.reading,
                        remedy,
                        mode: a.mode.as_str().to_string(),
                        opened_at: now,
                        last_seen_at: now,
                        acts_met: 1,
                        last_member: member.to_string(),
                        opened_entry: None,
                    };
                    let row = s.append_chain(
                        "resource_remedy_requested",
                        json!({
                            "addressed_to": "operator",
                            "key": req.key,
                            "resource_id": req.resource_id,
                            "floor_id": req.floor_id,
                            "measures": req.measures,
                            "reading": req.reading,
                            "min": req.min,
                            "max": req.max,
                            "remedy": req.remedy,
                            "mode": req.mode,
                            "first_met_by": member,
                        }),
                    );
                    // OPEN ONLY WHAT WAS WITNESSED (NOVA, kimi-code, codex on #1551). A request
                    // whose row did not commit is not shown as open; the next act that meets the
                    // floor tries again.
                    match row {
                        Ok(r) => {
                            req.opened_entry = Some(r.hash);
                            s.remedy_requests.insert(key, req);
                        }
                        Err(e) => tracing::warn!(error = %e, key = %req.key,
                            "remedy request not witnessed; it will be retried at the next act"),
                    }
                }
                FloorStatus::Ok => {
                    if let Some(closed) = s.remedy_requests.get(&key).cloned() {
                        let row = s.append_chain(
                            "resource_remedy_cleared",
                            json!({
                                "key": closed.key,
                                "resource_id": closed.resource_id,
                                "floor_id": closed.floor_id,
                                "reading": f.reading,
                                "opened_at": closed.opened_at,
                                "opened_entry": closed.opened_entry,
                                "acts_met": closed.acts_met,
                                "cleared_by_reading_during_act_of": member,
                            }),
                        );
                        // CLOSE ONLY WHAT WAS WITNESSED: a failed clear row leaves the request
                        // open, so the chain and the dashboard never disagree about it.
                        if row.is_ok() {
                            s.remedy_requests.remove(&key);
                        }
                    }
                }
            }
        }
    }
}

/// The chain kinds a remedy request is made of, newest decides.
pub const EVENT_TYPES: [&str; 2] = ["resource_remedy_requested", "resource_remedy_cleared"];

/// Rebuild the open requests from the chain: for each key, the newest row decides. A request
/// row means still open; a cleared row means closed. `acts_met` restarts at the count the row
/// recorded (1 for the opener), so the number after a restart is a floor, not the full count.
pub fn rehydrate(
    chain: &crate::storage::chain::SqliteChainStore,
) -> std::collections::BTreeMap<String, RemedyRequest> {
    let mut open = std::collections::BTreeMap::new();
    let mut decided = std::collections::HashSet::new();
    // COMPLETE HISTORY, not a recent window (codex/kimi-code on #1551): an open request older
    // than any window is still open, and remedy rows are few, so reading all of them is cheap.
    let rows = match chain.read_recent_by_types(None, &EVENT_TYPES, u64::MAX) {
        Ok(r) => r,
        Err(e) => {
            // INCOMPLETE RECOVERY IS VISIBLE: an empty dashboard would read as "nothing is
            // wrong". Stand a health entry in for the requests that could not be rebuilt.
            tracing::warn!(error = %e, "could not rebuild open remedy requests from the chain");
            let now = crate::server::gate_escalation::now_secs();
            open.insert(
                "rehydrate/remedy-requests".to_string(),
                RemedyRequest {
                    key: "rehydrate/remedy-requests".into(),
                    resource_id: "hestia".into(),
                    floor_id: "remedy-rehydration".into(),
                    measures: "open remedy requests rebuilt from the chain at startup".into(),
                    min: None,
                    max: None,
                    reading: None,
                    remedy: format!(
                        "the daemon could not read its remedy history ({e}); requests that were \
                         open before the restart may be missing until an act meets their floor again"
                    ),
                    mode: "health".into(),
                    opened_at: now,
                    last_seen_at: now,
                    acts_met: 0,
                    last_member: "hestia".into(),
                    opened_entry: None,
                },
            );
            return open;
        }
    };
    for e in rows {
        let d = &e.event_data;
        let Some(key) = d.get("key").and_then(|v| v.as_str()) else {
            continue;
        };
        if !decided.insert(key.to_string()) || e.event_type == EVENT_TYPES[1] {
            continue;
        }
        let at = e.timestamp.timestamp().max(0) as u64;
        let text = |k: &str| d.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string();
        open.insert(
            key.to_string(),
            RemedyRequest {
                key: key.to_string(),
                resource_id: text("resource_id"),
                floor_id: text("floor_id"),
                measures: text("measures"),
                min: d.get("min").and_then(|v| v.as_u64()),
                max: d.get("max").and_then(|v| v.as_u64()),
                reading: d.get("reading").and_then(|v| v.as_u64()),
                remedy: text("remedy"),
                mode: text("mode"),
                opened_at: at,
                last_seen_at: at,
                acts_met: 1,
                last_member: text("first_met_by"),
                opened_entry: Some(e.hash.clone()),
            },
        );
    }
    open
}

/// Fold the probes that have stopped answering into the open requests: open one per stuck probe,
/// update its age while it stays stuck, clear it once the probe has answered (it is in
/// `answered`, the probes this act read with a value).
pub fn note_stuck(
    s: &mut super::state::ServerState,
    stuck: &[(crate::policy::resources::Probe, std::time::Duration)],
    answered: &[crate::policy::resources::Probe],
    member: &str,
    now: u64,
) {
    for (probe, age) in stuck {
        let key = format!("probe/{}", probe.describe());
        let secs = age.as_secs();
        if let Some(open) = s.remedy_requests.get_mut(&key) {
            open.reading = Some(secs);
            open.last_seen_at = now;
            open.acts_met += 1;
            open.last_member = member.to_string();
            continue;
        }
        let limit = crate::policy::resource_probes::STUCK_AFTER.as_secs();
        let mut req = RemedyRequest {
            key: key.clone(),
            resource_id: "probe".into(),
            floor_id: probe.describe(),
            measures: format!("seconds the probe of {} has not answered", probe.describe()),
            min: None,
            max: Some(limit),
            reading: Some(secs),
            remedy: format!(
                "the probe of {} has not answered for {} min: the filesystem or drive bridge \
                 behind it may be hung (on WSL, Windows interop; a WSL restart clears it). \
                 Until it answers, floors that read it are unknown, and each resource's \
                 on_unknown decides: allow lets consuming acts through, refuse stops them",
                probe.describe(),
                secs / 60
            ),
            mode: "health".into(),
            opened_at: now,
            last_seen_at: now,
            acts_met: 1,
            last_member: member.to_string(),
            opened_entry: None,
        };
        let row = s.append_chain(
            "resource_remedy_requested",
            json!({
                "addressed_to": "operator",
                "key": req.key,
                "resource_id": req.resource_id,
                "floor_id": req.floor_id,
                "measures": req.measures,
                "reading": req.reading,
                "min": req.min,
                "max": req.max,
                "remedy": req.remedy,
                "mode": req.mode,
                "first_met_by": member,
            }),
        );
        if let Ok(r) = row {
            req.opened_entry = Some(r.hash);
            s.remedy_requests.insert(key, req);
        }
    }
    for probe in answered {
        let key = format!("probe/{}", probe.describe());
        if let Some(closed) = s.remedy_requests.get(&key).cloned() {
            let row = s.append_chain(
                "resource_remedy_cleared",
                json!({
                    "key": closed.key,
                    "resource_id": closed.resource_id,
                    "floor_id": closed.floor_id,
                    "opened_at": closed.opened_at,
                    "opened_entry": closed.opened_entry,
                    "acts_met": closed.acts_met,
                    "cleared_by_reading_during_act_of": member,
                }),
            );
            if row.is_ok() {
                s.remedy_requests.remove(&key);
            }
        }
    }
}

/// The periodic health pass (kimi-code on #1551): a probe that hangs after the one gate call
/// that started it must surface without waiting for another consuming act. Run on the daemon's
/// reconcile tick; opens a `health` request for each stuck probe and clears it once the probe
/// has answered.
pub fn health_pass(s: &mut super::state::ServerState, now: u64) {
    let stuck =
        crate::policy::resource_probes::stuck_probes(crate::policy::resource_probes::STUCK_AFTER);
    let answered = crate::policy::resource_probes::answered_probes();
    note_stuck(s, &stuck, &answered, "hestia-health", now);
}

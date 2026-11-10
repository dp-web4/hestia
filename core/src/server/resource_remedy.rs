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
//! Held in memory. A restart forgets an open request, and the next act that meets the same failed
//! floor opens it again, so nothing is lost but the count.

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
    pub mode: &'static str,
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
                FloorStatus::Unknown => {}
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
                        mode: a.mode.as_str(),
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
                    req.opened_entry = row.ok().map(|r| r.hash);
                    s.remedy_requests.insert(key, req);
                }
                FloorStatus::Ok => {
                    if let Some(closed) = s.remedy_requests.remove(&key) {
                        let _ = s.append_chain(
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
                    }
                }
            }
        }
    }
}

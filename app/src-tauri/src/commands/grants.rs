//! Reach — the grants in force, and the operator's own grant and revoke (Sprint 4a).
//!
//! Reads ride the dashboard snapshot (`scope_grants`, both lifetimes on every row, and the
//! standing store's `standing_generation`). Writes go to the operator-walled scope routes:
//!
//!  * `POST /api/scope/grant` — an operator-originated STANDING grant. It WIDENS reach with no
//!    member ask behind it, so a reason is required (the daemon's words: "its rationale is the
//!    only account of why this reach exists"). Exact by default; the subtree is opt-in.
//!  * `POST /api/scope/revoke` (live) and `POST /api/scope/standing/revoke` (standing). Revoking
//!    NARROWS, so a reason is invited and never required.
//!
//! LAST EDIT WINS (ruled 2026-09-25). A grant for a (member, path) that already holds a standing
//! grant REPLACES it — its reason, reach and expiry — and the engine will not stop that. So the
//! app makes the overwrite visible and bound to what the operator saw: the form sends the row it
//! displayed (`seen`), this command re-reads the snapshot immediately before the write, and if
//! the row there is not the one displayed it sends NOTHING and returns `moved` with the current
//! row. What is replaced is always a value the operator was shown.
//!
//! MEMBER IDS ARE CHOSEN, NOT TYPED (spec rule `member-id`; #1067's `Claude-code` grants). The
//! member must be in the snapshot's registry and not retired; the page offers only those, and
//! this command checks again rather than trusting the page. `grant_ahead_of_connect` is never
//! sent: a member nobody has recorded is not something this surface grants to.

use tauri::State;

use crate::{daemon, AppState};

const TEXT_MAX: usize = 512;

/// The daemon's `normalize_scope_path`, mirrored exactly, so the (member, path) key the app
/// compares is the key the store holds.
fn normalize_scope_path(path: &str) -> String {
    let p = path.trim();
    let mut out: Vec<&str> = Vec::new();
    for seg in p.split('/') {
        match seg {
            "" | "." => {}
            ".." => {
                out.pop();
            }
            s => out.push(s),
        }
    }
    let joined = out.join("/");
    if p.starts_with('/') {
        format!("/{joined}")
    } else {
        joined
    }
}

fn check_reason(required: bool, reason: Option<&str>) -> Result<Option<String>, String> {
    let t = reason.map(str::trim).unwrap_or("");
    if t.len() > TEXT_MAX {
        return Err(format!("reason is {} bytes; at most {TEXT_MAX}", t.len()));
    }
    if t.chars().any(char::is_control) {
        return Err("reason contains a control character".to_string());
    }
    if required && t.is_empty() {
        return Err(
            "granting reach requires a reason: an operator grant answers no member's ask, so its \
             reason is the only account of why the reach exists. Revoking needs none."
                .to_string(),
        );
    }
    Ok((!t.is_empty()).then(|| t.to_string()))
}

/// The standing row for (member, path) in a snapshot, or `Null`. The fields compared are the ones
/// a grant replaces; `secs_remaining` and friends move on their own and are not compared.
fn standing_row(snapshot: &serde_json::Value, member: &str, path: &str) -> serde_json::Value {
    snapshot
        .get("scope_grants")
        .and_then(|v| v.as_array())
        .and_then(|rows| {
            rows.iter().find(|r| {
                r.get("lifetime").and_then(|v| v.as_str()) == Some("standing")
                    && r.get("plugin_id").and_then(|v| v.as_str()) == Some(member)
                    && r.get("path").and_then(|v| v.as_str()) == Some(path)
            })
        })
        .cloned()
        .unwrap_or(serde_json::Value::Null)
}

fn replaced_key(row: &serde_json::Value) -> serde_json::Value {
    if row.is_null() {
        return serde_json::Value::Null;
    }
    serde_json::json!({
        "reason": row.get("reason"),
        "recursive": row.get("recursive"),
        "granted_by": row.get("granted_by"),
        "expires_at": row.get("expires_at"),
        "request_id": row.get("request_id"),
    })
}

/// Everything decided before a byte leaves: -> Ok(the normalized path) or the refusal.
fn preflight_grant(
    snapshot: &serde_json::Value,
    member: &str,
    path: &str,
) -> Result<String, String> {
    let members: Vec<&str> = snapshot
        .get("members")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|x| x.as_str()).collect())
        .unwrap_or_default();
    if !members.contains(&member) {
        return Err(format!(
            "'{member}' is not a member this seat has recorded, so a grant would reach nothing. \
             Choose the member from the list; ids are not typed here."
        ));
    }
    let retired = snapshot
        .get("retired")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().any(|x| x.as_str() == Some(member)))
        .unwrap_or(false);
    if retired {
        return Err(format!(
            "'{member}' is retired on this seat and receives authority through no door. \
             Reinstate it first (Agents) if it should hold reach again."
        ));
    }
    let norm = normalize_scope_path(path);
    if !norm.starts_with('/') {
        return Err(format!(
            "'{path}' is not an absolute path; a relative grant can never match anything the \
             gate checks"
        ));
    }
    Ok(norm)
}

/// Grant `member` standing reach on `path`, as the signed-in operator.
///
/// `seen` is the existing standing row the form displayed for this (member, path) — `null` when it
/// showed none. Outcomes: `granted` {result, replaced}; `moved` {current} when the row changed
/// since the operator looked (nothing sent).
#[tauri::command]
pub async fn grant_reach(
    state: State<'_, AppState>,
    member: String,
    path: String,
    reason: Option<String>,
    recursive: Option<bool>,
    expires_in_secs: Option<u64>,
    seen: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
    let member = member.trim().to_string();
    let reason = check_reason(true, reason.as_deref())?.unwrap_or_default();
    let snapshot = daemon::get(&state, "/api/dashboard").await?;
    let path = preflight_grant(&snapshot, &member, &path)?;
    let seen = seen.unwrap_or(serde_json::Value::Null);
    // Checked here first (cheap, and nothing is sent), and again by the daemon under its lock
    // via `expected_existing` — which is the check that closes the window between this read and
    // the write (the #1132 lesson: a binding only the client holds is a race).
    let current = standing_row(&snapshot, &member, &path);
    if replaced_key(&current) != replaced_key(&seen) {
        return Ok(serde_json::json!({ "outcome": "moved", "current": current }));
    }
    let mut body = serde_json::json!({
        "plugin_id": member,
        "path": path,
        "reason": reason,
        "recursive": recursive.unwrap_or(false),
        "expected_existing": replaced_key(&seen),
    });
    if let Some(secs) = expires_in_secs.filter(|s| *s > 0) {
        body["expires_in_secs"] = serde_json::json!(secs);
    }
    let (status, value) =
        daemon::request_status(&state, reqwest::Method::POST, "/api/scope/grant", Some(body)).await?;
    grant_outcome(status, value, current)
}

fn grant_outcome(
    status: reqwest::StatusCode,
    body: serde_json::Value,
    replaced: serde_json::Value,
) -> Result<serde_json::Value, String> {
    if status.is_success() {
        return Ok(serde_json::json!({
            "outcome": "granted",
            "result": body,
            "replaced": replaced,
        }));
    }
    // The daemon's own binding check: the row moved between our read and its lock.
    if status == reqwest::StatusCode::CONFLICT && body.get("moved").and_then(|v| v.as_bool()) == Some(true) {
        return Ok(serde_json::json!({
            "outcome": "moved",
            "current": body.get("current").cloned().unwrap_or(serde_json::Value::Null),
        }));
    }
    // Every other refusal (unknown member, retired, relative path) is the daemon's sentence.
    Err(body
        .get("error")
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .unwrap_or_else(|| format!("daemon returned {status}")))
}

/// A revoke's answer. The routes say "nothing to revoke" two ways — 404 (standing: no such row;
/// live: no such request) and 409 (live: not live any more) — and after the view showed the row,
/// either means another view (or the clock) got there first: `already_revoked`, not an error.
fn revoke_outcome(status: reqwest::StatusCode, body: serde_json::Value) -> Result<serde_json::Value, String> {
    if status.is_success() {
        return Ok(serde_json::json!({ "outcome": "revoked", "result": body }));
    }
    let why = body.get("error").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if status == reqwest::StatusCode::NOT_FOUND || status == reqwest::StatusCode::CONFLICT {
        return Ok(serde_json::json!({ "outcome": "already_revoked", "detail": why }));
    }
    // A 500 from the standing revoke can mean "revoked in memory, the vault write failed — retry":
    // the daemon's sentence says which, so it is passed through whole.
    Err(if why.is_empty() { format!("daemon returned {status}") } else { why })
}

/// Revoke one grant. A live grant is named by its `request_id`; a standing one by (member, path).
#[tauri::command]
pub async fn revoke_reach(
    state: State<'_, AppState>,
    lifetime: String,
    request_id: Option<String>,
    member: Option<String>,
    path: Option<String>,
    reason: Option<String>,
) -> Result<serde_json::Value, String> {
    let reason = check_reason(false, reason.as_deref())?;
    let with_reason = |mut body: serde_json::Value| {
        if let Some(r) = &reason {
            body["reason"] = serde_json::Value::String(r.clone());
        }
        Some(body)
    };
    let post = reqwest::Method::POST;
    let (status, value) = match lifetime.as_str() {
        "live" => {
            let id = request_id.map(|s| s.trim().to_string()).filter(|s| !s.is_empty());
            let Some(id) = id else {
                return Err("a live grant is revoked by its request id".to_string());
            };
            let body = with_reason(serde_json::json!({ "request_id": id }));
            daemon::request_status(&state, post, "/api/scope/revoke", body).await?
        }
        "standing" => {
            let (Some(m), Some(p)) = (member, path) else {
                return Err("a standing grant is revoked by its member and path".to_string());
            };
            let body = with_reason(
                serde_json::json!({ "plugin_id": m.trim(), "path": normalize_scope_path(&p) }),
            );
            daemon::request_status(&state, post, "/api/scope/standing/revoke", body).await?
        }
        other => return Err(format!("unknown grant lifetime '{other}'")),
    };
    revoke_outcome(status, value)
}

// --- Sprint 4b: make standing, reach, reassign ----------------------------------------------
//
// Three acts on grants already in force, each on its own daemon route that already witnesses
// intent -> commit -> terminal. What the app adds is what those routes cannot see: that the
// operator was SHOWN the row being replaced or moved. Promote replaces a standing twin on the
// same path, and reassign moves the source row as it is NOW, so both send the shown row as
// `expected_existing`; the daemon refuses (409 `moved`) under its lock if it changed. Reach only
// flips exact/subtree and the daemon already refuses a no-op, so it needs no binding.

/// One reading of the three routes' answers. `already` / `already_gone` / `moved` are
/// OUTCOMES — another view (or the clock) got there first — not errors.
fn standing_act_outcome(
    act: &str,
    status: reqwest::StatusCode,
    body: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let why = body.get("error").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if status.is_success() {
        if body.get("status").and_then(|v| v.as_str()) == Some("already_standing") {
            return Ok(serde_json::json!({ "outcome": "already", "detail": "already standing — nothing was appended" }));
        }
        return Ok(serde_json::json!({ "outcome": "done", "result": body }));
    }
    if status == reqwest::StatusCode::CONFLICT && body.get("moved").and_then(|v| v.as_bool()) == Some(true) {
        return Ok(serde_json::json!({
            "outcome": "moved",
            "current": body.get("current").cloned().unwrap_or(serde_json::Value::Null),
        }));
    }
    // Reach's 409 is its no-op ("already recursive/exact; nothing witnessed"). Reassign's 409s
    // (same member, destination already holds the path) are the operator's call to resolve.
    if status == reqwest::StatusCode::CONFLICT && act == "reach" {
        return Ok(serde_json::json!({ "outcome": "already", "detail": why }));
    }
    if status == reqwest::StatusCode::NOT_FOUND {
        return Ok(serde_json::json!({ "outcome": "already_gone", "detail": why }));
    }
    Err(if why.is_empty() { format!("daemon returned {status}") } else { why })
}

/// Make a LIVE grant standing. `seen` is the standing row the form showed on that path (null
/// = none); a reason is optional here only because the daemon falls back to the live grant's
/// own recorded reason — and refuses when there is none.
#[tauri::command]
pub async fn promote_grant(
    state: State<'_, AppState>,
    member: String,
    path: String,
    reason: Option<String>,
    seen: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
    let reason = check_reason(false, reason.as_deref())?;
    let path = normalize_scope_path(&path);
    let seen = seen.unwrap_or(serde_json::Value::Null);
    let mut body = serde_json::json!({
        "plugin_id": member.trim(), "path": path, "expected_existing": replaced_key(&seen),
    });
    if let Some(r) = reason {
        body["reason"] = serde_json::Value::String(r);
    }
    let (status, value) =
        daemon::request_status(&state, reqwest::Method::POST, "/api/scope/standing/promote", Some(body)).await?;
    standing_act_outcome("promote", status, value)
}

/// Widen a grant to its subtree (reason required) or narrow it back to exactly its path (none).
#[tauri::command]
pub async fn set_reach(
    state: State<'_, AppState>,
    member: String,
    path: String,
    recursive: bool,
    reason: Option<String>,
) -> Result<serde_json::Value, String> {
    let reason = check_reason(recursive, reason.as_deref()).map_err(|e| {
        if recursive { "making a grant reach its whole subtree requires a reason: it widens one path into a tree".to_string() } else { e }
    })?;
    let mut body = serde_json::json!({
        "plugin_id": member.trim(), "path": normalize_scope_path(&path), "recursive": recursive,
    });
    if let Some(r) = reason {
        body["reason"] = serde_json::Value::String(r);
    }
    let (status, value) =
        daemon::request_status(&state, reqwest::Method::POST, "/api/scope/standing/recursive", Some(body)).await?;
    standing_act_outcome("reach", status, value)
}

/// The destination of a reassign, checked like a grant's member: recorded, unretired, chosen
/// from the list, and not the source.
fn preflight_reassign(snapshot: &serde_json::Value, from: &str, to: &str, path: &str) -> Result<String, String> {
    if from == to {
        return Err("the destination is the member that already holds it".to_string());
    }
    preflight_grant(snapshot, to, path)
}

/// Move ONE standing grant to another member, as one act (a typo'd grant to the real seat).
/// `seen` is the source row as the form showed it; the move is refused if it changed.
#[tauri::command]
pub async fn reassign_grant(
    state: State<'_, AppState>,
    member: String,
    path: String,
    to: String,
    reason: Option<String>,
    seen: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let reason = check_reason(true, reason.as_deref())
        .map_err(|_| "reassigning a grant requires a reason: it widens what the destination can reach".to_string())?
        .unwrap_or_default();
    if seen.is_null() {
        return Err("a reassign moves a row you were shown; none was".to_string());
    }
    let snapshot = daemon::get(&state, "/api/dashboard").await?;
    let path = preflight_reassign(&snapshot, member.trim(), to.trim(), &path)?;
    let body = serde_json::json!({
        "plugin_id": member.trim(), "path": path, "to": to.trim(), "reason": reason,
        "expected_existing": replaced_key(&seen),
    });
    let (status, value) =
        daemon::request_status(&state, reqwest::Method::POST, "/api/scope/standing/reassign", Some(body)).await?;
    standing_act_outcome("reassign", status, value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::StatusCode;
    use serde_json::json;

    fn snap() -> serde_json::Value {
        json!({
            "members": ["claude-code", "hub-being", "caude-code"],
            "retired": ["caude-code"],
            "scope_grants": [
                {"lifetime": "live", "plugin_id": "hub-being", "path": "/w/x", "reason": "asked",
                 "request_id": "r1", "recursive": false, "secs_remaining": 100},
                {"lifetime": "standing", "plugin_id": "hub-being", "path": "/w/x", "reason": "home",
                 "granted_by": "operator", "recursive": true, "expires_at": null, "request_id": null},
            ],
        })
    }

    #[test]
    fn the_path_key_is_the_daemons() {
        assert_eq!(normalize_scope_path(" /w/a/./b/../c/ "), "/w/a/c");
        assert_eq!(normalize_scope_path("/"), "/");
        assert_eq!(normalize_scope_path("w/x"), "w/x");
    }

    #[test]
    fn a_grant_needs_a_reason_and_a_revoke_does_not() {
        assert!(check_reason(true, None).is_err());
        assert!(check_reason(true, Some("  ")).is_err());
        assert_eq!(check_reason(false, None).unwrap(), None);
        assert_eq!(check_reason(false, Some(" done ")).unwrap(), Some("done".into()));
        assert!(check_reason(false, Some(&"x".repeat(513))).is_err());
        assert!(check_reason(true, Some("bell\u{7}")).is_err());
    }

    #[test]
    fn only_a_recorded_unretired_member_and_an_absolute_path_are_granted_to() {
        let s = snap();
        assert_eq!(preflight_grant(&s, "claude-code", "/w/repo/").unwrap(), "/w/repo");
        assert!(preflight_grant(&s, "Claude-code", "/w").unwrap_err().contains("not a member"));
        assert!(preflight_grant(&s, "caude-code", "/w").unwrap_err().contains("retired"));
        assert!(preflight_grant(&s, "claude-code", "w/repo").unwrap_err().contains("absolute"));
    }

    #[test]
    fn the_replaced_row_is_the_standing_one_for_that_member_and_path() {
        let s = snap();
        let r = standing_row(&s, "hub-being", "/w/x");
        assert_eq!(r["reason"], "home");
        assert!(standing_row(&s, "claude-code", "/w/x").is_null());
    }

    /// The last-edit-wins binding: what the form showed must be what is there now.
    #[test]
    fn a_row_that_moved_since_it_was_shown_is_detected() {
        let s = snap();
        let now = standing_row(&s, "hub-being", "/w/x");
        let mut shown = now.clone();
        shown["secs_remaining"] = json!(5); // clock fields are not the grant
        assert_eq!(replaced_key(&now), replaced_key(&shown));
        shown["reason"] = json!("an older reason");
        assert_ne!(replaced_key(&now), replaced_key(&shown));
        // shown none, one exists now: moved
        assert_ne!(replaced_key(&now), replaced_key(&serde_json::Value::Null));
        // shown none, none now: not moved
        assert_eq!(replaced_key(&standing_row(&s, "claude-code", "/w/x")), replaced_key(&serde_json::Value::Null));
    }

    #[test]
    fn the_daemons_moved_refusal_is_an_outcome_and_other_refusals_are_errors() {
        let o = grant_outcome(
            StatusCode::CONFLICT,
            json!({"error": "not the one you were shown", "moved": true, "current": {"reason": "theirs"}}),
            json!(null),
        )
        .unwrap();
        assert_eq!((o["outcome"].clone(), o["current"]["reason"].clone()), (json!("moved"), json!("theirs")));
        let e = grant_outcome(
            StatusCode::CONFLICT,
            json!({"error": "'caude-code' was RETIRED on this seat"}),
            json!(null),
        )
        .unwrap_err();
        assert!(e.contains("RETIRED"));
        let ok = grant_outcome(StatusCode::OK, json!({"ok": true}), json!({"reason": "old"})).unwrap();
        assert_eq!(ok["replaced"]["reason"], "old");
    }

    #[test]
    fn nothing_left_to_revoke_is_an_outcome() {
        for st in [StatusCode::NOT_FOUND, StatusCode::CONFLICT] {
            let o = revoke_outcome(st, json!({"error": "not a live grant: nothing to revoke"})).unwrap();
            assert_eq!(o["outcome"], "already_revoked");
        }
        assert_eq!(revoke_outcome(StatusCode::OK, json!({"ok": true})).unwrap()["outcome"], "revoked");
        let e = revoke_outcome(
            StatusCode::INTERNAL_SERVER_ERROR,
            json!({"error": "revoked in memory but the vault write FAILED — RETRY this same revoke"}),
        )
        .unwrap_err();
        assert!(e.contains("RETRY"), "the retry instruction reaches the operator whole");
    }

    #[test]
    fn the_standing_acts_read_conflicts_as_outcomes_where_they_are() {
        let moved = standing_act_outcome("promote", StatusCode::CONFLICT,
            json!({"error": "not the one you were shown", "moved": true, "current": {"reason": "x"}})).unwrap();
        assert_eq!((moved["outcome"].clone(), moved["current"]["reason"].clone()), (json!("moved"), json!("x")));
        let noop = standing_act_outcome("reach", StatusCode::CONFLICT, json!({"error": "already recursive"})).unwrap();
        assert_eq!(noop["outcome"], "already");
        // a reassign 409 without `moved` is the operator's decision to make, not a race
        assert!(standing_act_outcome("reassign", StatusCode::CONFLICT,
            json!({"error": "'codex' already holds a standing grant on '/w'"})).unwrap_err().contains("already holds"));
        assert_eq!(standing_act_outcome("promote", StatusCode::OK, json!({"status": "already_standing"})).unwrap()["outcome"], "already");
        assert_eq!(standing_act_outcome("promote", StatusCode::OK, json!({"ok": true})).unwrap()["outcome"], "done");
        assert_eq!(standing_act_outcome("reach", StatusCode::NOT_FOUND, json!({"error": "no grant"})).unwrap()["outcome"], "already_gone");
        assert!(standing_act_outcome("reassign", StatusCode::BAD_REQUEST, json!({"error": "reason is required"})).is_err());
    }

    #[test]
    fn a_reassign_goes_only_to_a_recorded_unretired_other_member() {
        let s = snap();
        assert_eq!(preflight_reassign(&s, "caude-code", "claude-code", "/w/x").unwrap(), "/w/x");
        assert!(preflight_reassign(&s, "claude-code", "claude-code", "/w").unwrap_err().contains("already holds it"));
        assert!(preflight_reassign(&s, "claude-code", "Claude-code", "/w").unwrap_err().contains("not a member"));
        assert!(preflight_reassign(&s, "claude-code", "caude-code", "/w").unwrap_err().contains("retired"));
    }
}

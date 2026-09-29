//! Who is on this box, and is it governed — `GET /api/agents`.
//!
//! Read-only in this sprint (3a). The daemon returns the agent inventory's own report:
//! what is installed, what hestia has an adapter for, what is actually governed, and the
//! gaps between them — beings included since hestia #1076, found by their launcher's
//! `--member` rather than by a config file they do not have.
//!
//! When the inventory cannot run, the daemon answers `status: UNKNOWN` with a reason
//! rather than an empty list, because an empty list reads as "nothing ungoverned here" —
//! the exact inversion the surface exists to prevent. This command passes that through
//! untouched; `pages/Agents.tsx` must render it as the reason, never as a clean table.

use tauri::State;

use crate::{daemon, AppState};

#[tauri::command]
pub async fn agents_inventory(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    daemon::get(&state, "/api/agents").await
}

// --- Sprint 3b: retire / reinstate ---------------------------------------------------------
//
// Both are operator acts on THIS seat's registry, and both routes already witness INTENT ->
// COMMIT -> RECORD (`agent_retire`, `agent_reinstate`). The app's job is to not soften them:
//
//  * RETIRE revokes the id's standing grants. The daemon refuses (409) an id that has ACTED in
//    the last 24h unless `confirm_active` is sent, and says how many acts — that count is what
//    tells the three look-alike ids apart. The app shows that refusal as a question with its
//    evidence (`needs_confirmation`), never as a failure, and never pre-ticks the confirmation.
//  * Retiring an id that is ALREADY retired would replace the recorded reason (last edit wins,
//    ruled 2026-09-25). The app re-reads first and, if another view got there, reports
//    `already_retired` with the reason on record instead of silently overwriting it.
//  * REINSTATE does not restore the revoked grants, by design; the result names them so the
//    operator can re-grant deliberately. A 404 ("not retired on this seat") after the view
//    showed it retired means another view reinstated it first: `already_reinstated`.
//
// `connect` is deliberately not here: `/api/orchestrators/:id/connect` wires only a PostToolUse
// WITNESS hook, not the gate, so a button beside an UNGOVERNED row would promise governance it
// does not deliver. Governing is the members' installer's act (hestia-deploy). See
// docs/SPRINTS_APP_SURFACES.md, Sprint 3b.

const TEXT_MAX: usize = 512;

/// Member ids travel in a URL path segment. Accept the spellings this fleet uses and refuse the
/// rest here, rather than percent-encode something the daemon would then fail to find.
fn check_member_id(id: &str) -> Result<String, String> {
    // One rule for member ids on this surface: `checked_member`, which bypass/restore use too.
    checked_member(id).map(str::to_string)
}

fn check_text(what: &str, v: Option<&str>) -> Result<String, String> {
    let t = v.map(str::trim).unwrap_or("");
    if t.is_empty() {
        return Err(format!("{what} is required"));
    }
    if t.len() > TEXT_MAX {
        return Err(format!("{what} is {} bytes; at most {TEXT_MAX}", t.len()));
    }
    if t.chars().any(char::is_control) {
        return Err(format!("{what} contains a control character"));
    }
    Ok(t.to_string())
}

/// The daemon's retire answer, as an outcome the view can render without guessing.
fn retire_outcome(status: reqwest::StatusCode, body: serde_json::Value) -> Result<serde_json::Value, String> {
    if status.is_success() {
        return Ok(serde_json::json!({ "outcome": "retired", "result": body }));
    }
    let why = body.get("error").and_then(|v| v.as_str()).unwrap_or("").to_string();
    // The live-member guard is the one 409 that is a question, not a race: it carries the
    // evidence (`acts_recently`, or `unmeasurable`) the operator must weigh.
    if status == reqwest::StatusCode::CONFLICT
        && (body.get("acts_recently").is_some() || body.get("unmeasurable").is_some())
    {
        return Ok(serde_json::json!({
            "outcome": "needs_confirmation",
            "detail": why,
            "acts_recently": body.get("acts_recently").cloned().unwrap_or(serde_json::Value::Null),
            "unmeasurable": body.get("unmeasurable").and_then(|v| v.as_bool()).unwrap_or(false),
            "window_hours": body.get("window_hours").cloned().unwrap_or(serde_json::Value::Null),
        }));
    }
    Err(if why.is_empty() { format!("daemon returned {status}") } else { why })
}

fn reinstate_outcome(status: reqwest::StatusCode, body: serde_json::Value) -> Result<serde_json::Value, String> {
    if status.is_success() {
        return Ok(serde_json::json!({ "outcome": "reinstated", "result": body }));
    }
    let why = body.get("error").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if status == reqwest::StatusCode::NOT_FOUND {
        return Ok(serde_json::json!({ "outcome": "already_reinstated", "detail": why }));
    }
    Err(if why.is_empty() { format!("daemon returned {status}") } else { why })
}

#[tauri::command]
pub async fn retire_agent(
    state: State<'_, AppState>,
    id: String,
    reason: Option<String>,
    evidence_ref: Option<String>,
    confirm_active: Option<bool>,
) -> Result<serde_json::Value, String> {
    let id = check_member_id(&id)?;
    let reason = check_text("a reason", reason.as_deref())?;
    let evidence_ref = check_text(
        "a reference (what establishes this — a ruling, a finding, an issue)",
        evidence_ref.as_deref(),
    )?;
    // Last edit wins in the engine, so look before replacing: an id another view already
    // retired keeps the reason it was retired for.
    let snap = daemon::get(&state, "/api/dashboard").await?;
    if let Some(already) = already_retired(&snap, &id) {
        return Ok(already);
    }
    let body = serde_json::json!({
        "reason": reason,
        "ref": evidence_ref,
        "confirm_active": confirm_active.unwrap_or(false),
    });
    let (status, value) =
        daemon::request_status(&state, reqwest::Method::POST, &format!("/api/agents/{id}/retire"), Some(body))
            .await?;
    retire_outcome(status, value)
}

fn already_retired(snapshot: &serde_json::Value, id: &str) -> Option<serde_json::Value> {
    let listed = snapshot
        .get("retired")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().any(|x| x.as_str() == Some(id)))
        .unwrap_or(false);
    listed.then(|| {
        serde_json::json!({
            "outcome": "already_retired",
            "detail": format!("'{id}' was already retired on this seat — another view got there first. \
                               Nothing was sent, so the reason on record stands."),
        })
    })
}

#[tauri::command]
pub async fn reinstate_agent(
    state: State<'_, AppState>,
    id: String,
    reason: Option<String>,
) -> Result<serde_json::Value, String> {
    let id = check_member_id(&id)?;
    let reason = check_text("a reason", reason.as_deref())?;
    let (status, value) = daemon::request_status(
        &state,
        reqwest::Method::POST,
        &format!("/api/agents/{id}/reinstate"),
        Some(serde_json::json!({ "reason": reason })),
    )
    .await?;
    reinstate_outcome(status, value)
}

/// A member id as the daemon's route takes it. Refused rather than encoded: member ids are
/// `[A-Za-z0-9_.-]`, and anything else is not one.
fn checked_member(member: &str) -> Result<&str, String> {
    let m = member.trim();
    if m.is_empty() || m.starts_with('.') || !m.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.')) {
        return Err(format!("'{member}' is not a member id"));
    }
    Ok(m)
}

/// Bypass a member's gate — `POST /api/agents/:id/bypass` (dp, 2026-09-28: "useful for instances
/// when an update locks out a member that we need to be active to fix the issues"). Fail OPEN: the
/// member acts ungoverned until restored. The permitting direction, so a reason is required here
/// before the daemon (which requires it too) is asked.
#[tauri::command]
pub async fn agent_gate_bypass(
    state: State<'_, AppState>,
    member: String,
    reason: Option<String>,
) -> Result<serde_json::Value, String> {
    let m = checked_member(&member)?;
    let reason = reason.as_deref().map(str::trim).unwrap_or("");
    if reason.is_empty() {
        return Err("bypassing a gate requires a reason: it records why this member may act ungoverned".to_string());
    }
    let path = format!("/api/agents/{m}/bypass");
    daemon::send(&state, reqwest::Method::POST, &path, Some(serde_json::json!({ "reason": reason }))).await
}

/// Put a bypassed member's gate back exactly — `POST /api/agents/:id/restore`. The refusing
/// direction: no reason required. A refusal (the registration changed since) is passed through.
#[tauri::command]
pub async fn agent_gate_restore(
    state: State<'_, AppState>,
    member: String,
) -> Result<serde_json::Value, String> {
    let m = checked_member(&member)?;
    let path = format!("/api/agents/{m}/restore");
    daemon::send(&state, reqwest::Method::POST, &path, Some(serde_json::json!({}))).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::StatusCode;
    use serde_json::json;

    #[test]
    fn ids_that_cannot_travel_in_a_path_are_refused_here() {
        assert_eq!(check_member_id(" claude-code ").unwrap(), "claude-code");
        assert!(check_member_id("hub-being").is_ok());
        assert!(check_member_id("").is_err());
        assert!(check_member_id("../vault").is_err());
        assert!(check_member_id("a/b").is_err());
        assert!(check_member_id("a b").is_err());
    }

    #[test]
    fn retire_needs_both_a_reason_and_a_reference() {
        assert!(check_text("a reason", None).is_err());
        assert!(check_text("a reason", Some("   ")).is_err());
        assert!(check_text("a reason", Some(&"x".repeat(513))).is_err());
        assert!(check_text("a reason", Some("bell\u{7}")).is_err());
        assert_eq!(check_text("a reason", Some(" typo id ")).unwrap(), "typo id");
    }

    /// The guard's 409 is a question carrying evidence, not a failure and not a race.
    #[test]
    fn a_live_member_refusal_is_a_question_with_its_evidence() {
        let out = retire_outcome(
            StatusCode::CONFLICT,
            json!({"error": "this id has taken 5415 act(s) in the last 24h", "acts_recently": 5415, "window_hours": 24}),
        )
        .unwrap();
        assert_eq!(out["outcome"], "needs_confirmation");
        assert_eq!(out["acts_recently"], 5415);
        assert!(out["detail"].as_str().unwrap().contains("5415"));

        let out = retire_outcome(
            StatusCode::CONFLICT,
            json!({"error": "could not measure", "acts_recently": null, "unmeasurable": true}),
        )
        .unwrap();
        assert_eq!((out["outcome"].clone(), out["unmeasurable"].clone()), (json!("needs_confirmation"), json!(true)));
    }

    #[test]
    fn other_refusals_stay_errors() {
        assert!(retire_outcome(StatusCode::BAD_REQUEST, json!({"error": "reason and ref are required"})).is_err());
        // a 409 WITHOUT the guard's evidence is not a question to confirm through
        assert!(retire_outcome(StatusCode::CONFLICT, json!({"error": "something else"})).is_err());
        assert!(reinstate_outcome(StatusCode::INTERNAL_SERVER_ERROR, json!({"error": "still retired: disk"})).is_err());
    }

    #[test]
    fn a_reinstate_another_view_already_made_is_an_outcome() {
        let out = reinstate_outcome(StatusCode::NOT_FOUND, json!({"error": "'x' is not retired on this seat"})).unwrap();
        assert_eq!(out["outcome"], "already_reinstated");
        let out = reinstate_outcome(StatusCode::OK, json!({"ok": true, "grants_not_restored": ["/w"]})).unwrap();
        assert_eq!(out["result"]["grants_not_restored"], json!(["/w"]));
    }

    /// Last edit wins in the engine; the app must not overwrite a retirement it did not see.
    #[test]
    fn an_id_already_retired_elsewhere_is_not_sent_again() {
        let snap = json!({"retired": ["caude-code"]});
        assert_eq!(already_retired(&snap, "caude-code").unwrap()["outcome"], "already_retired");
        assert!(already_retired(&snap, "claude-code").is_none());
        assert!(already_retired(&json!({}), "claude-code").is_none());
    }

    #[test]
    fn only_member_ids_reach_the_route() {
        assert_eq!(checked_member("kimi-code").unwrap(), "kimi-code");
        assert!(checked_member("../x").is_err());
        assert!(checked_member("a/b").is_err());
        assert!(checked_member("").is_err());
    }
}

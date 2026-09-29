//! Gate integrity — verify what is installed, and ratify it as the trusted build.
//!
//! `POST /api/gates/ratify` is the operator asserting "these installed gate bytes are
//! the build I trust". The daemon's own words: *"nothing here can tell a good build
//! from a bad one; the operator must ratify from a state they believe correct."* The
//! installer deliberately never ratifies, so it cannot bless a tampered build, and
//! until this surface there was no UI, CLI verb or dashboard control that could —
//! only a hand-signed HTTP call. This is the operator's strong channel for it.
//!
//! Per gate (dp 2026-09-28): a named gate's ratification merges into the others; ratify-all
//! is accepted by the daemon only when every gate is the bytes the deploy installed. Stale
//! expectations are forgotten per path. The view re-reads the gates immediately before a
//! write; see `pages/Gates.tsx`. The reason rule mirrors the daemon's.

use tauri::State;

use crate::{daemon, AppState};

const REASON_MAX: usize = 512;

fn check_reason(reason: Option<&str>) -> Result<String, String> {
    let r = reason.map(str::trim).unwrap_or("");
    if r.is_empty() {
        return Err(
            "ratifying requires a reason: it records why these bytes are the ones you trust, \
             and the chain entry is what makes that judgement reviewable"
                .to_string(),
        );
    }
    if r.len() > REASON_MAX {
        return Err(format!("reason is {} bytes; the daemon accepts at most {REASON_MAX}", r.len()));
    }
    if r.chars().any(char::is_control) {
        return Err("reason contains a control character".to_string());
    }
    Ok(r.to_string())
}

/// `GET /api/gates/verify`: the verdict per discovered gate, plus the evidence — the
/// bytes installed now and what the deployment authority recorded installing.
#[tauri::command]
pub async fn gates_verify(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    daemon::get(&state, "/api/gates/verify").await
}

/// Ratify named gates (`paths`), merged into the rest; with no `paths`, every discovered gate,
/// which the daemon accepts only when all of them are the bytes the deploy installed.
#[tauri::command]
pub async fn gates_ratify(
    state: State<'_, AppState>,
    reason: Option<String>,
    expected: Option<serde_json::Value>,
    paths: Option<Vec<String>>,
) -> Result<serde_json::Value, String> {
    let reason = check_reason(reason.as_deref())?;
    // The bytes the operator reviewed (`evidence.current` from verify). The daemon refuses
    // the ratify unless the installed gates still match them, so the binding holds for
    // every caller, not only this app.
    let expected = expected.ok_or("ratifying requires the reviewed gate digests (evidence.current)")?;
    daemon::send(&state, reqwest::Method::POST, "/api/gates/ratify", Some(ratify_body(reason, expected, paths)?))
        .await
}

fn ratify_body(
    reason: String,
    expected: serde_json::Value,
    paths: Option<Vec<String>>,
) -> Result<serde_json::Value, String> {
    let mut body = serde_json::json!({ "reason": reason, "expected": expected });
    if let Some(p) = paths {
        if p.is_empty() {
            return Err("name at least one gate to ratify, or ratify all".to_string());
        }
        body["paths"] = serde_json::json!(p);
    }
    Ok(body)
}

/// Remove the expectations for gates this machine no longer wires. The daemon refuses a
/// gate it still discovers (forgetting a live gate would quiet a MODIFIED finding).
#[tauri::command]
pub async fn gates_forget(
    state: State<'_, AppState>,
    reason: Option<String>,
    paths: Vec<String>,
) -> Result<serde_json::Value, String> {
    let reason = check_reason(reason.as_deref())?;
    if paths.is_empty() {
        return Err("name the expectations to forget; there is no forget-all".to_string());
    }
    daemon::send(
        &state,
        reqwest::Method::POST,
        "/api/gates/forget",
        Some(serde_json::json!({ "reason": reason, "paths": paths })),
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ratify_without_a_reason_is_refused_here() {
        assert!(check_reason(None).unwrap_err().contains("requires a reason"));
        assert!(check_reason(Some("   ")).unwrap_err().contains("requires a reason"));
    }

    #[test]
    fn a_per_gate_ratify_names_its_gates_and_bulk_names_none() {
        let e = serde_json::json!({"/g/a.py": "aaa"});
        let b = ratify_body("r".into(), e.clone(), Some(vec!["/g/a.py".into()])).unwrap();
        assert_eq!(b["paths"], serde_json::json!(["/g/a.py"]));
        assert!(ratify_body("r".into(), e.clone(), None).unwrap().get("paths").is_none());
        assert!(ratify_body("r".into(), e, Some(vec![])).is_err());
    }

    #[test]
    fn a_ratify_reason_is_trimmed_bounded_and_control_free() {
        assert_eq!(check_reason(Some("  matches deploy 4d59496  ")).unwrap(), "matches deploy 4d59496");
        assert!(check_reason(Some(&"x".repeat(REASON_MAX + 1))).unwrap_err().contains("at most"));
        assert!(check_reason(Some("a\u{7}b")).unwrap_err().contains("control"));
    }
}

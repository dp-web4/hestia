//! Gate integrity — verify what is installed, and ratify it as the trusted build.
//!
//! `POST /api/gates/ratify` is the operator asserting "these installed gate bytes are
//! the build I trust". The daemon's own words: *"nothing here can tell a good build
//! from a bad one; the operator must ratify from a state they believe correct."* The
//! installer deliberately never ratifies, so it cannot bless a tampered build, and
//! until this surface there was no UI, CLI verb or dashboard control that could —
//! only a hand-signed HTTP call. This is the operator's strong channel for it.
//!
//! Ratification replaces the previous expectations (last edit wins, dp 2026-09-25),
//! so the view shows what it replaces and re-reads the gates immediately before the
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

/// Ratify every discovered gate's CURRENT bytes as the trusted build.
#[tauri::command]
pub async fn gates_ratify(
    state: State<'_, AppState>,
    reason: Option<String>,
    expected: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
    let reason = check_reason(reason.as_deref())?;
    // The bytes the operator reviewed (`evidence.current` from verify). The daemon refuses
    // the ratify unless the installed gates still match them, so the binding holds for
    // every caller, not only this app.
    let expected = expected.ok_or("ratifying requires the reviewed gate digests (evidence.current)")?;
    daemon::send(
        &state,
        reqwest::Method::POST,
        "/api/gates/ratify",
        Some(serde_json::json!({ "reason": reason, "expected": expected })),
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
    fn a_ratify_reason_is_trimmed_bounded_and_control_free() {
        assert_eq!(check_reason(Some("  matches deploy 4d59496  ")).unwrap(), "matches deploy 4d59496");
        assert!(check_reason(Some(&"x".repeat(REASON_MAX + 1))).unwrap_err().contains("at most"));
        assert!(check_reason(Some("a\u{7}b")).unwrap_err().contains("control"));
    }
}

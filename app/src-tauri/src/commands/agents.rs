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
    use super::checked_member;

    #[test]
    fn only_member_ids_reach_the_route() {
        assert_eq!(checked_member("kimi-code").unwrap(), "kimi-code");
        assert!(checked_member("../x").is_err());
        assert!(checked_member("a/b").is_err());
        assert!(checked_member("").is_err());
    }
}

//! Delegations — authority the operator delegates to one member (Sprint 4c).
//!
//! `GET/POST /api/agents/:id/delegations` and `POST …/:deleg/revoke`, the operator-plane form of
//! `hestia delegate grant/list/revoke`. The daemon's rules, not softened here:
//!
//!  * The agent is named ONLY by the URL. Its delegation key is derived from the member registry,
//!    never typed, and a typed agent in the body is refused (#1067). So the app picks the member
//!    from the registry and sends nothing else that names an identity.
//!  * Roles come from the daemon's closed list (`roles` in the GET answer): a free-text role is a
//!    typed identity by another name. Actions are an open vocabulary; the daemon reads each the
//!    way the enforcer will, refuses one that binds nothing (409), and names any verb it does not
//!    interpret as `unvalidated_actions`. The app shows that list whole rather than a bare "ok".
//!  * A grant with no roles and no actions is full authority and is refused.
//!  * GRANT needs a reason. REVOKE also needs one — the daemon's contract, pinned by its own test
//!    and the dashboard's. That inverts the asymmetry every other surface here keeps (narrowing
//!    never costs more than widening); it is raised with the owner rather than changed here.
//!  * A delegation is created, never replaced: there is no last-edit-wins overwrite to bind.
//!    Revoking one already revoked is the `already_revoked` outcome, not an error.

use tauri::State;

use crate::{daemon, AppState};

const TEXT_MAX: usize = 512;

/// A member id as the daemon's route takes it: `[A-Za-z0-9_.-]`, no leading dot.
fn checked_member(member: &str) -> Result<&str, String> {
    let m = member.trim();
    if m.is_empty()
        || m.starts_with('.')
        || !m.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.'))
    {
        return Err(format!("'{member}' is not a member id"));
    }
    Ok(m)
}

/// A delegation id as the route takes it: a hyphenated UUID, and nothing that could steer the path.
fn checked_uuid(id: &str) -> Result<String, String> {
    let t = id.trim();
    let ok = t.len() == 36
        && t.char_indices().all(|(i, c)| if matches!(i, 8 | 13 | 18 | 23) { c == '-' } else { c.is_ascii_hexdigit() });
    if ok { Ok(t.to_ascii_lowercase()) } else { Err("delegation id is not a UUID".to_string()) }
}

fn required_reason(reason: Option<&str>, act: &str) -> Result<String, String> {
    let t = reason.map(str::trim).unwrap_or("");
    if t.is_empty() {
        return Err(format!("{act} requires a reason"));
    }
    if t.len() > TEXT_MAX {
        return Err(format!("reason is {} bytes; at most {TEXT_MAX}", t.len()));
    }
    if t.chars().any(char::is_control) {
        return Err("reason contains a control character".to_string());
    }
    Ok(t.to_string())
}

/// Everything a grant body may carry, checked before it leaves. Returns the body.
fn grant_body(
    roles: &[String],
    actions: &[String],
    expires_hours: Option<u64>,
    reason: Option<&str>,
) -> Result<serde_json::Value, String> {
    let reason = required_reason(reason, "delegating authority")?;
    let clean = |v: &[String]| -> Vec<String> {
        v.iter().map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect()
    };
    let (roles, actions) = (clean(roles), clean(actions));
    if roles.is_empty() && actions.is_empty() {
        return Err(
            "name what is delegated: a delegation with no roles and no actions is full authority"
                .to_string(),
        );
    }
    let mut body = serde_json::json!({ "roles": roles, "actions": actions, "reason": reason });
    if let Some(h) = expires_hours.filter(|h| *h > 0) {
        body["expires_hours"] = serde_json::json!(h);
    }
    Ok(body)
}

fn revoke_outcome(status: reqwest::StatusCode, body: serde_json::Value) -> Result<serde_json::Value, String> {
    if status.is_success() {
        if body.get("already_revoked").and_then(|v| v.as_bool()) == Some(true) {
            return Ok(serde_json::json!({ "outcome": "already_revoked" }));
        }
        return Ok(serde_json::json!({ "outcome": "revoked", "result": body }));
    }
    let why = body.get("error").and_then(|v| v.as_str()).unwrap_or("").to_string();
    Err(if why.is_empty() { format!("daemon returned {status}") } else { why })
}

/// This member's delegations (revoked ones stay listed), the role vocabulary, and whether it is
/// retired — in which case its history is readable and nothing may be granted to it.
#[tauri::command]
pub async fn delegations_list(
    state: State<'_, AppState>,
    member: String,
) -> Result<serde_json::Value, String> {
    let m = checked_member(&member)?;
    daemon::get(&state, &format!("/api/agents/{m}/delegations")).await
}

#[tauri::command]
pub async fn delegation_grant(
    state: State<'_, AppState>,
    member: String,
    roles: Vec<String>,
    actions: Vec<String>,
    expires_hours: Option<u64>,
    reason: Option<String>,
) -> Result<serde_json::Value, String> {
    let m = checked_member(&member)?;
    let body = grant_body(&roles, &actions, expires_hours, reason.as_deref())?;
    daemon::send(&state, reqwest::Method::POST, &format!("/api/agents/{m}/delegations"), Some(body)).await
}

#[tauri::command]
pub async fn delegation_revoke(
    state: State<'_, AppState>,
    member: String,
    delegation_id: String,
    reason: Option<String>,
) -> Result<serde_json::Value, String> {
    let m = checked_member(&member)?;
    let id = checked_uuid(&delegation_id)?;
    let reason = required_reason(reason.as_deref(), "revoking a delegation (the daemon's rule)")?;
    let (status, value) = daemon::request_status(
        &state,
        reqwest::Method::POST,
        &format!("/api/agents/{m}/delegations/{id}/revoke"),
        Some(serde_json::json!({ "reason": reason })),
    )
    .await?;
    revoke_outcome(status, value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::StatusCode;
    use serde_json::json;

    #[test]
    fn only_member_ids_reach_the_route() {
        assert_eq!(checked_member(" kimi-code ").unwrap(), "kimi-code");
        for bad in ["", "../x", "a/b", ".hidden", "a b"] {
            assert!(checked_member(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn a_grant_names_what_it_delegates_and_why_and_no_identity() {
        assert!(grant_body(&[], &[], None, Some("r")).unwrap_err().contains("full authority"));
        assert!(grant_body(&["witness".into()], &[], None, None).unwrap_err().contains("requires a reason"));
        let b = grant_body(&[" witness ".into(), "".into()], &["ledger.read".into()], Some(8), Some(" audit ")).unwrap();
        assert_eq!(b, json!({"roles": ["witness"], "actions": ["ledger.read"], "reason": "audit", "expires_hours": 8}));
        // the body carries no agent key of any spelling — the daemon refuses one (#1067)
        for k in ["agent", "agent_id", "agent_lct_id", "plugin_id"] {
            assert!(b.get(k).is_none(), "{k}");
        }
        assert!(grant_body(&["witness".into()], &[], Some(0), Some("r")).unwrap().get("expires_hours").is_none());
    }

    #[test]
    fn a_delegation_id_is_a_uuid_and_nothing_else() {
        assert!(checked_uuid("3f7b70d0-13d9-4049-b048-d87528810de1").is_ok());
        for bad in ["", "3f7b70d0", "../../revoke", "3f7b70d0-13d9-4049-b048-d87528810de1/x", "3f7b70d0x13d9-4049-b048-d87528810de1"] {
            assert!(checked_uuid(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn a_revoke_already_made_is_an_outcome() {
        assert_eq!(revoke_outcome(StatusCode::OK, json!({"ok": true, "already_revoked": true})).unwrap()["outcome"], "already_revoked");
        assert_eq!(revoke_outcome(StatusCode::OK, json!({"ok": true})).unwrap()["outcome"], "revoked");
        assert!(revoke_outcome(StatusCode::CONFLICT, json!({"error": "does not belong to 'x'"})).unwrap_err().contains("does not belong"));
    }
}

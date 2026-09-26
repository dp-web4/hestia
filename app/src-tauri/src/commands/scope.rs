//! Ruling a scope request — a member asked for reach on a path.
//!
//! `POST /api/scope/decide` behind `operator_gate`, like the escalation channel.
//! The daemon's own rules are mirrored here so the app states them instead of
//! relaying a 400, and so the UI cannot invert them:
//!
//!  * A GRANT needs a reason; a REFUSAL does not. In the daemon's words: *"widening
//!    needs a stated why, narrowing does not. Refusing is the safe direction and
//!    must never carry more friction than approving."*
//!  * A STANDING refusal is not a thing — refusing is already durable in effect,
//!    and a re-ask files a new record. `standing` is offered only with a grant.
//!  * EXACT by default. A request names one path; recursion is the operator's
//!    explicit choice at decide time and never something the asker can set.
//!
//! A ruling is single-shot. The daemon answers 409 for a request already decided
//! or expired — often because another view of the same engine (the dashboard, the
//! CLI) got there first — and that comes back as the `already_decided` OUTCOME,
//! not an error. See `decide.rs` and PRD §1a.

use tauri::State;

use crate::{daemon, AppState};

const REASON_MAX: usize = 512;

/// What the app sends, validated to the daemon's own rules before it leaves.
#[derive(Debug, PartialEq)]
struct Ruling {
    reason: Option<String>,
    standing: bool,
    recursive: bool,
}

fn check_ruling(
    granted: bool,
    reason: Option<&str>,
    standing: bool,
    recursive: bool,
) -> Result<Ruling, String> {
    let trimmed = reason.map(str::trim).unwrap_or("");
    if trimmed.len() > REASON_MAX {
        return Err(format!(
            "reason is {} bytes; the daemon accepts at most {REASON_MAX}",
            trimmed.len()
        ));
    }
    if trimmed.chars().any(char::is_control) {
        return Err("reason contains a control character".to_string());
    }
    if granted && trimmed.is_empty() {
        return Err(
            "granting reach requires a reason: it widens what a member can touch, and the \
             member reads these words — a refusal is what costs nothing to explain"
                .to_string(),
        );
    }
    if standing && !granted {
        return Err(
            "a standing refusal is not a thing: refusing is already durable in effect, and a \
             re-ask files a new record"
                .to_string(),
        );
    }
    Ok(Ruling {
        reason: (!trimmed.is_empty()).then(|| trimmed.to_string()),
        standing,
        recursive,
    })
}

/// Grant or refuse one pending scope request, as the signed-in operator.
///
/// `{ outcome: "decided", result }` when this call ruled;
/// `{ outcome: "already_decided", detail }` when another view got there first.
#[tauri::command]
pub async fn rule_scope_request(
    state: State<'_, AppState>,
    request_id: String,
    granted: bool,
    reason: Option<String>,
    standing: Option<bool>,
    recursive: Option<bool>,
) -> Result<serde_json::Value, String> {
    let request_id = request_id.trim().to_string();
    if request_id.is_empty() {
        return Err("no scope request id".to_string());
    }
    // Both default to false, as the daemon's do: exact, and not standing.
    let r = check_ruling(
        granted,
        reason.as_deref(),
        standing.unwrap_or(false),
        recursive.unwrap_or(false),
    )?;

    let mut body = serde_json::json!({
        "request_id": request_id,
        "granted": granted,
        "standing": r.standing,
        "recursive": r.recursive,
    });
    if let Some(reason) = r.reason {
        body["reason"] = serde_json::Value::String(reason);
    }
    match daemon::send_checked(&state, reqwest::Method::POST, "/api/scope/decide", Some(body)).await
    {
        Ok(result) => Ok(serde_json::json!({ "outcome": "decided", "result": result })),
        Err(daemon::Refused::Conflict(detail)) => {
            Ok(serde_json::json!({ "outcome": "already_decided", "detail": detail }))
        }
        Err(daemon::Refused::Other(e)) => Err(e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_grant_without_a_reason_is_refused_here() {
        let e = check_ruling(true, None, false, false).unwrap_err();
        assert!(e.contains("requires a reason"), "{e}");
        let e = check_ruling(true, Some("  "), false, false).unwrap_err();
        assert!(e.contains("requires a reason"), "{e}");
    }

    #[test]
    fn a_refusal_needs_no_reason_and_keeps_one_if_given() {
        // The daemon's asymmetry: refusing must never carry more friction than
        // approving. Requiring words to refuse would invert it.
        let r = check_ruling(false, None, false, false).unwrap();
        assert_eq!(r.reason, None);
        let r = check_ruling(false, Some(" that path does not exist "), false, false).unwrap();
        assert_eq!(r.reason.as_deref(), Some("that path does not exist"));
    }

    #[test]
    fn a_standing_refusal_is_refused() {
        let e = check_ruling(false, None, true, false).unwrap_err();
        assert!(e.contains("standing refusal"), "{e}");
        assert!(check_ruling(true, Some("ok"), true, false).is_ok());
    }

    #[test]
    fn exact_and_not_standing_by_default() {
        let r = check_ruling(true, Some("read-only probe"), false, false).unwrap();
        assert!(!r.recursive && !r.standing);
    }
}

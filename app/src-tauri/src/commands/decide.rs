//! Deciding a governance-surface escalation — the STRONG channel.
//!
//! `POST /api/operator/gate-escalation` sits behind `operator_gate`, so the caller
//! has proved an operator LCT by challenge/response. That is what separates it
//! from `hestia gate approve` on the CLI, which is authenticated only by
//! filesystem access to `HESTIA_HOME` — the same access every member on the box
//! already has, including the agent whose write is being judged.
//!
//! The app holds the operator key in its own encrypted vault (Sprint A, #298), so
//! this is the one surface that can drive that channel as designed. Every call
//! here goes through the authed transport, which attaches the operator bearer
//! token and re-authenticates once from the unlocked vault if the session
//! lapsed — so a decision never silently degrades to the weaker path. There is
//! deliberately no CLI fallback in this file.
//!
//! # Racing the machine's other views
//!
//! The daemon serves its own web dashboard and the CLI drives the same state.
//! All three are views onto ONE engine, and the engine is the arbiter: a
//! decision is single-shot (`DecideError::AlreadyDecided`) and the loser of a
//! race gets 409. That is correct and this file does not try to improve on it.
//!
//! What this file must get right is the REPORT. A 409 means the operator's
//! intent was already settled — by their own other window, or by a peer — and
//! calling that "error" teaches them that the app is unreliable when it is the
//! engine working. So the outcome is typed: `decided` when this call ruled,
//! `already_decided` when another view did, with the daemon's own sentence
//! carried through. Only a real failure is an `Err`.

use tauri::State;

use crate::{daemon, AppState};

/// The daemon requires a reason to APPROVE and none to DENY
/// (`core/src/server/http.rs`): refusing is the default and costs nothing to
/// explain, while permitting is the act that will be read back later. Enforced
/// here too, so the app states the rule instead of relaying a 400 — and so the
/// UI cannot invert the asymmetry by making deny feel like the one needing
/// defence. The bound matches the daemon's own: non-empty, <= 512 bytes, no
/// control characters.
const REASON_MAX: usize = 512;

fn check_reason(approve: bool, reason: Option<&str>) -> Result<Option<String>, String> {
    let trimmed = reason.map(str::trim).unwrap_or("");
    if !approve {
        // A deny may carry a reason, and does not require one.
        return Ok(if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        });
    }
    if trimmed.is_empty() {
        return Err(
            "approving a governance write requires a reason: the daemon records it as the basis \
             for permitting the act, and a denial is what costs nothing to explain"
                .to_string(),
        );
    }
    if trimmed.len() > REASON_MAX {
        return Err(format!(
            "reason is {} bytes; the daemon accepts at most {REASON_MAX}",
            trimmed.len()
        ));
    }
    if trimmed.chars().any(char::is_control) {
        return Err("reason contains a control character".to_string());
    }
    Ok(Some(trimmed.to_string()))
}

/// Approve or deny one pending escalation, as the signed-in operator.
///
/// Returns the daemon's own answer rather than a synthesised success: whether an
/// approval actually permits the write depends on the bar the escalation was
/// filed under, and this command must not claim more than the daemon said.
///
/// `{ outcome: "decided", result }` when this call ruled;
/// `{ outcome: "already_decided", detail }` when another view got there first.
#[tauri::command]
pub async fn decide_gate_escalation(
    state: State<'_, AppState>,
    id: String,
    approve: bool,
    reason: Option<String>,
) -> Result<serde_json::Value, String> {
    let id = id.trim().to_string();
    if id.is_empty() {
        return Err("no escalation id".to_string());
    }
    let reason = check_reason(approve, reason.as_deref())?;

    let mut body = serde_json::json!({ "id": id, "approve": approve });
    if let Some(r) = reason {
        body["reason"] = serde_json::Value::String(r);
    }
    match daemon::send_checked(
        &state,
        reqwest::Method::POST,
        "/api/operator/gate-escalation",
        Some(body),
    )
    .await
    {
        Ok(result) => Ok(serde_json::json!({ "outcome": "decided", "result": result })),
        // Not an error: the engine settled this already, on this machine or
        // another view of it. The caller re-reads the queue and shows what is.
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
    fn approve_without_a_reason_is_refused_here_not_at_the_daemon() {
        let err = check_reason(true, None).unwrap_err();
        assert!(err.contains("requires a reason"), "{err}");
        let err = check_reason(true, Some("   ")).unwrap_err();
        assert!(err.contains("requires a reason"), "{err}");
    }

    #[test]
    fn deny_needs_no_reason_and_keeps_one_if_given() {
        assert_eq!(check_reason(false, None).unwrap(), None);
        assert_eq!(check_reason(false, Some("  ")).unwrap(), None);
        assert_eq!(
            check_reason(false, Some(" not now ")).unwrap(),
            Some("not now".to_string())
        );
    }

    #[test]
    fn an_approve_reason_is_trimmed_bounded_and_control_free() {
        assert_eq!(
            check_reason(true, Some("  peer corroborated  ")).unwrap(),
            Some("peer corroborated".to_string())
        );
        let long = "x".repeat(REASON_MAX + 1);
        assert!(check_reason(true, Some(&long)).unwrap_err().contains("at most"));
        assert!(check_reason(true, Some("bad\u{0007}reason"))
            .unwrap_err()
            .contains("control character"));
    }
}

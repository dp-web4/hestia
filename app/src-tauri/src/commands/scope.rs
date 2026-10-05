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
    once: bool,
    grant_path: Option<String>,
}

/// The breadth rule the daemon enforces (2026-10-05): `grant_path` is the asked path or a
/// directory ABOVE it at a separator, never the root, and an ancestor is always recursive.
fn check_breadth(asked: &str, grant_path: Option<&str>, recursive: bool) -> Result<Option<String>, String> {
    let Some(gp) = grant_path.map(str::trim).filter(|g| !g.is_empty()) else {
        return Ok(None);
    };
    let gp = gp.trim_end_matches('/');
    if gp == asked.trim_end_matches('/') {
        return Ok(None);
    }
    let is_ancestor = gp.starts_with('/') && !gp.is_empty() && asked.starts_with(&format!("{gp}/"));
    if !is_ancestor {
        return Err(format!(
            "the grant must reach from the asked path ({asked}) or a directory above it, never the root; got {gp}"
        ));
    }
    if !recursive {
        return Err("a grant on a directory above the asked path must include everything below it — \
                    an exact grant there would not reach what was asked"
            .to_string());
    }
    Ok(Some(gp.to_string()))
}

fn check_ruling(
    granted: bool,
    reason: Option<&str>,
    standing: bool,
    recursive: bool,
) -> Result<Ruling, String> {
    check_ruling_full(granted, reason, standing, recursive, false, None, "")
}

fn check_ruling_full(
    granted: bool,
    reason: Option<&str>,
    standing: bool,
    recursive: bool,
    once: bool,
    grant_path: Option<&str>,
    asked: &str,
) -> Result<Ruling, String> {
    if once && (!granted || standing || recursive || grant_path.is_some_and(|g| !g.trim().is_empty())) {
        return Err(
            "\"this act once\" approves the refused act exactly once — it is a grant, never standing, \
             never recursive, and has no breadth"
                .to_string(),
        );
    }
    let grant_path = if granted && !once {
        check_breadth(asked, grant_path, recursive)?
    } else {
        None
    };
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
        once,
        grant_path,
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
    once: Option<bool>,
    grant_path: Option<String>,
    asked_path: Option<String>,
) -> Result<serde_json::Value, String> {
    let request_id = request_id.trim().to_string();
    if request_id.is_empty() {
        return Err("no scope request id".to_string());
    }
    // All default to false/absent, as the daemon's do: exact, not standing, not once.
    let r = check_ruling_full(
        granted,
        reason.as_deref(),
        standing.unwrap_or(false),
        recursive.unwrap_or(false),
        once.unwrap_or(false),
        grant_path.as_deref(),
        asked_path.as_deref().unwrap_or(""),
    )?;

    let mut body = serde_json::json!({
        "request_id": request_id,
        "granted": granted,
        "standing": r.standing,
        "recursive": r.recursive,
    });
    if r.once {
        body["once"] = serde_json::Value::Bool(true);
    }
    if let Some(gp) = r.grant_path {
        body["grant_path"] = serde_json::Value::String(gp);
    }
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
        assert!(!r.once && r.grant_path.is_none());
    }

    /// "This act once" (2026-10-05) is a grant with no duration choice and no breadth.
    #[test]
    fn once_is_a_bare_grant() {
        let asked = "/etc/hostname";
        assert!(check_ruling_full(true, Some("one read"), false, false, true, None, asked).unwrap().once);
        for (granted, standing, recursive, gp) in [
            (false, false, false, None),
            (true, true, false, None),
            (true, false, true, None),
            (true, false, false, Some("/etc")),
        ] {
            let e = check_ruling_full(granted, Some("r"), standing, recursive, true, gp, asked);
            assert!(e.is_err(), "{granted} {standing} {recursive} {gp:?}");
        }
    }

    /// Breadth: the asked path, or a directory above it — recursive, never the root, never a
    /// sibling that merely shares a prefix.
    #[test]
    fn breadth_is_the_asked_path_or_a_recursive_ancestor() {
        let asked = "/home/u/.local/state/mesh/x.log";
        let ok = |gp, rec| check_ruling_full(true, Some("r"), true, rec, false, Some(gp), asked);
        assert_eq!(ok("/home/u/.local/state/mesh", true).unwrap().grant_path.as_deref(),
                   Some("/home/u/.local/state/mesh"));
        assert_eq!(ok(asked, false).unwrap().grant_path, None, "the asked path itself needs no field");
        assert!(ok("/home/u/.local/state/mesh", false).is_err(), "an ancestor must be recursive");
        assert!(ok("/", true).is_err(), "never the root");
        assert!(ok("/home/u/.local/state/me", true).is_err(), "a prefix is not an ancestor");
        assert!(ok("/srv", true).is_err(), "nor an unrelated directory");
        // A refusal ignores breadth entirely.
        assert_eq!(check_ruling_full(false, None, false, false, false, Some("/srv"), asked)
                       .unwrap().grant_path, None);
    }
}

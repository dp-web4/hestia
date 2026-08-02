//! `hestia gate` — the client for the remedy every gate deny already names.
//!
//! Stage 2 (#114) armed the governance-surface gate and printed this on every refusal:
//!
//! ```text
//! To allow:  hestia gate approve <id> --reason '...'   (or: hestia gate deny <id>)
//! ```
//!
//! That subcommand had never been written. `git log -S"enum GateCmd"` across the whole
//! history returns nothing, while the text naming it shipped in `5e15636` — so from the
//! moment enforcement began, the prescribed remedy pointed at a command that did not exist.
//!
//! The channel itself works: a session holding the `hestia_*` MCP tools can already rule,
//! and on 2026-07-31 one did — `claude-code` denied `codex`'s escalation `899e0686bd8a1f38`
//! with a reasoned refusal, NOT-SAME satisfied, cross-vendor independence recorded. The gap
//! is REACHABILITY for callers without those tools (#121), which is every mesh-woken and
//! headless session. Measured over one 53-minute chain window: 12 escalations opened, 1
//! ruled. Under-used, not inert — and this is the client the deny text has always promised.
//!
//! WHAT THIS IS NOT. This adds no authority. Every decision is made by the daemon:
//! `tool_gate_arbitrate_escalation` requires an attributed live session, enforces
//! NOT-SAME server-side through `arbiter::eligibility` (not a second copy that could
//! drift), and demands a stated reason to approve while a deny needs none. This module
//! can only reach verdicts the daemon would already permit from any other client. It is
//! a reachability fix, not a trust change — which is exactly why it does not need the
//! human approval that fixing the gate's own code does.
//!
//! WHAT IT DOES NOT FIX. The identity it presents is asserted, not proven: `hestia_connect`
//! authenticates nobody, so `--as` is a claim (#63, #128). The CLI therefore prints the
//! identity it asserted alongside every answer, so a reader can never mistake the name in
//! the record for a verified one. It deliberately does NOT default to a member's name.

use anyhow::{anyhow, bail, Context, Result};
use serde_json::{json, Value};
use std::time::Duration;

/// The identity asserted when the operator does not name one. Deliberately not a member
/// name: an unnamed caller should be visibly a CLI, not silently a peer. Note that an
/// unrecognised asserted name grades cross-vendor at the arbiter (`arbiter.rs` clause 4),
/// so this is a weaker claim than it looks — see #128.
const DEFAULT_ASSERTED_ID: &str = "hestia-cli";

struct Mcp {
    client: reqwest::blocking::Client,
    url: String,
    mcp_session: Option<String>,
    next_id: u64,
}

impl Mcp {
    fn connect(endpoint: &str) -> Result<Self> {
        let url = if endpoint.ends_with("/mcp") {
            endpoint.to_string()
        } else {
            format!("{}/mcp", endpoint.trim_end_matches('/'))
        };
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(15))
            .build()?;
        let mut m = Mcp { client, url, mcp_session: None, next_id: 0 };
        m.rpc(
            "initialize",
            Some(json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hestia-gate-cli", "version": env!("CARGO_PKG_VERSION")},
            })),
        )
        .with_context(|| {
            format!(
                "no hestia daemon at {} — start one with `hestia serve`",
                m.url
            )
        })?;
        Ok(m)
    }

    fn rpc(&mut self, method: &str, params: Option<Value>) -> Result<Value> {
        self.next_id += 1;
        let mut body = json!({"jsonrpc": "2.0", "id": self.next_id, "method": method});
        if let Some(p) = params {
            body["params"] = p;
        }
        let mut req = self
            .client
            .post(&self.url)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream");
        if let Some(s) = &self.mcp_session {
            req = req.header("Mcp-Session-Id", s.clone());
        }
        let res = req.body(body.to_string()).send()?;
        if self.mcp_session.is_none() {
            if let Some(h) = res.headers().get("mcp-session-id") {
                self.mcp_session = h.to_str().ok().map(str::to_string);
            }
        }
        let text = res.text()?;
        let v = parse_sse_frame(&text)?;
        if let Some(e) = v.get("error") {
            bail!("daemon refused {method}: {e}");
        }
        Ok(v)
    }

    /// Call a tool and return its decoded payload.
    ///
    /// A tool FAILURE arrives as HTTP 200 with a `result` whose text is an `_hestia_error`
    /// envelope — a refusal shaped like a success. #135 is the same class one layer up (a
    /// refused notice exiting 0, so a rejected send read as a sent one). Anything that is
    /// not an answer becomes an `Err` here, so it can never reach the operator as a verdict.
    fn tool(&mut self, name: &str, args: Value) -> Result<Value> {
        let v = self.rpc("tools/call", Some(json!({"name": name, "arguments": args})))?;
        tool_payload(name, &v)
    }
}

/// Take the first NON-EMPTY `data:` frame off the daemon's SSE response.
///
/// The stream opens with an empty `data:` line. A reader that takes the first `data:`
/// blindly gets an empty string, and the resulting parse error reads like "the daemon is
/// down" — which is the most expensive possible misreport for a tool whose whole job is to
/// tell you whether a refusal has an answer yet.
fn parse_sse_frame(text: &str) -> Result<Value> {
    let payload = text
        .lines()
        .filter_map(|l| l.strip_prefix("data: "))
        .map(str::trim)
        .find(|p| !p.is_empty())
        .unwrap_or_else(|| text.trim());
    serde_json::from_str(payload)
        .with_context(|| format!("undecodable daemon response: {}", truncate(payload, 200)))
}

/// Decode a tool result, turning a refusal into an `Err`.
///
/// A tool FAILURE arrives as HTTP 200 with a `result` whose text is an `_hestia_error`
/// envelope — a refusal shaped like a success. #135 is the same class one layer up (a
/// refused notice exiting 0, so a rejected send read as a sent one). Anything that is not
/// an answer becomes an `Err` here, so it can never reach the operator as a verdict.
fn tool_payload(name: &str, v: &Value) -> Result<Value> {
    let text = v
        .pointer("/result/content/0/text")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("tool {name}: no content in daemon response"))?;
    let parsed: Value =
        serde_json::from_str(text).with_context(|| format!("tool {name}: undecodable payload"))?;
    if let Some(e) = parsed.get("_hestia_error") {
        let msg = e.get("message").and_then(Value::as_str).unwrap_or("(no message)");
        bail!("{name} refused: {msg}");
    }
    Ok(parsed)
}

/// Pull the session id out of a `hestia_connect` answer.
///
/// Connect returns `sessionId`; every gate tool consumes `session_id`. A client that reads
/// back the key it was handed gets nothing and then operates UNATTRIBUTED without erroring
/// — which is how the `unattributed` row in #128 came to exist. Accept both spellings, and
/// fail loudly rather than degrade to an anonymous caller.
fn session_from_connect(v: &Value) -> Result<&str> {
    v.get("sessionId")
        .or_else(|| v.get("session_id"))
        .and_then(Value::as_str)
        .ok_or_else(|| {
            anyhow!(
                "connect returned no session id; refusing to continue unattributed — \
                 an unattributed caller cannot rule and would be recorded as one that could"
            )
        })
}

/// Enforced daemon-side too; checked client-side so the operator learns it before a round
/// trip and before an escalation is touched at all.
fn check_reason(approve: bool, reason: &str) -> Result<()> {
    if approve && reason.trim().is_empty() {
        bail!(
            "approving a governance write requires --reason (a deny does not). \
             Approving is what a reader will have to weigh later."
        );
    }
    Ok(())
}

fn truncate(s: &str, n: usize) -> String {
    if s.len() <= n { s.to_string() } else { format!("{}…", &s[..n]) }
}

/// Open an attributed session. Returns (session_id, asserted_plugin_id).
fn open_session(m: &mut Mcp, asserted_id: &str, role: &str) -> Result<(String, String)> {
    let r = m.tool(
        "hestia_connect",
        json!({"plugin_id": asserted_id, "role": role, "host_agent": asserted_id}),
    )?;
    let sid = session_from_connect(&r)?.to_string();
    Ok((sid, asserted_id.to_string()))
}

fn banner(asserted: &str) {
    eprintln!(
        "identity ASSERTED as '{asserted}' (hestia_connect authenticates nobody — see #63/#128); \
         the daemon decides, this CLI only asks."
    );
}

pub fn pending(endpoint: &str, asserted_id: Option<String>, role: &str) -> Result<()> {
    let asserted = asserted_id.unwrap_or_else(|| DEFAULT_ASSERTED_ID.to_string());
    let mut m = Mcp::connect(endpoint)?;
    let (sid, who) = open_session(&mut m, &asserted, role)?;
    banner(&who);
    let r = m.tool("hestia_gate_pending_escalations", json!({"session_id": sid}))?;

    let count = r.get("count").and_then(Value::as_u64).unwrap_or(0);
    if count == 0 {
        println!("no pending escalations");
    } else {
        println!(
            "{:<18} {:<16} {:<7} {:<9} {:>8}  {}",
            "ESCALATION", "ASKED_BY", "TOOL", "MAY_RULE", "SECS", "MARKER"
        );
        if let Some(list) = r.get("pending").and_then(Value::as_array) {
            for e in list {
                let s = |k: &str| e.get(k).and_then(Value::as_str).unwrap_or("-").to_string();
                let may = match e.get("you_may_rule") {
                    Some(Value::Bool(b)) => b.to_string(),
                    _ => "null".to_string(),
                };
                println!(
                    "{:<18} {:<16} {:<7} {:<9} {:>8}  {}",
                    s("escalation_id"),
                    s("asked_by"),
                    s("tool_name"),
                    may,
                    e.get("secs_remaining").and_then(Value::as_u64).unwrap_or(0),
                    s("marker"),
                );
                // THE BASIS, on its own lines. A one-row table cannot carry a rationale, and
                // an operator ruling from id + asker + path fragment is choosing without
                // grounds (dp, 2026-08-02). Absence is printed explicitly rather than left
                // blank: "the member gave no reason" is information the decider should have,
                // and a blank cell reads as a rendering gap instead of a missing claim.
                match e.get("stated_reason").and_then(Value::as_str) {
                    Some(v) if !v.trim().is_empty() => println!("    why:  {v}"),
                    _ => println!("    why:  (none stated — decide on the payload alone)"),
                }
                if let Some(v) = e.get("stated_detail").and_then(Value::as_str) {
                    if !v.trim().is_empty() {
                        println!("    what: {v}");
                    }
                }
                println!();
            }
        }
    }
    // The daemon ships a caveat with this answer explaining that `you_may_rule` reflects
    // NOT-SAME only. Swallowing it would let a reader mistake NOT-SAME for a boundary.
    if let Some(c) = r.get("caveat").and_then(Value::as_str) {
        println!("\ncaveat: {c}");
    }
    Ok(())
}

pub fn poll(endpoint: &str, id: &str, asserted_id: Option<String>, role: &str) -> Result<()> {
    let asserted = asserted_id.unwrap_or_else(|| DEFAULT_ASSERTED_ID.to_string());
    let mut m = Mcp::connect(endpoint)?;
    let (sid, who) = open_session(&mut m, &asserted, role)?;
    banner(&who);
    let r = m.tool(
        "hestia_gate_escalation_poll",
        json!({"escalation_id": id, "session_id": sid}),
    )?;
    println!("{}", serde_json::to_string_pretty(&r)?);
    // An unknown id and an expired id are the SAME answer by design (#129); the status
    // word alone cannot tell them apart, so do not let the exit code imply it can.
    let permits = r.get("permits_write").and_then(Value::as_bool).unwrap_or(false);
    if !permits {
        eprintln!("\nthis escalation does NOT permit the write");
    }
    Ok(())
}

/// Rule on an escalation. `approve` must be an explicit verdict — there is no default.
pub fn arbitrate(
    endpoint: &str,
    id: &str,
    approve: bool,
    reason: Option<String>,
    asserted_id: Option<String>,
    role: &str,
) -> Result<()> {
    let reason = reason.unwrap_or_default();
    check_reason(approve, &reason)?;
    let asserted = asserted_id.unwrap_or_else(|| DEFAULT_ASSERTED_ID.to_string());
    let mut m = Mcp::connect(endpoint)?;
    let (sid, who) = open_session(&mut m, &asserted, role)?;
    banner(&who);
    let r = m.tool(
        "hestia_gate_arbitrate_escalation",
        json!({
            "escalation_id": id,
            "approve": approve,
            "reason": reason,
            "session_id": sid,
        }),
    )?;
    println!("{}", serde_json::to_string_pretty(&r)?);
    Ok(())
}

/// Add evidence WITHOUT deciding. #122 made approval accumulate as factors rather than
/// first-answer-wins; without this subcommand a member holding partial evidence has only
/// two moves — rule it, or nothing — which pressures toward ruling on evidence the bar
/// does not support. That is the exact failure the factor set exists to prevent.
pub fn corroborate(
    endpoint: &str,
    id: &str,
    asserted_id: Option<String>,
    role: &str,
) -> Result<()> {
    let asserted = asserted_id.unwrap_or_else(|| DEFAULT_ASSERTED_ID.to_string());
    let mut m = Mcp::connect(endpoint)?;
    let (sid, who) = open_session(&mut m, &asserted, role)?;
    banner(&who);
    let r = m.tool(
        "hestia_gate_escalation_corroborate",
        json!({"escalation_id": id, "session_id": sid}),
    )?;
    println!("{}", serde_json::to_string_pretty(&r)?);
    eprintln!("corroboration is NOT a verdict — it permits nothing by itself");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The daemon's stream opens with an EMPTY `data:` frame. A reader that takes the
    /// first `data:` blindly decodes "" and reports the daemon as unreachable. This input
    /// is the real shape observed on 127.0.0.1:7711, empty first frame included.
    #[test]
    fn sse_skips_the_empty_opening_frame() {
        let raw = "data: \nid: 0\nretry: 3000\n\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"ok\":true}}\n";
        let v = parse_sse_frame(raw).expect("must decode past the empty frame");
        assert_eq!(v.pointer("/result/ok"), Some(&json!(true)));
    }

    #[test]
    fn sse_falls_back_to_a_plain_json_body() {
        let v = parse_sse_frame("{\"result\":{\"ok\":1}}").unwrap();
        assert_eq!(v.pointer("/result/ok"), Some(&json!(1)));
    }

    /// A tool refusal is HTTP 200 with `_hestia_error` INSIDE the result. If this decoded
    /// as success the caller would print a refusal as an answer — the #135 class.
    #[test]
    fn a_refusal_shaped_like_a_success_is_an_error() {
        let envelope = json!({"_hestia_error": {
            "code": "hestia.internal_error",
            "message": "no such escalation — unknown ids are denies, not retries"
        }});
        let resp = json!({"result": {"content": [{"text": envelope.to_string()}]}});
        let err = tool_payload("hestia_gate_arbitrate_escalation", &resp)
            .expect_err("an _hestia_error envelope must not decode as an answer");
        assert!(err.to_string().contains("no such escalation"), "{err}");
    }

    #[test]
    fn a_real_answer_decodes() {
        let resp = json!({"result": {"content": [{"text": json!({"count": 0}).to_string()}]}});
        let v = tool_payload("hestia_gate_pending_escalations", &resp).unwrap();
        assert_eq!(v.get("count"), Some(&json!(0)));
    }

    /// Connect answers `sessionId`; the gate tools want `session_id`. Reading back the key
    /// you were handed yields None and a silently UNATTRIBUTED caller — the state that
    /// produced #128's `unattributed` row. Both spellings must resolve.
    #[test]
    fn session_id_is_read_from_the_spelling_connect_actually_returns() {
        let connect = json!({
            "assignedRole": "citizen",
            "constellationRole": "role:constellation:member",
            "roleDeclarationHonored": true,
            "sessionId": "fabcdc75-b309-4d2b-9b9c-d468f0c6d862",
            "softLct": "lct:web4:session:348f5a07bfd68871"
        });
        assert_eq!(
            session_from_connect(&connect).unwrap(),
            "fabcdc75-b309-4d2b-9b9c-d468f0c6d862"
        );
        let snake = json!({"session_id": "abc"});
        assert_eq!(session_from_connect(&snake).unwrap(), "abc");
    }

    /// Degrading to an anonymous caller must be an error, never a default.
    #[test]
    fn a_missing_session_refuses_rather_than_going_unattributed() {
        let err = session_from_connect(&json!({"assignedRole": "citizen"}))
            .expect_err("no session id must not silently become an unattributed caller");
        assert!(err.to_string().contains("unattributed"), "{err}");
    }

    /// Approving needs a stated reason; refusing does not. Same asymmetry the daemon
    /// enforces — a deny is the default and costs nothing to explain.
    #[test]
    fn approve_requires_a_reason_and_deny_does_not() {
        assert!(check_reason(true, "").is_err());
        assert!(check_reason(true, "   ").is_err());
        assert!(check_reason(true, "the classifier refused a read").is_ok());
        assert!(check_reason(false, "").is_ok());
    }
}

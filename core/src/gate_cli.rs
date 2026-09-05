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
use std::time::{Duration, Instant};

/// The identity asserted when the operator does not name one. Deliberately not a member
/// name: an unnamed caller should be visibly a CLI, not silently a peer. Note that an
/// unrecognised asserted name grades cross-vendor at the arbiter (`arbiter.rs` clause 4),
/// so this is a weaker claim than it looks — see #128.
const DEFAULT_ASSERTED_ID: &str = "hestia-cli";

pub struct Mcp {
    client: reqwest::blocking::Client,
    url: String,
    mcp_session: Option<String>,
    next_id: u64,
}

impl Mcp {
    pub fn connect(endpoint: &str) -> Result<Self> {
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
    pub fn tool(&mut self, name: &str, args: Value) -> Result<Value> {
        let v = self.rpc("tools/call", Some(json!({"name": name, "arguments": args})))?;
        tool_payload(name, &v)
    }

    /// Like `tool`, but a refusal envelope comes back as a VALUE, not an `Err`. For the one
    /// caller that needs to read a refusal's payload — `scope arbitrate`'s unsigned preflight,
    /// whose `_hestia_error.data.signs` carries the bytes to sign (#962). Every other caller
    /// keeps `tool`, so a refusal can never reach an operator as a verdict by accident.
    pub fn tool_envelope(&mut self, name: &str, args: Value) -> Result<Value> {
        let v = self.rpc("tools/call", Some(json!({"name": name, "arguments": args})))?;
        let text = v
            .pointer("/result/content/0/text")
            .and_then(Value::as_str)
            .ok_or_else(|| anyhow!("tool {name}: no content in daemon response"))?;
        serde_json::from_str(text).with_context(|| format!("tool {name}: undecodable payload"))
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
pub fn open_session(m: &mut Mcp, asserted_id: &str, role: &str) -> Result<(String, String)> {
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

/// Serialize the pending response without changing its daemon-owned schema.
///
/// The wake primer routes this value to `open-petitions.py fold`. That consumer
/// distinguishes an attempted empty read from a non-response by checking that
/// `pending` is an array, so a CLI-specific wrapper or table parser would erase
/// the distinction the fold exists to preserve (#675).
fn pending_json(r: &Value) -> Result<String> {
    serde_json::to_string(r).context("encoding pending escalations as JSON")
}

pub fn pending(
    endpoint: &str,
    asserted_id: Option<String>,
    role: &str,
    json_output: bool,
) -> Result<()> {
    let asserted = asserted_id.unwrap_or_else(|| DEFAULT_ASSERTED_ID.to_string());
    let mut m = Mcp::connect(endpoint)?;
    let (sid, who) = open_session(&mut m, &asserted, role)?;
    banner(&who);
    let r = m.tool("hestia_gate_pending_escalations", json!({"session_id": sid}))?;

    if json_output {
        // `banner` is stderr. Keep stdout to one JSON value so the primer's
        // `hestia gate pending --json | open-petitions.py fold …` works as written.
        println!("{}", pending_json(&r)?);
        return Ok(());
    }

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

/// How long to sleep between polls while `--wait` is counting down.
///
/// The claim window is 600s and a grant is single-use, so the cost of noticing a decision
/// late is real: every second between the ruling and the re-issue is spent out of the
/// window the asker has to use it. Two seconds against a loopback daemon is ~1800 requests
/// across the longest permitted wait, which is nothing, and it bounds the notice lag at
/// 0.3% of the window.
const WAIT_POLL_INTERVAL: Duration = Duration::from_secs(2);

/// The longest `--wait` this client accepts.
///
/// Not a clamp — an over-long value is REFUSED, loudly. A silent clamp would hand the
/// caller a wait that ended for a reason they were never told, which is the same shape as
/// every other defect this surface has had: a well-formed wrong answer instead of an error.
/// The number is the default escalation TTL: a pending record cannot outlive it, so no
/// wait beyond it can learn anything a wait of exactly it could not.
const WAIT_MAX_SECS: u64 = 3600;

/// Has this escalation left the PENDING state? — the whole predicate `--wait` waits on.
///
/// Split out and pure for the same reason `hollow_approval_warning` is: the daemon is not
/// available to a unit test, and a wait condition that nothing exercises is a claim, not a
/// guarantee. Every trap here is a way of continuing to wait forever on a record that will
/// never move.
///
/// ONLY the literal `pending` continues the wait. Approved, denied and expired are all
/// terminal, and so is an unknown id — which the daemon deliberately answers as `expired`,
/// because "an id this daemon has never seen" and "an id whose window closed" are the same
/// answer on purpose (#129). Waiting on a typo would otherwise burn the caller's entire
/// budget and then report the same thing the first poll already knew.
///
/// A MISSING OR NON-STRING `status` ALSO ENDS THE WAIT. This is the same fail-closed rule
/// `hollow_approval_warning` applies to an absent `permits_write`: a daemon too old to send
/// the field, or a reply this client cannot parse, must not be able to buy an unbounded
/// wait by staying silent. The caller gets the payload and can read it; what they do not
/// get is a spinner against a daemon that was never going to answer the question.
fn wait_is_over(r: &Value) -> bool {
    !matches!(r.get("status").and_then(Value::as_str), Some("pending"))
}

/// Show one escalation's state, optionally BLOCKING until it is ruled on.
///
/// WHY THE WAIT EXISTS, measured on CBP 2026-08-27. Escalation `cdeeb14b74cd4ed0` was
/// opened at 08:12:15, approved by the operator at 08:16:30, and claimed at 08:21:16 —
/// 286 seconds after the grant, and 11 seconds after a human typed the word "approved"
/// into the asker's session. The decision had been on the chain and in a queued disposition
/// notice that whole time. Nothing was broken: the record was correct, the poll would have
/// answered correctly, and the asker simply had no way to be waiting on it, because every
/// route from "ruled" back to "the asker knows" was either a mesh notice that only lands at
/// the next wake, or a busy-wait nobody writes by hand. So the cheapest way to learn the
/// answer was to ask a person, and 286 of the 600 available seconds went to that.
///
/// That is a governance failure and not a latency one. A remedy whose fast path runs
/// through a human is a remedy that will be skipped, and the alternative to a skipped
/// remedy is not compliance — it is a rephrase. This makes waiting on the RECORD the
/// cheapest thing the asker can do.
///
/// The session is opened ONCE and reused for the whole wait; a tool error mid-wait
/// propagates rather than being retried, so a caller never mistakes a broken connection for
/// a still-pending petition.
pub fn poll(
    endpoint: &str,
    id: &str,
    asserted_id: Option<String>,
    role: &str,
    wait_secs: Option<u64>,
) -> Result<()> {
    if let Some(w) = wait_secs {
        if w > WAIT_MAX_SECS {
            bail!(
                "--wait {w} exceeds the {WAIT_MAX_SECS}s maximum: a pending escalation \
                 cannot outlive its TTL, so a longer wait cannot learn anything this one \
                 cannot. Re-run with a smaller value."
            );
        }
    }
    let asserted = asserted_id.unwrap_or_else(|| DEFAULT_ASSERTED_ID.to_string());
    let mut m = Mcp::connect(endpoint)?;
    let (sid, who) = open_session(&mut m, &asserted, role)?;
    banner(&who);

    let budget = wait_secs.unwrap_or(0);
    let started = Instant::now();
    let mut timed_out = false;
    let r = loop {
        let r = m.tool(
            "hestia_gate_escalation_poll",
            json!({"escalation_id": id, "session_id": sid}),
        )?;
        if wait_is_over(&r) {
            break r;
        }
        let spent = started.elapsed().as_secs();
        if spent >= budget {
            timed_out = wait_secs.is_some();
            break r;
        }
        // Never sleep past the budget: the last nap of a wait is the remainder, so the
        // reported elapsed time is the one the caller asked for.
        let left = Duration::from_secs(budget - spent);
        std::thread::sleep(WAIT_POLL_INTERVAL.min(left));
    };

    println!("{}", serde_json::to_string_pretty(&r)?);
    if timed_out {
        eprintln!(
            "\nwaited {budget}s and this escalation is STILL PENDING: nobody has ruled. \
             That is not a deny — the record is live and the write stays refused until \
             someone decides. Poll again, or wait again."
        );
    }
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
    // `poll` has always ended with this line; the decide path never did, which is backwards.
    // Polling is a question, and the asker reads the answer; approving FEELS like a grant, so
    // silence there reads as success. Say it on the surface where the mistake is expensive.
    if let Some(w) = hollow_approval_warning(approve, &r) {
        eprintln!("\n{w}");
    }
    Ok(())
}

/// The warning text for an approval that permits nothing, or `None` if there is nothing to
/// warn about. Split out from `arbitrate` so it can be tested without a daemon — the whole
/// point is that this fires, and a warning nothing exercises is just a claim.
///
/// Absent `permits_write` is treated as NOT permitting: an older daemon that does not send
/// the field must not be able to make a hollow approval look sound by staying quiet.
fn hollow_approval_warning(approve: bool, r: &Value) -> Option<String> {
    if !approve {
        return None; // a deny permits nothing by design; that is not news.
    }
    if r.get("permits_write").and_then(Value::as_bool).unwrap_or(false) {
        return None;
    }
    let bar = r.get("bar").and_then(Value::as_str).unwrap_or("the stated bar");
    Some(format!(
        "WARNING: this approval does NOT permit the write — {bar} is UNMET.\n\
         It is recorded, but re-issuing the write will still be refused, and decisions\n\
         are single-shot: this escalation cannot accumulate the missing factor now."
    ))
}

/// Add evidence WITHOUT deciding. #122 made approval accumulate as factors rather than
/// first-answer-wins; without this subcommand a member holding partial evidence has only
/// two moves — rule it, or nothing — which pressures toward ruling on evidence the bar
/// does not support. That is the exact failure the factor set exists to prevent.
pub fn corroborate(
    endpoint: &str,
    id: &str,
    stance: &str,
    argument: Option<String>,
    asserted_id: Option<String>,
    role: &str,
) -> Result<()> {
    let asserted = asserted_id.unwrap_or_else(|| DEFAULT_ASSERTED_ID.to_string());
    let mut m = Mcp::connect(endpoint)?;
    let (sid, who) = open_session(&mut m, &asserted, role)?;
    banner(&who);
    // The stance travels verbatim; the daemon owns the vocabulary and refuses what it
    // cannot honour (#367: an unstated stance used to default to concurrence, and a
    // dissent argument was silently discarded — refuse-don't-default is the remedy).
    let mut payload = json!({"escalation_id": id, "session_id": sid, "stance": stance});
    if let Some(a) = argument {
        payload["argument"] = json!(a);
    }
    let r = m.tool("hestia_gate_escalation_corroborate", payload)?;
    println!("{}", serde_json::to_string_pretty(&r)?);
    eprintln!("your stance is evidence, NOT a verdict — it permits nothing and vetoes nothing");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `--wait` MUST NOT SPIN ON A RECORD THAT WILL NEVER MOVE, and must not stop early
    /// on the one state it exists to wait through.
    ///
    /// Both directions are failures and they are not symmetric. Stopping early on
    /// `pending` gives the caller back the same answer they already had and sends them to
    /// a human — the exact 286-second detour this flag was written to remove. Failing to
    /// stop hangs a headless session against a typo'd id until its own wake times out,
    /// with no output at all.
    ///
    /// The unknown-id arm is the real payload measured on CBP 2026-08-27 against
    /// `deadbeefdeadbeef`, verbatim: the daemon answers `expired`, on purpose, because
    /// "never seen" and "window closed" are the same answer (#129). A wait keyed on
    /// "approved or denied" rather than "not pending" would sit on that for the full
    /// budget and then report what the first poll already knew.
    ///
    /// Sabotage arm: change `wait_is_over` to `matches!(.., Some("approved") | Some("denied"))`
    /// and the expired, unknown-id, absent and non-string arms all go red while the
    /// pending and approved arms stay green — which is exactly the shape of wait bug that
    /// would otherwise ship.
    #[test]
    fn only_a_pending_status_keeps_the_wait_going() {
        assert!(
            !wait_is_over(&json!({"status": "pending", "permits_write": false})),
            "a live petition is the ONE state worth waiting through"
        );

        for terminal in ["approved", "denied", "expired"] {
            assert!(
                wait_is_over(&json!({"status": terminal})),
                "{terminal} is a ruling or a death; there is nothing further to wait for"
            );
        }

        // The unknown-id reply, measured live rather than imagined.
        assert!(
            wait_is_over(&json!({
                "escalation_id": "deadbeefdeadbeef",
                "status": "expired",
                "permits_write": false,
                "granted": false,
                "claim_window_secs_remaining": 0,
                "secs_remaining": 0,
                "note": "unknown escalation_id — treated as expired (a restart drops the \
                         store, and an in-flight escalation must then read as denied)"
            })),
            "an id this daemon never saw must not buy an unbounded wait"
        );
    }

    /// A REPLY THIS CLIENT CANNOT READ ENDS THE WAIT — the same fail-closed rule
    /// `a_missing_permits_write_field_is_not_taken_as_permission` applies one field over.
    ///
    /// An older daemon that does not send `status`, or any reply whose `status` is not a
    /// string, must not be able to purchase a silent hour of spinning by omission. The
    /// caller still gets the payload printed and can read it; what they must not get is a
    /// client that treats "I could not parse this" as "not decided yet".
    #[test]
    fn an_unreadable_status_does_not_buy_an_unbounded_wait() {
        assert!(wait_is_over(&json!({})), "absent status must end the wait");
        assert!(
            wait_is_over(&json!({"status": null})),
            "a null status is not a pending petition"
        );
        assert!(
            wait_is_over(&json!({"status": 0})),
            "a non-string status must not read as pending"
        );
    }

    /// The daemon's stream opens with an EMPTY `data:` frame. A reader that takes the
    /// first `data:` blindly decodes "" and reports the daemon as unreachable. This input
    /// is the real shape observed on 127.0.0.1:7711, empty first frame included.
    #[test]
    fn sse_skips_the_empty_opening_frame() {
        let raw = "data: \nid: 0\nretry: 3000\n\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"ok\":true}}\n";
        let v = parse_sse_frame(raw).expect("must decode past the empty frame");
        assert_eq!(v.pointer("/result/ok"), Some(&json!(true)));
    }

    /// The shape the daemon actually returned for daea09fc2106dd7b on 2026-08-06: a
    /// `sovereign_plus_peer` bar decided by the operator alone, 15s into the window. This is
    /// the majority case, not a corner — 63 approvals on the chain look exactly like this,
    /// and every one of them was reported to the approver as a bare `approved`.
    #[test]
    fn an_approval_short_of_the_bar_warns_that_it_permits_nothing() {
        let r = json!({
            "escalation_id": "daea09fc2106dd7b",
            "status": "approved",
            "decided_by": "operator",
            "bar": "sovereign_plus_peer",
            "bar_met": false,
            "permits_write": false,
        });
        let w = hollow_approval_warning(true, &r).expect("an unmet bar must warn");
        assert!(w.contains("does NOT permit the write"), "{w}");
        assert!(w.contains("sovereign_plus_peer"), "name the bar that went unmet: {w}");
    }

    /// The negative half: a sound approval must stay quiet, or the warning is noise that
    /// gets tuned out before it ever matters.
    #[test]
    fn an_approval_that_meets_the_bar_is_silent() {
        let r = json!({"status": "approved", "bar": "single_approver",
                       "bar_met": true, "permits_write": true});
        assert!(hollow_approval_warning(true, &r).is_none());
    }

    /// A daemon too old to send `permits_write` must not buy silence by omission — the
    /// #135 class again, an absent field reading as a favourable answer.
    #[test]
    fn a_missing_permits_write_field_is_not_taken_as_permission() {
        let r = json!({"status": "approved", "decided_by": "operator"});
        assert!(hollow_approval_warning(true, &r).is_some(),
                "absent permits_write must warn, not reassure");
    }

    /// A deny already permits nothing; saying so would train the reader to ignore the line.
    #[test]
    fn a_deny_does_not_warn() {
        let r = json!({"status": "denied", "permits_write": false});
        assert!(hollow_approval_warning(false, &r).is_none());
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

    /// `--json` is a pipe contract, not a second rendering. The fold's `asked`
    /// flag depends on seeing the daemon's `pending` array, including when it is
    /// empty, so every field must survive untouched.
    #[test]
    fn pending_json_preserves_the_daemon_response_shape() {
        let daemon = json!({
            "pending": [{
                "escalation_id": "abc123",
                "asked_by": "member-a",
                "you_may_rule": false,
                "factors": [{"member": "member-b", "stance": "dissent"}],
            }],
            "count": 1,
            "you": {"plugin_id": "member-c", "role": "role:constellation:member"},
            "caveat": "a stated caveat",
        });
        let rendered = pending_json(&daemon).expect("pending response serializes");
        let reparsed: Value = serde_json::from_str(&rendered).expect("JSON output reparses");
        assert_eq!(reparsed, daemon, "the CLI must not reinterpret the daemon response");
        assert!(reparsed["pending"].is_array(), "the fold requires a pending array");
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

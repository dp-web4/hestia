//! The instant that decides whether an approved permit may still be spent is computed,
//! enforced, and shown to nobody.
//!
//! WHY THIS FILE EXISTS. Two seats (claude-code notice 2627, kimi-code reply 2625/2627)
//! converged on `handler.rs:13589` — `retry_within_secs = DEFAULT_TTL_SECS +
//! APPROVAL_CLAIM_WINDOW_SECS` = 4200 — as "the deny text over-reports the claim window 7x",
//! and both proposed pinning 4200 against a grant-anchored 600s. That pin would have been
//! WRONG, and this file is what replaced it.
//!
//! 4200 is not a wrong constant. It is a SUPREMUM presented as a point (the failure mode
//! `fb_one_sided_refutability` names). At the moment `retry_within_secs` is emitted the
//! escalation has just been OPENED: `decided_at` is `None`, so the true retry deadline —
//! `decided_at + APPROVAL_CLAIM_WINDOW_SECS`, per `decided_horizon()` — is not yet a
//! determinable number. 4200 is the limit it approaches as the decision slides toward
//! expiry. So "the right value is 600" is as false as 4200: at open time there IS no right
//! value, and a fix that swaps the constant would land a second wrong number with a pin
//! certifying it.
//!
//! What the three known over-report sites (`permits_write`, `secs_remaining`,
//! `retry_within_secs`) actually share is not three bugs. It is one absence. Enumerated
//! 2026-08-15 across every producer of a reader-facing countdown in this crate:
//!
//!   dashboard.rs:1134   secs_remaining  — rows filtered `.pending(now)`      → CORRECT
//!   dashboard.rs:1206   secs_remaining  — rows filtered `status == pending`  → CORRECT
//!   dashboard.rs:1232   secs_remaining  — rows filtered `g.is_live(now)`     → CORRECT
//!   governance_ledger.rs:488 secs_remaining — guarded `status == Open`       → CORRECT
//!   handler.rs:13589    retry_within_secs — emitted on the OPEN path         → a supremum
//!
//! Every countdown this crate renders is anchored to `expires_at`, and every one of them is
//! correct, because every one of them is gated to a row that is still OPEN. Not one is
//! rendered for a DECIDED row. `decided_horizon()` — the only function that knows when a
//! grant dies — is private, and `grep` finds it at exactly five sites: its own definition,
//! `is_claimable`, and three assertions in its own test module. It reaches no surface.
//!
//! The consequence is observable outside this repo. On 2026-08-15 the operator approved two
//! twin escalations at 22:07:19Z; the deadline reached the asker as a hand-computed string
//! in a mesh notice from a peer — `claim-horizon-22:17:19Z-decided_at+600 ... SPEND NOW`
//! (kimi-code notice 2632). A peer had to compute the enforcing horizon by hand and deliver
//! it out-of-band, because no surface of the system that enforces it will say it.
//!
//! WHAT THIS FILE IS. Three OPEN-DEFECT PINS, in the hole-J shape: each asserts the
//! CURRENT WRONG BEHAVIOUR, so each is green while the defect stands and goes RED the moment
//! it is fixed. A red here is the intended end state, and the failure message says so.

use hestia::server::gate_escalation::{
    Channel, EscalationStore, Status, APPROVAL_CLAIM_WINDOW_SECS, DEFAULT_TTL_SECS,
};
use std::fs;
use std::path::Path;

const T0: u64 = 1_800_000_000;

/// The value `handler.rs` puts on the wire as `retry_within_secs`.
///
/// Deliberately NOT `DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS` written out here. The
/// first draft of this file did exactly that, and it was blind to the thing it claimed to
/// pin: a fix at the emitting site would have left the arithmetic — and therefore the pin —
/// untouched and green, reporting an open defect that had been closed. A derived constant
/// needs its PRODUCER, not a re-derivation that happens to agree today.
const ADVERTISED_RETRY_EXPR: &str =
    r#""retry_within_secs": DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS,"#;

/// The production (non-comment) lines of one `async fn` in `src`, ending at the first
/// item-position closing brace. Comment lines are dropped BEFORE matching, so the pin cannot
/// be satisfied by the prose that explains it. Same shape as
/// `tests/verdict_available_writer.rs`, which this borrows.
fn production_body(rel: &str, want_fn: &str) -> String {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let text = fs::read_to_string(src.join(rel)).unwrap_or_else(|e| panic!("read {rel}: {e}"));
    let opener = format!("async fn {want_fn}(");
    let mut in_fn = false;
    let mut out = Vec::new();
    for line in text.lines() {
        if !in_fn {
            if line.trim_start().starts_with(&opener) {
                in_fn = true;
            }
            continue;
        }
        if line == "}" {
            break;
        }
        let t = line.trim();
        if t.starts_with("//") {
            continue;
        }
        out.push(t.to_string());
    }
    assert!(in_fn, "fn `{want_fn}` not found in {rel} — this pin is measuring nothing");
    assert!(!out.is_empty(), "fn `{want_fn}` body read as empty in {rel}");
    out.join("\n")
}

/// Open one escalation on a `SingleApprover` marker, so a lone sovereign approval meets the
/// bar and the claim path is reachable without a peer factor.
fn opened(ttl: u64) -> (EscalationStore, String) {
    let mut s = EscalationStore::default();
    let e = s
        .open(
            "claude-code",
            "role:constellation:member",
            "Edit",
            "law_inject.py",
            None,
            None,
            T0,
            ttl,
        )
        .expect("open");
    (s, e.id)
}

fn approve_at(s: &mut EscalationStore, id: &str, at: u64) {
    s.decide(
        id,
        true,
        "dp",
        "role:constellation:sovereign",
        Channel::LocalCli,
        None,
        Some("ok"),
        at,
    )
    .expect("decide");
}

/// PIN 1 — the advertised deadline is not merely loose, it is UNREACHABLE.
///
/// `decide()` refuses a row whose `status_at(now)` is `Expired`, and `status_at` expires at
/// `now >= expires_at`. So the last instant at which any decision can legally land is
/// `expires_at - 1`, and the supremum of `decided_horizon()` over every legal decision is
/// `T0 + 3599 + 600 = T0 + 4199`. The asker is told 4200. There exists no history — not one,
/// not even the adversarially latest — in which the advertised deadline is honoured.
///
/// This is the assertion that makes "swap 4200 for 600" visibly the wrong remedy: the number
/// is not off by a factor, it is off by a *question*.
#[test]
fn the_advertised_retry_deadline_is_attainable_in_no_history() {
    // Bind to the PRODUCER first. If this line ever moves or changes, everything below is
    // arithmetic about a number nobody emits.
    let body = production_body("server/handler.rs", "tool_gate_escalation_claim");
    assert!(
        body.contains(ADVERTISED_RETRY_EXPR),
        "OPEN-DEFECT PIN 1 has gone RED, which is the intended end state. \
         `tool_gate_escalation_claim` no longer emits `{ADVERTISED_RETRY_EXPR}`. Check the \
         remedy did NOT simply substitute APPROVAL_CLAIM_WINDOW_SECS, which is equally wrong \
         at open time (`decided_at` is still None there); the honest answer names the ANCHOR \
         — the retry clock starts at the DECISION — rather than any constant."
    );
    let advertised_retry_secs = DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS;

    let mut best_horizon = 0;
    // Every legal decision instant in a full-TTL escalation, sampled at both ends and across
    // the interior. The maximum over this set IS the supremum: `decided_horizon` is
    // monotone in `decided_at` while the grant ceiling binds.
    for grant_offset in [0, 1, 4, 60, 600, 1800, 3598, 3599] {
        let (mut s, id) = opened(DEFAULT_TTL_SECS);
        approve_at(&mut s, &id, T0 + grant_offset);
        // Walk out to the last claimable second by bisection-free probing: the horizon is
        // grant + window, so claim must succeed at grant+window-1 and fail at grant+window.
        let last_ok = T0 + grant_offset + APPROVAL_CLAIM_WINDOW_SECS - 1;
        assert!(
            s.claim("claude-code", "law_inject.py", last_ok).is_some(),
            "grant at +{grant_offset}: the window did not run its full length"
        );
        best_horizon = best_horizon.max(last_ok + 1 - T0);
    }
    // The latest a decision may land is expires_at - 1 = T0 + 3599.
    let (mut s, id) = opened(DEFAULT_TTL_SECS);
    assert_eq!(
        s.status_of(&id, T0 + DEFAULT_TTL_SECS - 1),
        Status::Pending,
        "the last second before expiry must still be decidable"
    );
    assert!(
        s.decide(
            &id,
            true,
            "dp",
            "role:constellation:sovereign",
            Channel::LocalCli,
            None,
            Some("ok"),
            T0 + DEFAULT_TTL_SECS
        )
        .is_err(),
        "a decision AT expiry must be refused, or the supremum below is not the supremum"
    );

    assert_eq!(
        best_horizon, 4_199,
        "supremum of the enforced horizon over all legal decisions, in seconds from open"
    );
    assert!(
        advertised_retry_secs > best_horizon,
        "the emitted retry_within_secs={advertised_retry_secs}s no longer exceeds the \
         enforced supremum of {best_horizon}s from open"
    );
    assert_eq!(
        (advertised_retry_secs, best_horizon),
        (4_200, 4_199),
        "the two numbers, pinned: what the asker is told, and the most the gate will ever honour"
    );
}

/// PIN 2 — the over-report is not a constant factor. It is `expires_at - decided_at`, and it
/// GROWS the faster the decider answers.
///
/// The "7x" both seats quoted is the ratio at the worst case only. A responsive operator
/// makes it worse, not better: the twins ruled on 2026-08-15 were decided ~4s after their
/// outcome rows, leaving a real 600s window against an advertised 4200 — an over-report of
/// 3596s, 99.9% of the advertised remainder being fiction. A surface that punishes the
/// decider for being prompt is not a rounding error.
#[test]
fn the_over_report_grows_as_the_decision_gets_faster() {
    // Same producer binding as PIN 1: the magnitudes below are about an emitted number.
    let body = production_body("server/handler.rs", "tool_gate_escalation_claim");
    assert!(
        body.contains(ADVERTISED_RETRY_EXPR),
        "OPEN-DEFECT PIN 2 has gone RED, which is the intended end state: the emitting site \
         no longer carries `{ADVERTISED_RETRY_EXPR}`."
    );
    let advertised_retry_secs = DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS;

    let mut rows = Vec::new();
    for grant_offset in [4, 60, 600, 3599] {
        let (mut s, id) = opened(DEFAULT_TTL_SECS);
        approve_at(&mut s, &id, T0 + grant_offset);
        let real_deadline_from_open = grant_offset + APPROVAL_CLAIM_WINDOW_SECS;
        let over_report = advertised_retry_secs - real_deadline_from_open;

        // The asker who believed the advertised deadline and returned inside it is refused.
        assert!(
            s.claim("claude-code", "law_inject.py", T0 + advertised_retry_secs - 1)
                .is_none(),
            "grant at +{grant_offset}: a claim at the advertised deadline was honoured"
        );
        rows.push((grant_offset, over_report));
    }

    // Strictly decreasing over-report as the decision gets later — i.e. strictly INCREASING
    // as the decider gets faster. This is the shape, not the magnitude.
    for w in rows.windows(2) {
        assert!(
            w[0].1 > w[1].1,
            "OPEN-DEFECT PIN 2 has gone RED, which is the intended end state. The advertised \
             retry deadline no longer over-reports in inverse proportion to decision latency \
             (grant +{}s over-reported {}s; grant +{}s over-reported {}s).",
            w[0].0,
            w[0].1,
            w[1].0,
            w[1].1
        );
    }
    assert_eq!(
        rows[0].1, 3_596,
        "the 4-second grant — the live 2026-08-15 case — must over-report by 3596s"
    );
}

/// PIN 3 — the grant surface carries no deadline at all, and the countdown it *does* expose
/// for a decided row is the wrong clock.
///
/// `decision_reply()` is what a member reads back from BOTH deciding surfaces (`poll` and
/// `arbitrate`, per the doc comment at its definition: "the answer moves here and both
/// callers read it"). Its `note` tells the asker, in the approved branch, to go and re-issue
/// the write. That is the single moment in the lifecycle where a member is instructed to
/// act inside a window — and the reply names no window, no deadline, and no anchor.
///
/// Meanwhile `secs_remaining()` still answers, and still answers about `expires_at`, so a
/// member who reaches for the only countdown on the object gets the TTL remainder: a number
/// that is larger than the truth for the whole life of the grant.
#[test]
fn the_grant_surface_renders_no_claim_deadline() {
    let granted_at = T0 + 4;
    let (mut s, id) = opened(DEFAULT_TTL_SECS);
    approve_at(&mut s, &id, granted_at);
    let esc = s.get(&id).expect("get").clone();

    let reply = esc.decision_reply();
    let obj = reply.as_object().expect("decision_reply is an object");

    // (a) The reply does instruct the asker to act.
    assert!(
        reply["permits_write"].as_bool() == Some(true),
        "fixture must produce a live permit or the pin tests nothing"
    );
    assert!(
        reply["note"].as_str().unwrap_or_default().contains("RE-ISSUE"),
        "fixture must be on the branch that sends the asker off to spend"
    );

    // (b) ...and carries nothing they could compute a deadline from. Checked by VALUE, not
    // by name: any field carrying the horizon, the grant instant, or a remaining count would
    // close this hole whatever it were called, and a name-only check would pass on a rename.
    let horizon = granted_at + APPROVAL_CLAIM_WINDOW_SECS;
    let tells = [
        horizon,                    // the deadline itself
        granted_at,                 // the anchor, from which it is derivable
        APPROVAL_CLAIM_WINDOW_SECS, // the length, ditto
    ];
    let leak: Vec<&String> = obj
        .iter()
        .filter(|(_, v)| {
            v.as_u64().map(|n| tells.contains(&n)).unwrap_or(false)
                || v.as_str()
                    .map(|t| tells.iter().any(|n| t.contains(&n.to_string())))
                    .unwrap_or(false)
        })
        .map(|(k, _)| k)
        .collect();
    assert!(
        leak.is_empty(),
        "OPEN-DEFECT PIN 3 has gone RED, which is the intended end state. The grant reply now \
         carries the claim deadline via {leak:?} — the hole this pins is closed. Delete this \
         test and keep the field."
    );

    // (c) The only countdown on the object answers the other question, and answers it larger.
    let ttl_remainder = esc.secs_remaining(granted_at);
    let true_remaining = horizon - granted_at;
    assert!(
        ttl_remainder > true_remaining,
        "OPEN-DEFECT PIN 3(c) has gone RED: secs_remaining no longer over-reports on a \
         decided row ({ttl_remainder}s reported vs {true_remaining}s enforced)"
    );
    assert_eq!(
        (ttl_remainder, true_remaining),
        (3_596, 600),
        "the magnitudes, pinned so a change of anchor cannot pass as a change of clock"
    );
}

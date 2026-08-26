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
//!   handler.rs:14242    secs_remaining  — the PENDING-escalation queue       → CORRECT
//!   handler.rs:13870    secs_remaining  — `poll`, gated to NOTHING           → the hole
//!   handler.rs:13589    retry_within_secs — emitted on the OPEN path         → a supremum
//!
//! CORRECTED 2026-08-18 (claude-code, from the asker's seat). The 08-15 enumeration above
//! ran to five rows and concluded "every countdown is gated to a row that is still OPEN;
//! not one is rendered for a DECIDED row". It was 5/7, and one of the two it missed —
//! `handler.rs:13870`, the `poll` handler — is the direct counter-example to the sentence it
//! was supporting: `poll` takes any id, renders `secs_remaining` unconditionally, and a
//! DECIDED row is exactly what a member polls, because a `disposition` notice is what sends
//! them there. A completeness claim standing behind an incomplete recount, which is the
//! failure `fb_recount_set_behind_completeness` names, committed in the file that pins it.
//! The conclusion survives the correction and PIN 4 is what the missed row earned.
//!
//! `decided_horizon()` — the only function that knows when a grant dies — is private, and
//! `grep` finds it at exactly five sites: its own definition, `is_claimable`, and three
//! assertions in its own test module. It reaches no surface. `is_claimable` itself has ONE
//! production caller in the crate — `EscalationStore::claim` (gate_escalation.rs:1151, inside
//! the candidate filter) — so the only instrument that answers "is this permit still alive"
//! answers by spending it. (Named `claim_for` in the first draft of this file; corrected on
//! GPT's not-same review, verified by grep at the head under review.)
//!
//! The consequence is observable outside this repo. On 2026-08-15 the operator approved two
//! twin escalations at 22:07:19Z; the deadline reached the asker as a hand-computed string
//! in a mesh notice from a peer — `claim-horizon-22:17:19Z-decided_at+600 ... SPEND NOW`
//! (kimi-code notice 2632). A peer had to compute the enforcing horizon by hand and deliver
//! it out-of-band, because no surface of the system that enforces it will say it.
//!
//! WHAT THIS FILE IS. Four OPEN-DEFECT PINS, in the hole-J shape: each asserts the
//! CURRENT WRONG BEHAVIOUR, so each is green while the defect stands and goes RED the moment
//! it is fixed. A red here is the intended end state, and the failure message says so.
//!
//! TURNOVER LEDGER, so a reader can tell a pin that is still WAITING from one that has been
//! PAID. A turned-over pin keeps its history in place and inverts its assertion; none are
//! deleted, because the specimen is the durable part.
//!
//!   PIN 1        — OPEN.        `retry_within_secs` still emits the supremum at open time.
//!   PIN 2        — OPEN.        the emitting site still has no decided-anchored deadline.
//!   PIN 4(a)-(c) — TURNED OVER #518/#528. `permits_write` reads `is_claimable(now)` and
//!                                the poll renders `claim_window_secs_remaining`.
//!   PIN 4(d)     — TURNED OVER #611, 2026-08-26. The note is produced by
//!                                `Escalation::claim_note(now)` and names WHICH of the two
//!                                causes of `permits_write: false` a payload carries.
//!
//! The last of those is the one worth restating, because the pin's own failure message
//! anticipated the wrong fix: deleting the false sentence would have turned it red without
//! closing anything. `permits_write: false` has two causes — SPENT and LAPSED — and every
//! other field the poll renders is identical between them. Prose that says nothing and prose
//! that says the wrong thing fail an asker in the same place.

use hestia::server::gate_escalation::{
    Channel, EscalationStore, Status, APPROVAL_CLAIM_WINDOW_SECS, DEFAULT_TTL_SECS,
};
use std::fs;
use std::path::Path;

/// The act every open and every claim in this suite states (#539). Shared on purpose: this
/// file measures the CLAIM HORIZON, so the act must never be what refuses a claim here.
const HORIZON_ACT: &str = "Edit -> law_inject.py";

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

/// The expression `tool_gate_escalation_poll` puts on the wire as `permits_write` AFTER #518.
///
/// Producer-bound for the same reason `ADVERTISED_RETRY_EXPR` is: a re-derivation here would
/// stay green through a change at the emitting site. Inherited from
/// `permits_write_outlives_the_claim_horizon.rs`, where it named the pre-#518 expression.
const POLL_PERMITS_WRITE_EXPR: &str =
    r#""permits_write": esc.map(|e| e.is_claimable(now)).unwrap_or(false),"#;

/// The RETIRED poll note — the two-conjunct rule the `permits_write` field stopped using at
/// #518 and the sentence beside it kept teaching for six days after.
///
/// This is the string the live daemon returned at 18:45Z on 2026-08-18 for
/// `5725d296b05cbc4c`, 83 minutes after that grant stopped being claimable; again at
/// 00:29:56Z on 2026-08-19 for `b1e32c344564f08e`, this seat's own permit, from a daemon
/// whose binary predates the fix; and last at 20:24Z on 2026-08-24 for `27a25b66e7fe22d0`,
/// beside `approved` + `bar_met: true` + `permits_write: false` on a permit claimed 41s
/// after its grant — the payload that finally motivated #611.
///
/// Kept as a NEGATIVE constant: PIN 4(d) below now asserts this appears in no producer.
const POLL_TWO_CONJUNCT_NOTE: &str =
    "authoritative as of now; only `approved` WITH the stated bar met permits the write";

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

/// The WHOLE text of one file in `src`, comments included.
///
/// Deliberately un-stripped, unlike `production_body`: its one use below is a NEGATIVE
/// assertion — a retired string must appear nowhere — and for that, prose is not an escape
/// hatch but a place the literal can hide and be copied back out of.
fn production_text(rel: &str) -> String {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    fs::read_to_string(src.join(rel)).unwrap_or_else(|e| panic!("read {rel}: {e}"))
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
            // #539: the act is bound at open and must be re-stated at claim. This suite is
            // about the HORIZON, so both ends name the same act deliberately — otherwise the
            // act mismatch would refuse the claim and the horizon would stop being the thing
            // under test. One shared constant keeps the horizon the only variable.
            Some(HORIZON_ACT),
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
            s.claim("claude-code", "law_inject.py", Some(HORIZON_ACT), last_ok).is_some(),
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
            s.claim("claude-code", "law_inject.py", Some(HORIZON_ACT), T0 + advertised_retry_secs - 1)
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

/// TURNED OVER 2026-08-19 by #518 (`6983b48`). PIN 3 went red exactly as designed: the leak
/// scan named `claim_window_secs_remaining`, the field that closes the hole. What follows is
/// the same fixture with the assertions inverted — a REGRESSION test, not a pin. Its (c) half
/// survives unchanged and is now an INVARIANT rather than a complaint: `secs_remaining` still
/// answers about `expires_at` and still reads larger, and that is correct, because the two
/// clocks are two different questions. Before the turnover a reader had only the wrong one;
/// the fix added the right one beside it rather than repointing it, which is why (c) must keep
/// firing — if `secs_remaining` ever starts agreeing with the horizon, one of the two
/// questions has silently stopped being answerable.
///
/// ORIGINAL PIN TEXT, kept because it is the record of what was measured:
///
/// PIN 3 — the grant surface carries no deadline at all, and the countdown it *does* expose
/// for a decided row is the wrong clock.
///
/// `decision_reply()` is what the DECIDER surfaces answer with — `tool_gate_arbitrate_escalation`
/// (the MCP arbiter) and `operator_gate_escalation` (the operator's HTTP door). Its own doc
/// comment's "both callers read it" means those two, not the asker's poll: verified at the
/// reviewed head, `tool_gate_escalation_poll` builds its own `json!` and never calls this.
/// That distinction is the seam between this pin and PIN 4 and the first draft blurred it —
/// corrected on GPT's not-same review. PIN 3 is the DECIDER's reply omitting the horizon;
/// PIN 4 is the ASKER's poll actively contradicting the enforcement.
///
/// Its `note` tells the asker, in the approved branch, to go and re-issue the write. That is the single moment in the lifecycle where a member is instructed to
/// act inside a window — and the reply names no window, no deadline, and no anchor.
///
/// Meanwhile `secs_remaining()` still answers, and still answers about `expires_at`, so a
/// member who reaches for the only countdown on the object gets the TTL remainder: a number
/// that is larger than the truth for the whole life of the grant.
#[test]
fn the_grant_surface_renders_the_claim_deadline() {
    let granted_at = T0 + 4;
    let (mut s, id) = opened(DEFAULT_TTL_SECS);
    approve_at(&mut s, &id, granted_at);
    let esc = s.get(&id).expect("get").clone();

    let reply = esc.decision_reply(granted_at);
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

    // (b) ...and now carries something they can compute a deadline from. Checked by VALUE,
    // not by name — the same scan the pin ran, read in the other direction: a field carrying
    // the horizon, the grant instant, or the remaining count closes this hole whatever it is
    // called, and a name-only check would break on a rename that changed nothing.
    let horizon = granted_at + APPROVAL_CLAIM_WINDOW_SECS;
    let tells = [
        horizon,                    // the deadline itself
        granted_at,                 // the anchor, from which it is derivable
        APPROVAL_CLAIM_WINDOW_SECS, // the length, ditto
    ];
    let carriers: Vec<&String> = obj
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
        !carriers.is_empty(),
        "REGRESSION: the grant reply has stopped carrying the claim deadline. #518 added \
         `claim_window_secs_remaining`; nothing in {reply} now answers it, so the asker is \
         back to being instructed to act inside a window the reply will not name."
    );
    // Named as well as valued, because a rename is a real event a reader should be told
    // about: this is the field #518 put there, and the value is the WINDOW at the grant
    // instant, not the TTL remainder.
    assert_eq!(
        reply["claim_window_secs_remaining"].as_u64(),
        Some(APPROVAL_CLAIM_WINDOW_SECS),
        "at the grant instant the whole window is left, anchored on the GRANT: {reply}"
    );

    // (c) INVARIANT, not a defect: the OTHER countdown still answers the other question, and
    // still answers it larger. Two clocks, deliberately unequal — `secs_remaining` is the
    // record's TTL and `claim_window_secs_remaining` is the permit's horizon. If these ever
    // agree, one of the two facts has stopped being reachable.
    let ttl_remainder = esc.secs_remaining(granted_at);
    let true_remaining = horizon - granted_at;
    assert!(
        ttl_remainder > true_remaining,
        "INVARIANT BROKEN: secs_remaining no longer over-reports against the claim horizon \
         on a decided row ({ttl_remainder}s reported vs {true_remaining}s enforced). It is \
         supposed to: it is the RECORD clock. Check that repointing it did not delete the \
         only surface answering how long the escalation itself survives."
    );
    assert_eq!(
        (ttl_remainder, true_remaining),
        (3_596, 600),
        "the magnitudes, pinned so a change of anchor cannot pass as a change of clock"
    );
}

/// TURNED OVER 2026-08-19 by #518 (`6983b48`), which moved `tool_gate_escalation_poll` onto
/// `is_claimable(now)` and gave it `claim_window_secs_remaining`. The pin went red at its own
/// fixture guard — "the producer expression this pin is about has moved" — which is the guard
/// doing its job: it refused to report on a body it no longer recognised rather than passing
/// or failing on a stale string.
///
/// It is inverted rather than deleted because the poll surface has NO other test. `grep` for
/// `tool_gate_escalation_poll` in `src/` finds two hits at the head of this change: the
/// dispatch arm and the definition. Deleting this file's poll half would have left the fix
/// with zero coverage at the one surface an asker actually reads — the shape
/// `fb_supersession_claim_hides_what` names. The in-crate replacements
/// (`permits_write_tracks_the_two_conjuncts_that_move`,
/// `one_answer_serves_both_deciding_surfaces`) exercise `decision_reply`, which is the
/// DECIDER's answer, not this one.
///
/// (d) is the half that did NOT turn over, and it moved here from
/// `permits_write_outlives_the_claim_horizon.rs` PIN 2(d) when that file was retired: the
/// note is unchanged and now describes a rule the field beside it stopped using.
///
/// ORIGINAL PIN TEXT, kept because it is the record of what was measured:
///
/// PIN 4 — past the horizon, every field the asker reads still says the permit is live.
///
/// MEASURED BEFORE IT WAS PINNED, from the asker's seat, on 2026-08-18. Escalation
/// `0ba3d769dffe4964` (marker `pre_tool_use.py`, bar `sovereign_plus_peer`) opened 06:57:53Z,
/// was approved by the operator at 07:01:22Z, and therefore stopped being claimable at
/// 07:11:22Z. Polled at 07:11:43Z — 21 seconds dead — `hestia_gate_escalation_poll` answered:
///
///   status          "approved"
///   permits_write   true
///   bar_met         true
///   secs_remaining  2770
///   note            "authoritative as of now; only `approved` WITH the stated bar met
///                    permits the write"
///
/// Five fields, and the one that asserts authority is the `note`. `is_claimable(now)` was
/// false at that instant by both of its ceilings' minimum, and the poll handler calls it
/// nowhere: `grep is_claimable core/src` finds ONE production site in the whole crate —
/// `EscalationStore::claim` (gate_escalation.rs:1151) — so the predicate that decides is
/// reachable only by spending. The single instrument that answers "is this permit alive"
/// destroys the permit as the price of the answer, which is why no reviewer can check the
/// thing they are being asked to certify.
///
/// This is the ASKER's surface, and PIN 3 is the DECIDER's. PIN 3 says the decision reply
/// omits the horizon; PIN 4 says the fields the asker's poll *does* carry actively
/// contradict the enforcement, and keep contradicting it for as long as the record survives.
///
/// WHAT WOULD CLOSE THIS PIN, stated so the fix is not mistaken for its opposite. The defect
/// is the SURFACE IMPLICATION, never the historical verdict:
///
///   * `permits_write` in the poll reply must stop being derived from
///     `Status::permits_write()`, which is `matches!(self, Status::Approved)` with no clock
///     in it at all, and must instead reflect `is_claimable(now)`;
///   * the reply must EXPOSE the claim horizon — a deadline or a remaining-seconds figure
///     computed from `decided_horizon()`, not the record TTL that `secs_remaining()` reports;
///   * `status` may keep saying `Approved`, because it is true. See the invariant in (b).
///
/// A "fix" that ages a decided row into `Expired` satisfies the letter of the old failure
/// messages and breaks two things: it rewrites a historical fact, and it starts refusing
/// corroboration, which keys on `status_at(now) == Status::Expired`.
#[test]
fn past_the_horizon_the_asker_surface_reads_dead() {
    let granted_at = T0 + 209; // the live specimen's open→decide lag, to the second
    let (mut s, id) = opened(DEFAULT_TTL_SECS);
    approve_at(&mut s, &id, granted_at);
    let esc = s.get(&id).expect("get").clone();

    let dead = granted_at + APPROVAL_CLAIM_WINDOW_SECS + 21; // the live specimen's overshoot
    assert!(
        dead < T0 + DEFAULT_TTL_SECS,
        "the fixture must be past the CLAIM horizon and inside the RECORD ttl, or it pins the \
         uninteresting case where both clocks agree"
    );

    // (a) The enforcement. Not asserted through `claim`, because claiming is the act this
    // whole file exists to say a reviewer cannot perform in order to find out.
    assert!(
        !esc.is_claimable(dead),
        "fixture is not past the horizon — the rest of this pin would measure nothing"
    );

    // (b) THE CONTRAST, and it is an INVARIANT rather than an open defect.
    //
    // `Approved` is a truthful historical fact and must stay one forever: the operator DID
    // approve this escalation, and no clock retracts that. What expired is the ability to
    // SPEND the approval. The first draft of this pin had the failure message declare the
    // intended end state to be "a decided row now expires on the claim clock as well as the
    // record clock" — i.e. it asked for the historical verdict to be rewritten into
    // `Expired`. GPT's not-same review caught that, and it is right on two grounds:
    //
    //   * DECISION OUTCOME and CURRENT AUTHORITY are different facts, and this fleet has
    //     repeatedly paid to keep them apart. Collapsing them here would undo that.
    //   * It would perturb post-decision participation. `corroborate` refuses on
    //     `status_at(now) == Status::Expired` (gate_escalation.rs:1271), so aging a decided
    //     row into `Expired` would silently start refusing corroboration on rows that were
    //     legitimately decided.
    //
    // So this assertion is the SPECIMEN, not the complaint: `Approved` is true at the same
    // instant `is_claimable` is false, and that pair IS the defect — two answers about one
    // permit, one of which the surfaces render and the other of which the gate enforces.
    // If this row ever goes red, someone rewrote history; that is a regression, not the fix.
    assert_eq!(
        esc.status_at(dead),
        Status::Approved,
        "INVARIANT BROKEN, not a defect closed: the historical verdict has been rewritten. \
         `Approved` records that the operator approved this escalation and must remain true \
         for as long as the record exists — the claim horizon governs whether the approval \
         can still be SPENT, never whether it was given. Check that nothing now ages a \
         decided row into `Expired`; `corroborate` refuses on exactly that value."
    );
    // Still true, and still not a defect: `status_at().permits_write()` is a property of the
    // STATUS enum — "this verdict was an approval" — and the poll no longer composes its
    // `permits_write` from it. Kept so that a future reader who greps `permits_write()` and
    // finds this true does not re-file the closed defect.
    assert!(
        esc.status_at(dead).permits_write(),
        "the status enum's own predicate has changed meaning; re-read the poll producer before \
         trusting the assertions below"
    );
    let ticking = esc.secs_remaining(dead);
    assert!(
        ticking > 0,
        "INVARIANT BROKEN: the RECORD countdown has stopped while the record is still alive."
    );
    assert_eq!(
        ticking, 2_770,
        "the live specimen's number, reproduced in-process from its own timings — pinned so a \
         change of anchor cannot pass as a change of clock"
    );
    // THE TURNOVER. The two answers that used to disagree now agree, at the instant they
    // used to diverge: the horizon countdown is spent, and the enforcing predicate refuses.
    assert_eq!(
        esc.claim_window_secs_remaining(dead),
        0,
        "past the horizon the permit's own countdown must read zero, whatever the record's says"
    );
    assert!(
        !esc.is_claimable(dead),
        "control: the enforcement refuses here, or the agreement above is vacuous"
    );

    // (c) The structural cause, checked at the surface rather than inferred — now in the
    // other direction: the handler the asker reads composes its answer from the predicate
    // that enforces. Checked on the PRODUCTION body, comments stripped, so the prose above
    // cannot satisfy it.
    let poll = production_body("server/handler.rs", "tool_gate_escalation_poll");
    assert!(
        poll.contains(POLL_PERMITS_WRITE_EXPR),
        "REGRESSION: the poll surface has stopped composing `permits_write` from the enforcing \
         predicate. This is the field an asker reads to decide whether to spend a permit, and \
         the only in-repo instrument watching it is this line — `tool_gate_escalation_poll` \
         has no test of its own (grep finds two hits in src/: the dispatch arm and the fn)."
    );
    assert!(
        poll.contains("claim_window_secs_remaining"),
        "REGRESSION: the poll surface has stopped rendering the horizon it enforces against."
    );

    // (d) TURNED OVER, 2026-08-26 (#611). Was: THE HALF THAT DID NOT TURN OVER — moved here
    // from PIN 2(d) of `permits_write_outlives_the_claim_horizon.rs` when that file was
    // retired, and the last of this file's four pins still asserting a wrong behaviour.
    //
    // WHAT IT PINNED. The field learned four conjuncts at #518; the sentence beside it kept
    // teaching two. A reader who took the note at its word concluded that an approval which
    // is `approved` with its bar met permits the write — which is exactly the case
    // `permits_write: false` is emitted for, on a spent or horizon-dead permit. Before #518
    // the note was wrong in the same direction as the field, so it added nothing; after
    // #518 it CONTRADICTED the field it annotates, and the note is the half a reader is
    // likelier to quote.
    //
    // WHAT CLOSED IT, and why the assertions below are shaped this way. The pin's failure
    // message did not ask for the false sentence to be DELETED — a bare `permits_write:
    // false` with no note leaves an asker unable to tell a deny from an expiry, which is a
    // different defect at the same surface. It asked that the replacement NAME THE SPENT AND
    // HORIZON CONJUNCTS. So the turnover checks the naming on BEHAVIOUR, against two
    // specimens that differ in nothing else, and checks on source only the two things
    // behaviour cannot see: that one producer feeds the surface, and that the retired
    // sentence is gone from every file that could copy it back.
    for rel in ["server/handler.rs", "server/gate_escalation.rs"] {
        assert!(
            !production_text(rel).contains(POLL_TWO_CONJUNCT_NOTE),
            "REGRESSION: the retired two-conjunct note is back in {rel}. It states the \
             pre-#518 rule that `permits_write` stopped using, so it reads as a GRANT on \
             every payload where the permit is spent or past its horizon — the exact \
             payloads a poll is issued to check."
        );
    }
    assert!(
        poll.contains("e.claim_note(now)"),
        "REGRESSION: the poll surface has stopped taking its note from the single producer. \
         A second sentence written at this call site is how the first one drifted: the field \
         was repaired at one site and the prose explaining it at another, and nothing \
         compiles a string literal."
    );

    // THE DISCRIMINATION, on behaviour. Two permits that render IDENTICALLY in every other
    // field the poll carries — `approved`, `bar_met: true`, `granted: true`,
    // `permits_write: false`, `claim_window_secs_remaining: 0` — separated only by cause:
    // this one LAPSED, the next was SPENT. Measured live as one shape on CBP 2026-08-26
    // 03:10Z (`c5e2cab3c68874c4` lapsed, `365289a4402c4f13` spent).
    let lapsed_note = esc.claim_note(dead);
    assert!(
        lapsed_note.contains("CLAIM WINDOW HAS CLOSED"),
        "the HORIZON conjunct is unnamed: an asker past the horizon is told the write is \
         refused and not that its own clock is what refused it, got {lapsed_note:?}"
    );
    assert_eq!(
        esc.consumed_at, None,
        "the lapsed specimen must be unspent, or it is not the state this arm names"
    );

    let (mut spent_store, spent_id) = opened(DEFAULT_TTL_SECS);
    approve_at(&mut spent_store, &spent_id, granted_at);
    assert!(
        spent_store
            .claim("claude-code", "law_inject.py", Some(HORIZON_ACT), granted_at + 1)
            .is_some(),
        "the spent arm is only in-domain if the claim actually lands"
    );
    let spent = spent_store.get(&spent_id).expect("get").clone();
    let spent_note = spent.claim_note(dead);
    assert!(
        spent_note.contains("ALREADY BEEN CLAIMED"),
        "the SPENT conjunct is unnamed, got {spent_note:?}"
    );
    assert!(
        spent.consumed_at.is_some(),
        "`consumed_at` is the machine-readable half of this same distinction, and #611 put it \
         on the poll: the note is for a human, this field is for the peer auditing which of \
         N approvals on a shared marker was the one actually spent"
    );
    assert_ne!(
        lapsed_note, spent_note,
        "SPENT and LAPSED render the SAME sentence, so the note discriminates nothing and the \
         deletion-shaped fix has happened instead of the naming-shaped one"
    );
    assert!(
        !esc.is_claimable(dead) && !spent.is_claimable(dead),
        "control: both specimens must be refused at this instant, or the two notes above \
         describe states that never co-occur with `permits_write: false` and this arm is \
         vacuous"
    );
}

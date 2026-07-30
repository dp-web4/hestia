//! Gate self-write escalation — a human approval gate on writes to the governance surface.
//!
//! Stage 2 of the ruling dp gave on 2026-07-29, PR #97 having landed stage 1:
//!
//! > "yes, witnessed read, write refused with escalation, fail closed. escalate to human for
//! > approval (there are legit times when we are actually working on the file), deny on timeout
//! > of a couple minutes."
//!
//! Stage 1 refuses every write to the gate's own code. That is correct and it is also too much:
//! the fleet legitimately edits its gates (#55, #89, #90 in one week). This restores that path
//! and puts a human across it.
//!
//! # What this is NOT, said first
//!
//! **This is not a security boundary against a determined member, and must never be described as
//! one.** hestia is assurance profile **A1** — a cooperative gate, not OS isolation. Every member
//! runs as the same UID as the operator (HST-009), so a member CAN run the approve command itself.
//! Nothing here prevents that, and a design that claimed otherwise would be the reassuring bit
//! that is identical to the null state.
//!
//! What it actually buys, in order of how much it is worth:
//!
//! 1. **The legitimate case stops being blocked.** That is the whole point. dp said there are
//!    real times we work on the file, and stage 1 alone makes those impossible.
//! 2. **Self-approval leaves a record.** Running the approve command is itself a tool call, so
//!    it passes the gate and is witnessed like any other. The evasion is not blocked and it is
//!    not silent. NOTE: it is not yet given its own event class — an earlier draft of this
//!    comment named a `gate_self_approval` severity that does not exist, which would have sent
//!    the next reader looking for a door that was never built.
//! 3. **Every decision names its channel.** `via` records whether approval arrived from the
//!    local CLI (same-UID, weak) or an authenticated operator HTTP session (LCT
//!    challenge/response, strong). A reader can weigh them differently because they ARE
//!    different, and collapsing them into "approved" would throw away the only evidence that
//!    distinguishes them.
//!
//! Climbing the assurance ladder is the fix for (1) and (2); it is not available today, and
//! pretending otherwise is worse than the gap.
//!
//! # Fail-closed, in the three places it has to be
//!
//! Every uncertain branch DENIES, because the alternative is a governance write that proceeded
//! because nobody said no:
//!
//! * **Timeout.** A pending escalation past its deadline is `Expired`, which the hook treats as a
//!   deny. Nobody has to be watching for the safe thing to happen.
//! * **Unknown id.** A poll for an id this store has never seen returns `Expired`, not an error
//!   the caller might mistake for "still working on it". A daemon restart drops the store, so
//!   every escalation in flight across a restart correctly reads as denied.
//! * **A hook that cannot wait.** The harness gives `pre_tool_use.py` **5 seconds**, and a hook
//!   it kills yields neither `exit 2` nor a JSON deny — Claude Code then runs the tool anyway.
//!   So waiting in-hook for a human fails OPEN, not closed. The shape is therefore deny-now /
//!   decide-out-of-band / retry: refuse immediately, let a human decide whenever, and let the
//!   member re-issue the write to `claim` the approval in one fast round trip.
//! * **Late decision.** `decide` REFUSES once expired. Otherwise an operator approving at T+150s
//!   would flip a verdict the hook already acted on at T+120s, and the record would disagree
//!   with what happened.

use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};

/// How long a pending escalation lives. dp: "deny on timeout of a couple minutes."
pub const DEFAULT_TTL_SECS: u64 = 120;

/// How long an APPROVAL stays claimable after it is granted.
///
/// This exists because the hook cannot wait. `plugin.json` and the live `settings.json` both
/// give `pre_tool_use.py` a **5 second** harness timeout, and a hook the harness kills produces
/// neither `exit 2` nor a JSON deny — Claude Code treats that as a non-blocking error and **runs
/// the tool anyway**. A 135-second in-hook wait therefore did not fail closed; it failed OPEN,
/// with a `gate_escalation_opened` entry on the chain making it look like process had happened
/// while the write sailed through underneath. kimi-code caught it (PR #114 review), and
/// `law_inject.py:39` had the invariant written down the whole time: the hook's budget must stay
/// BELOW its settings.json timeout, "or the harness wins and the guarantee is void again."
///
/// So the shape is deny-now / decide-out-of-band / retry: the write is refused immediately, a
/// human decides whenever, and the member re-issues the write, which claims the approval in one
/// fast round trip. This window is how long that retry stays possible. Long enough to be humane,
/// short enough that an approval cannot be ridden days later.
pub const APPROVAL_CLAIM_WINDOW_SECS: u64 = 600;

/// Terminal entries older than this are dropped on the next `open`. Housekeeping only — it can
/// never change an answer, because a missing id and an expired id are already the same verdict.
pub const REAP_KEEP_SECS: u64 = 3_600;

/// Upper bound on the store, so a member cannot exhaust memory by opening escalations in a loop.
/// Reaching it is itself refused rather than silently evicting — evicting the oldest would let a
/// flood erase a pending decision, which is a way to turn a deny into a nothing.
pub const MAX_PENDING: usize = 64;

#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Pending,
    Approved,
    Denied,
    /// Deadline passed with no decision, OR the id is unknown to this store. Both are denies.
    Expired,
}

impl Status {
    /// The single place that answers "may the write proceed?". Only one variant says yes, and it
    /// says yes by name rather than by not being a known failure.
    pub fn permits_write(self) -> bool {
        matches!(self, Status::Approved)
    }
}

/// How a decision reached us. Not cosmetic: these carry different evidential weight and the
/// record must keep them apart.
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Channel {
    /// Authenticated operator HTTP session (LCT challenge/response). Strong.
    OperatorSession,
    /// Local CLI, authenticated only by filesystem access to HESTIA_HOME. Same-UID as every
    /// member on this box, so this is convenience, not proof.
    LocalCli,
    /// A NOT-SAME peer member decided it, through the same independence rules the appeal
    /// arbiter uses. At A1 this is not an enforced boundary — the peer shares this UID — so it
    /// is recorded SECOND-PARTY REVIEW, not a stronger permission. What it buys is that the
    /// approval was looked at by something that is not the asker, and the record says how
    /// different that something is.
    PeerMember,
}

#[derive(Clone, Debug, serde::Serialize)]
pub struct Escalation {
    pub id: String,
    /// The member asking. Recorded as claimed — `plugin_id` is caller-asserted (HST-005), and
    /// this field inherits that weakness rather than laundering it.
    pub plugin_id: String,
    pub role: String,
    pub tool_name: String,
    /// Which governance file the write would reach.
    pub marker: String,
    pub opened_at: u64,
    pub expires_at: u64,
    status: Status,
    /// When a human actually decided. `None` while Pending.
    ///
    /// Recorded because `decided_by` and `decided_via` without a timestamp cannot answer the
    /// one question an attribution record is asked after the fact: how long the approval sat
    /// before it was spent. kimi-code, PR #114 review — `secs_from_decision_to_use` was
    /// computed from `opened_at`, so a decision at T+119 was reported as ~2 minutes of use-lag
    /// that never happened. A mislabeled duration in a record whose point is attribution is
    /// what a future argument gets built on.
    pub decided_at: Option<u64>,
    pub decided_by: Option<String>,
    pub decided_via: Option<Channel>,
    pub reason: Option<String>,
    /// The ROLE the decider was filling, not just which agent it was.
    ///
    /// dp, 2026-07-30: "at some point we need to stop putting 'human' on a pedestal. and focus
    /// on the role. sovereign is a role. who or what fills it is secondary." So the record
    /// carries role@agent: `decided_role` is the half that says by what authority, and
    /// `decided_by` is the half that says who filled it. Either alone lets the surface lie.
    pub decided_role: Option<String>,
    /// How different the decider was from the asker, when a peer decided. `None` for the
    /// sovereign channels, where the question does not arise.
    pub independence: Option<crate::arbiter::Independence>,
    /// When the approval was spent. An approval is **single use**: it authorises the one write
    /// that was refused, not a standing permit on the governance surface. Without this, one
    /// approval would license every subsequent edit until the daemon restarted.
    pub consumed_at: Option<u64>,
}

impl Escalation {
    /// Status as of `now`. A pending escalation past its deadline reads `Expired` WITHOUT the
    /// store having been touched — so the answer cannot depend on whether a sweep happened to
    /// run, and a stalled daemon cannot leave a stale `Pending` looking live.
    pub fn status_at(&self, now: u64) -> Status {
        match self.status {
            Status::Pending if now >= self.expires_at => Status::Expired,
            other => other,
        }
    }

    /// The stored value, ignoring the clock. For the record only — callers deciding whether a
    /// write may proceed must use `status_at`.
    pub fn stored_status(&self) -> Status {
        self.status
    }

    pub fn secs_remaining(&self, now: u64) -> u64 {
        self.expires_at.saturating_sub(now)
    }

    /// May this approval still authorise the write it was granted for?
    ///
    /// Three conditions, all of which have to hold, and each of which is a way this could
    /// otherwise become a standing permit: it was actually approved, it has not already been
    /// spent, and the retry window has not closed.
    pub fn is_claimable(&self, now: u64) -> bool {
        self.status == Status::Approved
            && self.consumed_at.is_none()
            && now < self.decided_horizon()
    }

    /// The instant after which an approval stops being claimable.
    fn decided_horizon(&self) -> u64 {
        self.opened_at
            .saturating_add(DEFAULT_TTL_SECS)
            .saturating_add(APPROVAL_CLAIM_WINDOW_SECS)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum DecideError {
    /// No such escalation. Fail closed: the caller must treat this as a deny, never a retry.
    Unknown,
    /// Deadline already passed. The hook has by now denied, so flipping this would make the
    /// record disagree with what happened.
    Expired,
    /// Already approved or denied. Decisions are single-shot.
    AlreadyDecided(Status),
    /// No decider named. A record whose point is attribution must not carry an anonymous
    /// approval.
    AnonymousDecider,
}

impl std::fmt::Display for DecideError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DecideError::Unknown => write!(
                f,
                "no such escalation — unknown ids are denies, not retries"
            ),
            DecideError::Expired => write!(
                f,
                "escalation expired; the write was already refused, and a late approval would \
                 disagree with what happened"
            ),
            DecideError::AlreadyDecided(s) => {
                write!(f, "already decided ({s:?}); decisions are single-shot")
            }
            DecideError::AnonymousDecider => write!(
                f,
                "a decision must name its decider — an anonymous approval in an attribution \
                 record is worse than no record"
            ),
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum OpenError {
    /// Too many pending. Refused rather than evicting — see MAX_PENDING.
    TooManyPending(usize),
    /// A required field was empty. An escalation nobody can attribute or act on is not a
    /// decision request, it is noise with a deadline.
    MissingField(&'static str),
}

impl std::fmt::Display for OpenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OpenError::TooManyPending(n) => write!(
                f,
                "{n} escalations already pending (max {MAX_PENDING}) — refusing rather than \
                 evicting, because evicting the oldest lets a flood erase a pending decision"
            ),
            OpenError::MissingField(name) => {
                write!(f, "'{name}' is required — an unattributable escalation is not actionable")
            }
        }
    }
}

#[derive(Default)]
pub struct EscalationStore {
    by_id: HashMap<String, Escalation>,
    /// Monotonic, so two escalations opened in the same second still differ.
    seq: u64,
}

pub fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

impl EscalationStore {
    pub fn open(
        &mut self,
        plugin_id: &str,
        role: &str,
        tool_name: &str,
        marker: &str,
        now: u64,
        ttl_secs: u64,
    ) -> Result<Escalation, OpenError> {
        // Housekeeping first. Without it terminal entries accumulate without bound — a member
        // may sustain MAX_PENDING opens per window, and both the live count below and
        // `pending()` are O(n) scans, so every escalation would get slower with history.
        // kimi-code, PR #114 review: `reap` was called only from its own test. Safe to call
        // here because `reaping_can_never_change_an_answer` proves it cannot flip a verdict.
        self.reap(now, REAP_KEEP_SECS);

        let plugin_id = plugin_id.trim();
        let tool_name = tool_name.trim();
        let marker = marker.trim();
        if plugin_id.is_empty() {
            return Err(OpenError::MissingField("plugin_id"));
        }
        if tool_name.is_empty() {
            return Err(OpenError::MissingField("tool_name"));
        }
        if marker.is_empty() {
            return Err(OpenError::MissingField("marker"));
        }

        // Count what is ACTUALLY pending as of now, not what is stored as Pending — otherwise
        // expired-but-unreaped entries would fill the quota and a member could be locked out of
        // escalating by its own earlier timeouts.
        let live = self
            .by_id
            .values()
            .filter(|e| e.status_at(now) == Status::Pending)
            .count();
        if live >= MAX_PENDING {
            return Err(OpenError::TooManyPending(live));
        }

        self.seq += 1;
        let mut h = Sha256::new();
        h.update(b"hestia:gate-escalation:");
        h.update(self.seq.to_be_bytes());
        h.update(now.to_be_bytes());
        h.update(plugin_id.as_bytes());
        h.update(marker.as_bytes());
        let id: String = h.finalize()[..8].iter().map(|b| format!("{b:02x}")).collect();

        let esc = Escalation {
            id: id.clone(),
            plugin_id: plugin_id.to_string(),
            role: role.trim().to_string(),
            tool_name: tool_name.to_string(),
            marker: marker.to_string(),
            opened_at: now,
            expires_at: now.saturating_add(ttl_secs.max(1)),
            status: Status::Pending,
            decided_at: None,
            decided_by: None,
            decided_via: None,
            reason: None,
            decided_role: None,
            independence: None,
            consumed_at: None,
        };
        self.by_id.insert(id, esc.clone());
        Ok(esc)
    }

    /// Spend an existing approval for this exact (member, governance file), if one is live.
    ///
    /// This is the retry half of deny-now / decide-out-of-band / retry. The hook calls it on
    /// every governance write; almost always there is nothing to claim and the write is refused,
    /// which is one fast round trip well inside the harness's 5-second budget.
    ///
    /// Matching is on **plugin_id AND marker**, not on plugin_id alone: approving a change to
    /// the gate must not silently authorise a change to `witness.py`. Both are caller-asserted
    /// (HST-005) and that weakness is inherited, not laundered — but at A1 the member could
    /// approve itself outright, so a member lying about `marker` to spend its own approval on a
    /// different file gains nothing it did not already have.
    ///
    /// Consumption is the whole point: an approval authorises the one write that was refused,
    /// not a standing permit.
    pub fn claim(&mut self, plugin_id: &str, marker: &str, now: u64) -> Option<Escalation> {
        let plugin_id = plugin_id.trim();
        let marker = marker.trim();
        if plugin_id.is_empty() || marker.is_empty() {
            return None;
        }
        // Oldest claimable first, so a member that somehow holds two approvals spends the one
        // closest to expiring rather than stranding it.
        let mut ids: Vec<(u64, String)> = self
            .by_id
            .values()
            .filter(|e| e.plugin_id == plugin_id && e.marker == marker && e.is_claimable(now))
            .map(|e| (e.opened_at, e.id.clone()))
            .collect();
        ids.sort();
        let id = ids.first()?.1.clone();
        let esc = self.by_id.get_mut(&id)?;
        esc.consumed_at = Some(now);
        Some(esc.clone())
    }

    /// The poll the hook calls. An unknown id answers `Expired` rather than an error, because
    /// the caller's only safe reading of "I do not know" is "no".
    pub fn status_of(&self, id: &str, now: u64) -> Status {
        self.by_id
            .get(id)
            .map(|e| e.status_at(now))
            .unwrap_or(Status::Expired)
    }

    pub fn get(&self, id: &str) -> Option<&Escalation> {
        self.by_id.get(id)
    }

    pub fn decide(
        &mut self,
        id: &str,
        approve: bool,
        decided_by: &str,
        decided_role: &str,
        via: Channel,
        independence: Option<crate::arbiter::Independence>,
        reason: Option<&str>,
        now: u64,
    ) -> Result<Escalation, DecideError> {
        // An anonymous approval in a record whose entire purpose is attribution is worse than
        // no record. Latent today (both channels hardcode a decider) and it must not become
        // reachable when the CLI lands. kimi-code, PR #114 review.
        if decided_by.trim().is_empty() {
            return Err(DecideError::AnonymousDecider);
        }
        let esc = self.by_id.get_mut(id).ok_or(DecideError::Unknown)?;
        match esc.status_at(now) {
            Status::Expired => return Err(DecideError::Expired),
            s @ (Status::Approved | Status::Denied) => {
                return Err(DecideError::AlreadyDecided(s))
            }
            Status::Pending => {}
        }
        esc.status = if approve { Status::Approved } else { Status::Denied };
        esc.decided_at = Some(now);
        esc.decided_by = Some(decided_by.trim().to_string());
        esc.decided_role = Some(decided_role.trim().to_string()).filter(|r| !r.is_empty());
        esc.decided_via = Some(via);
        esc.independence = independence;
        esc.reason = reason.map(|r| r.trim().to_string()).filter(|r| !r.is_empty());
        Ok(esc.clone())
    }

    /// Everything a human needs to decide, live as of `now`, oldest first so the one about to
    /// expire is at the top.
    pub fn pending(&self, now: u64) -> Vec<&Escalation> {
        let mut v: Vec<&Escalation> = self
            .by_id
            .values()
            .filter(|e| e.status_at(now) == Status::Pending)
            .collect();
        v.sort_by_key(|e| (e.opened_at, e.id.clone()));
        v
    }

    /// Drop entries that have been terminal for a while. Purely housekeeping: it can never
    /// change an answer, because `status_at` already treats a missing id and an expired id the
    /// same way.
    pub fn reap(&mut self, now: u64, keep_secs: u64) -> usize {
        let before = self.by_id.len();
        self.by_id
            .retain(|_, e| e.status_at(now) == Status::Pending || now < e.expires_at + keep_secs);
        before - self.by_id.len()
    }

    pub fn len(&self) -> usize {
        self.by_id.len()
    }

    pub fn is_empty(&self) -> bool {
        self.by_id.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const T0: u64 = 1_800_000_000;

    fn store_with_one() -> (EscalationStore, String) {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "role:constellation:member", "Edit", "pre_tool_use.py", T0, 120)
            .expect("open");
        (s, e.id)
    }

    #[test]
    fn only_approved_permits_a_write() {
        // The whole gate reduces to this. If any other variant ever permits, the escalation
        // becomes a formality.
        assert!(Status::Approved.permits_write());
        for s in [Status::Pending, Status::Denied, Status::Expired] {
            assert!(!s.permits_write(), "{s:?} must not permit a governance write");
        }
    }

    #[test]
    fn unknown_id_reads_as_expired_not_as_an_error() {
        let s = EscalationStore::default();
        // Fail closed: a daemon restart drops the store, and every in-flight escalation must
        // then read as denied rather than as something the hook should keep waiting on.
        assert_eq!(s.status_of("deadbeefdeadbeef", T0), Status::Expired);
        assert!(!s.status_of("deadbeefdeadbeef", T0).permits_write());
    }

    #[test]
    fn pending_becomes_expired_on_the_clock_alone() {
        let (s, id) = store_with_one();
        assert_eq!(s.status_of(&id, T0), Status::Pending);
        assert_eq!(s.status_of(&id, T0 + 119), Status::Pending);
        // No sweep has run; the deadline alone decides. A stalled daemon cannot leave a dead
        // escalation looking live.
        assert_eq!(s.status_of(&id, T0 + 120), Status::Expired);
        assert_eq!(s.get(&id).unwrap().stored_status(), Status::Pending);
    }

    #[test]
    fn approval_after_the_deadline_is_refused() {
        let (mut s, id) = store_with_one();
        let err = s
            .decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, None, T0 + 121)
            .expect_err("late approval must be refused");
        assert_eq!(err, DecideError::Expired);
        // And it did not mutate: the record still says nobody decided.
        assert_eq!(s.status_of(&id, T0 + 121), Status::Expired);
        assert!(s.get(&id).unwrap().decided_by.is_none());
    }

    #[test]
    fn decisions_are_single_shot() {
        let (mut s, id) = store_with_one();
        s.decide(&id, false, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("not now"), T0 + 5)
            .expect("first decision");
        let err = s
            .decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, None, T0 + 6)
            .expect_err("a deny must not be upgradable to an approve");
        assert_eq!(err, DecideError::AlreadyDecided(Status::Denied));
        assert_eq!(s.status_of(&id, T0 + 6), Status::Denied);
    }

    #[test]
    fn a_decided_escalation_keeps_its_verdict_past_the_deadline() {
        // Expiry applies to UNDECIDED escalations only. An approval at T+5 must not silently
        // become a deny at T+121 — the hook may still be mid-write.
        let (mut s, id) = store_with_one();
        s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::OperatorSession, None, None, T0 + 5)
            .expect("approve");
        assert_eq!(s.status_of(&id, T0 + 5_000), Status::Approved);
    }

    #[test]
    fn the_channel_is_recorded_and_the_two_are_not_interchangeable() {
        let (mut s, id) = store_with_one();
        let e = s
            .decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, None, T0 + 1)
            .expect("approve");
        // A same-UID CLI approval and an authenticated operator session are both "approved" and
        // are NOT the same evidence. If this ever collapses to one value, the record loses the
        // only thing that distinguishes them.
        assert_eq!(e.decided_via, Some(Channel::LocalCli));
        assert_ne!(Channel::LocalCli, Channel::OperatorSession);
    }

    #[test]
    fn required_fields_are_required() {
        let mut s = EscalationStore::default();
        assert_eq!(
            s.open("", "r", "Edit", "gate.py", T0, 120).unwrap_err(),
            OpenError::MissingField("plugin_id")
        );
        assert_eq!(
            s.open("claude-code", "r", "", "gate.py", T0, 120).unwrap_err(),
            OpenError::MissingField("tool_name")
        );
        assert_eq!(
            s.open("claude-code", "r", "Edit", "   ", T0, 120).unwrap_err(),
            OpenError::MissingField("marker")
        );
    }

    #[test]
    fn a_flood_is_refused_and_expired_entries_do_not_hold_the_quota() {
        let mut s = EscalationStore::default();
        for i in 0..MAX_PENDING {
            s.open("claude-code", "r", "Edit", &format!("f{i}.py"), T0, 120)
                .expect("under the cap");
        }
        assert_eq!(
            s.open("claude-code", "r", "Edit", "one-too-many.py", T0, 120)
                .unwrap_err(),
            OpenError::TooManyPending(MAX_PENDING)
        );
        // Once they lapse, the quota frees — otherwise a member's own timeouts would lock it out
        // of ever escalating again, which is a deny with no decision behind it.
        s.open("claude-code", "r", "Edit", "later.py", T0 + 121, 120)
            .expect("expired entries must not hold the quota");
    }

    #[test]
    fn ids_are_distinct_within_the_same_second() {
        let mut s = EscalationStore::default();
        let a = s.open("claude-code", "r", "Edit", "gate.py", T0, 120).unwrap();
        let b = s.open("claude-code", "r", "Edit", "gate.py", T0, 120).unwrap();
        assert_ne!(a.id, b.id, "same member, same file, same second must still differ");
    }

    #[test]
    fn reaping_can_never_change_an_answer() {
        let (mut s, id) = store_with_one();
        let t = T0 + 10_000;
        let before = s.status_of(&id, t);
        s.reap(t, 60);
        assert_eq!(s.status_of(&id, t), before, "reap changed a verdict");
        assert_eq!(before, Status::Expired);
    }

    #[test]
    fn a_peer_decision_records_role_at_agent_and_its_independence() {
        // dp, 2026-07-30: "sovereign is a role. who or what fills it is secondary." So the
        // record must carry BOTH halves. `decided_by` alone cannot say by what authority;
        // `decided_role` alone cannot say who filled it. Either alone lets the surface lie.
        use crate::arbiter::Independence;
        let (mut s, id) = store_with_one();
        let e = s
            .decide(
                &id, true, "kimi-code", "role:constellation:reviewer",
                Channel::PeerMember, Some(Independence::CrossMember),
                Some("verified the diff"), T0 + 3,
            )
            .expect("peer approve");
        assert_eq!(e.decided_by.as_deref(), Some("kimi-code"));
        assert_eq!(e.decided_role.as_deref(), Some("role:constellation:reviewer"));
        assert_eq!(e.decided_via, Some(Channel::PeerMember));
        assert_eq!(e.independence, Some(Independence::CrossMember));
    }

    #[test]
    fn a_peer_approval_is_claimable_by_the_asker_and_still_single_use() {
        // The peer path must not be a second, weaker lane: it produces exactly the same
        // single-use, window-bounded approval the sovereign path does.
        use crate::arbiter::Independence;
        let (mut s, id) = store_with_one();
        s.decide(&id, true, "kimi-code", "role:constellation:reviewer",
                 Channel::PeerMember, Some(Independence::CrossVendor), Some("ok"), T0 + 2)
            .unwrap();
        assert!(s.claim("claude-code", "pre_tool_use.py", T0 + 3).is_some());
        assert!(
            s.claim("claude-code", "pre_tool_use.py", T0 + 4).is_none(),
            "a peer-granted approval must be spent like any other"
        );
    }

    #[test]
    fn the_sovereign_channels_record_no_independence() {
        // Independence is a question about a PEER. For the sovereign role it does not arise,
        // and answering it anyway would invent a comparison nobody made.
        let (mut s, id) = store_with_one();
        let e = s
            .decide(&id, true, "operator", "role:constellation:sovereign",
                    Channel::OperatorSession, None, Some("ok"), T0 + 1)
            .unwrap();
        assert_eq!(e.independence, None);
        assert_eq!(e.decided_role.as_deref(), Some("role:constellation:sovereign"));
    }

    #[test]
    fn an_approval_is_single_use() {
        // Otherwise one approval is a standing permit on the governance surface until the
        // daemon restarts, which is not what anybody approved.
        let (mut s, id) = store_with_one();
        s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), T0 + 5).unwrap();
        let first = s.claim("claude-code", "pre_tool_use.py", T0 + 6);
        assert!(first.is_some(), "the approval it was granted for must be claimable");
        assert_eq!(first.unwrap().consumed_at, Some(T0 + 6));
        let second = s.claim("claude-code", "pre_tool_use.py", T0 + 7);
        assert!(second.is_none(), "a spent approval must not authorise a second write");
    }

    #[test]
    fn only_an_approved_escalation_is_claimable() {
        for (approve, label) in [(false, "denied")] {
            let (mut s, id) = store_with_one();
            s.decide(&id, approve, "dp", "role:constellation:sovereign", Channel::LocalCli, None, None, T0 + 1).unwrap();
            assert!(
                s.claim("claude-code", "pre_tool_use.py", T0 + 2).is_none(),
                "{label} must not be claimable"
            );
        }
        // Undecided, and lapsed-undecided, likewise.
        let (mut s, _) = store_with_one();
        assert!(s.claim("claude-code", "pre_tool_use.py", T0 + 2).is_none(), "pending");
        assert!(s.claim("claude-code", "pre_tool_use.py", T0 + 500).is_none(), "expired");
    }

    #[test]
    fn an_approval_stops_being_claimable_once_the_retry_window_closes() {
        let (mut s, id) = store_with_one();
        s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), T0 + 5).unwrap();
        let horizon = T0 + DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS;
        assert!(s.claim("claude-code", "pre_tool_use.py", horizon - 1).is_some());

        let (mut s2, id2) = store_with_one();
        s2.decide(&id2, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), T0 + 5).unwrap();
        // A day later must not still be rideable.
        assert!(s2.claim("claude-code", "pre_tool_use.py", horizon).is_none());
        assert!(s2.claim("claude-code", "pre_tool_use.py", T0 + 86_400).is_none());
    }

    #[test]
    fn a_claim_matches_on_member_and_file_together() {
        // Approving a change to the gate must not silently authorise a change to witness.py,
        // nor let a different member spend someone else's approval.
        let (mut s, id) = store_with_one();
        s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), T0 + 1).unwrap();
        assert!(s.claim("claude-code", "witness.py", T0 + 2).is_none(), "wrong file");
        assert!(s.claim("kimi-code", "pre_tool_use.py", T0 + 2).is_none(), "wrong member");
        assert!(s.claim("", "pre_tool_use.py", T0 + 2).is_none(), "empty member");
        assert!(s.claim("claude-code", "", T0 + 2).is_none(), "empty file");
        assert!(s.claim("claude-code", "pre_tool_use.py", T0 + 2).is_some(), "the exact pair");
    }

    #[test]
    fn a_decision_must_name_its_decider() {
        let (mut s, id) = store_with_one();
        assert_eq!(
            s.decide(&id, true, "   ", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), T0 + 1).unwrap_err(),
            DecideError::AnonymousDecider
        );
        // And it did not mutate on the way out.
        assert_eq!(s.status_of(&id, T0 + 1), Status::Pending);
    }

    #[test]
    fn a_decision_records_when_it_was_made_not_when_it_was_asked_for() {
        // The record carried `secs_from_decision_to_use` computed from `opened_at`, which is a
        // different duration wearing the decision's name. Approve at T0+119 and spend at T0+120:
        // the honest answer is 1 second, and the old arithmetic said 120.
        let (mut s, id) = store_with_one();
        let decided = s
            .decide(&id, true, "dp", Channel::OperatorSession, Some("legit gate edit"), T0 + 119)
            .expect("decide");
        assert_eq!(decided.decided_at, Some(T0 + 119));
        assert_ne!(
            decided.decided_at,
            Some(decided.opened_at),
            "a decision that lands 119s after the ask must not be recorded at the ask"
        );

        let now = T0 + 120;
        let claimed = s.claim("claude-code", "pre_tool_use.py", now).expect("claim");
        let from_decision = now - claimed.decided_at.expect("a claimed approval was decided");
        let from_open = now - claimed.opened_at;
        assert_eq!(from_decision, 1, "decision -> use");
        assert_eq!(from_open, 120, "open -> use");
        assert_ne!(
            from_decision, from_open,
            "if these ever coincide the test cannot tell the mislabeled field from the fixed one"
        );
    }

    #[test]
    fn a_pending_escalation_has_no_decision_time() {
        // The absent case has to stay absent: a default of `opened_at` here would silently
        // reintroduce the same wrong number through the back door.
        let (s, id) = store_with_one();
        assert_eq!(s.get(&id).unwrap().decided_at, None);
    }

    #[test]
    fn open_reaps_so_terminal_entries_cannot_accumulate_without_bound() {
        let mut s = EscalationStore::default();
        for i in 0..10 {
            s.open("claude-code", "r", "Edit", &format!("f{i}.py"), T0, 120).unwrap();
        }
        assert_eq!(s.len(), 10);
        // Long after they lapsed, one more open sweeps them.
        s.open("claude-code", "r", "Edit", "later.py", T0 + DEFAULT_TTL_SECS + REAP_KEEP_SECS + 1, 120)
            .unwrap();
        assert_eq!(s.len(), 1, "reap must run on open, not only in its own test");
    }

    #[test]
    fn pending_lists_oldest_first_and_hides_the_expired() {
        let mut s = EscalationStore::default();
        let old = s.open("claude-code", "r", "Edit", "a.py", T0, 120).unwrap();
        let new = s.open("kimi-code", "r", "Write", "b.py", T0 + 30, 120).unwrap();
        let ids: Vec<&str> = s.pending(T0 + 31).iter().map(|e| e.id.as_str()).collect();
        assert_eq!(ids, vec![old.id.as_str(), new.id.as_str()]);
        // `old` lapses first; the list must stop offering it as decidable.
        let ids: Vec<&str> = s.pending(T0 + 121).iter().map(|e| e.id.as_str()).collect();
        assert_eq!(ids, vec![new.id.as_str()]);
    }
}

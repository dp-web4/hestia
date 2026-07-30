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
//! 2. **Self-approval becomes a loud, separately-typed act.** Running the approve command is a
//!    tool call, so it passes the gate, and the gate treats an approve of one's own pending
//!    escalation as `gate_self_approval` at escalate severity. The evasion is not blocked; it is
//!    made expensive to hide.
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
//! * **Late decision.** `decide` REFUSES once expired. Otherwise an operator approving at T+150s
//!   would flip a verdict the hook already acted on at T+120s, and the record would disagree
//!   with what happened.

use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};

/// How long a pending escalation lives. dp: "deny on timeout of a couple minutes."
pub const DEFAULT_TTL_SECS: u64 = 120;

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
    pub decided_by: Option<String>,
    pub decided_via: Option<Channel>,
    pub reason: Option<String>,
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
            decided_by: None,
            decided_via: None,
            reason: None,
        };
        self.by_id.insert(id, esc.clone());
        Ok(esc)
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
        via: Channel,
        reason: Option<&str>,
        now: u64,
    ) -> Result<Escalation, DecideError> {
        let esc = self.by_id.get_mut(id).ok_or(DecideError::Unknown)?;
        match esc.status_at(now) {
            Status::Expired => return Err(DecideError::Expired),
            s @ (Status::Approved | Status::Denied) => {
                return Err(DecideError::AlreadyDecided(s))
            }
            Status::Pending => {}
        }
        esc.status = if approve { Status::Approved } else { Status::Denied };
        esc.decided_by = Some(decided_by.trim().to_string());
        esc.decided_via = Some(via);
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
            .decide(&id, true, "dp", Channel::LocalCli, None, T0 + 121)
            .expect_err("late approval must be refused");
        assert_eq!(err, DecideError::Expired);
        // And it did not mutate: the record still says nobody decided.
        assert_eq!(s.status_of(&id, T0 + 121), Status::Expired);
        assert!(s.get(&id).unwrap().decided_by.is_none());
    }

    #[test]
    fn decisions_are_single_shot() {
        let (mut s, id) = store_with_one();
        s.decide(&id, false, "dp", Channel::LocalCli, Some("not now"), T0 + 5)
            .expect("first decision");
        let err = s
            .decide(&id, true, "dp", Channel::LocalCli, None, T0 + 6)
            .expect_err("a deny must not be upgradable to an approve");
        assert_eq!(err, DecideError::AlreadyDecided(Status::Denied));
        assert_eq!(s.status_of(&id, T0 + 6), Status::Denied);
    }

    #[test]
    fn a_decided_escalation_keeps_its_verdict_past_the_deadline() {
        // Expiry applies to UNDECIDED escalations only. An approval at T+5 must not silently
        // become a deny at T+121 — the hook may still be mid-write.
        let (mut s, id) = store_with_one();
        s.decide(&id, true, "dp", Channel::OperatorSession, None, T0 + 5)
            .expect("approve");
        assert_eq!(s.status_of(&id, T0 + 5_000), Status::Approved);
    }

    #[test]
    fn the_channel_is_recorded_and_the_two_are_not_interchangeable() {
        let (mut s, id) = store_with_one();
        let e = s
            .decide(&id, true, "dp", Channel::LocalCli, None, T0 + 1)
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

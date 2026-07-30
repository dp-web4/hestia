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

/// How long an APPROVAL stays spendable after the human decided it.
///
/// kimi-code, reviewing #114: *"You'd want a decision TTL on approved entries so a stale approval
/// can't be ridden days later — today an approval is valid until daemon restart."* Correct, and
/// the time bound is the weaker half of the answer. The strong half is [`Status::Consumed`]: an
/// approval authorises exactly ONE write and is spent by the write that uses it. Bounding by USE
/// is what stops a grant becoming a standing permission; bounding by TIME only stops the window
/// staying open while nobody looks. Both, because they fail differently.
///
/// Sized for a human loop, not a machine one: the member is denied, tells the operator, the
/// operator decides, the member retries. Minutes, not hours.
pub const GRANT_TTL_SECS: u64 = 300;

/// How long a terminal entry is kept for the record after every clock on it has run out. Strictly
/// greater than [`GRANT_TTL_SECS`] so housekeeping can never reach a grant that is still live.
pub const REAP_KEEP_SECS: u64 = GRANT_TTL_SECS + 60;

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
    /// Approved, and the write it authorised has been made. Terminal, and NOT re-spendable: one
    /// approval buys one write. Distinct from `Denied` because the record must still say a human
    /// said yes — what changed is that the grant is gone, not that it never existed.
    Consumed,
}

impl Status {
    /// Whether the RECORD says a human approved. Not the same question as "may this write proceed
    /// now" — see [`EscalationStore::claim`], which is the only thing that may answer that one.
    /// A `Consumed` grant was approved and is still spent; keeping those apart is the point.
    pub fn permits_write(self) -> bool {
        matches!(self, Status::Approved)
    }

    /// Terminal states keep their value past the deadline; only `Pending` is the clock's to change.
    fn is_decided(self) -> bool {
        matches!(self, Status::Approved | Status::Denied | Status::Consumed)
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
    /// When the human decided. The grant window is measured from HERE, not from `opened_at`: an
    /// approval at second 119 must not be born already stale.
    pub decided_at: Option<u64>,
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

    /// Whether [`EscalationStore::claim`] would spend this one right now.
    ///
    /// Deliberately NOT folded into `status_at`. `status_at` answers "what does the record say
    /// happened", which is a fact and does not decay; this answers "may a write proceed on it",
    /// which does. An approval that nobody spent stays `Approved` in the record forever and stops
    /// being claimable in minutes, and those are two different sentences.
    pub fn claimable_at(&self, now: u64) -> bool {
        self.status_at(now) == Status::Approved
            && self
                .decided_at
                .is_some_and(|d| now < d.saturating_add(GRANT_TTL_SECS))
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
    /// Nobody named themselves. Refused rather than recorded as `Some("")` — attribution is the
    /// entire product of this record, and an anonymous approval in it is worse than no record,
    /// because it reads like one. (kimi-code, #114 review, finding 3.)
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
                "'decided_by' is required — an approval nobody signed is the one thing this \
                 record exists to prevent"
            ),
        }
    }
}

/// Why a grant could not be spent. Every variant is a DENY; they are kept apart so the member is
/// told which door to knock on, not so any of them opens one.
#[derive(Debug, PartialEq, Eq)]
pub enum ClaimError {
    /// No approval on file for this member and this file. The ordinary case: nobody has decided
    /// yet, or the answer was no.
    NoGrant,
    /// A human approved, and the spendable window closed before anyone used it. Distinguished
    /// from `NoGrant` because the remedy differs: ask again, and this time act on it.
    Stale { decided_at: u64 },
    /// The approval was already spent by an earlier write. One approval, one write.
    AlreadySpent { decided_at: u64 },
}

impl std::fmt::Display for ClaimError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ClaimError::NoGrant => write!(f, "no approved escalation for this member and file"),
            ClaimError::Stale { decided_at } => write!(
                f,
                "an approval exists (decided at {decided_at}) but its {GRANT_TTL_SECS}s window \
                 has closed — ask again"
            ),
            ClaimError::AlreadySpent { decided_at } => write!(
                f,
                "that approval (decided at {decided_at}) was already spent — one approval \
                 authorises one write"
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

        // Housekeeping before the O(n) scans below, so the cost of an escalation stops growing
        // with the history of every escalation before it. (kimi-code, #114 review, finding 1:
        // `reap` was reachable only from its own test.)
        self.reap(now, REAP_KEEP_SECS);

        // Same member, same file, already waiting? Hand back the SAME request rather than minting
        // a second one. Under the deny-now/retry protocol a refused member retries, and without
        // this the operator's queue fills with duplicates of one question while MAX_PENDING
        // counts down toward locking that member out of asking at all.
        if let Some(live) = self
            .by_id
            .values()
            .find(|e| e.status_at(now) == Status::Pending && e.plugin_id == plugin_id && e.marker == marker)
        {
            return Ok(live.clone());
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
            decided_at: None,
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
        let who = decided_by.trim();
        if who.is_empty() {
            return Err(DecideError::AnonymousDecider);
        }
        let esc = self.by_id.get_mut(id).ok_or(DecideError::Unknown)?;
        match esc.status_at(now) {
            Status::Expired => return Err(DecideError::Expired),
            s @ (Status::Approved | Status::Denied | Status::Consumed) => {
                return Err(DecideError::AlreadyDecided(s))
            }
            Status::Pending => {}
        }
        esc.status = if approve { Status::Approved } else { Status::Denied };
        esc.decided_by = Some(who.to_string());
        esc.decided_via = Some(via);
        esc.decided_at = Some(now);
        esc.reason = reason.map(|r| r.trim().to_string()).filter(|r| !r.is_empty());
        Ok(esc.clone())
    }

    /// Spend an approval, if this member has one for this file. **The only thing in the system
    /// that may permit a governance write**, and it does so at most once per approval.
    ///
    /// Split out from `poll` because the hook cannot afford to WAIT for a decision — a
    /// PreToolUse hook killed by its harness timeout does not deny, it lets the call through
    /// (measured on Claude Code 2.1.220, not inferred). So the hook denies immediately and the
    /// member retries after a human decides; this is the fast, single-round-trip question that
    /// retry asks.
    ///
    /// Matching is on `(plugin_id, marker)`. `plugin_id` is caller-asserted (HST-005) and this
    /// inherits that weakness — it is not a barrier against a member claiming another's grant. It
    /// is what stops an approval for one file being spent on a different one by accident, which
    /// is the failure that actually happens.
    pub fn claim(
        &mut self,
        plugin_id: &str,
        marker: &str,
        now: u64,
    ) -> Result<Escalation, ClaimError> {
        let plugin_id = plugin_id.trim();
        let marker = marker.trim();

        let mine = |e: &&mut Escalation| e.plugin_id == plugin_id && e.marker == marker;

        // Newest decision first: if a member asked twice and both were approved, the one the
        // operator most recently said yes to is the one they meant.
        let mut candidates: Vec<&mut Escalation> =
            self.by_id.values_mut().filter(|e| mine(&e)).collect();
        candidates.sort_by_key(|e| std::cmp::Reverse(e.decided_at.unwrap_or(0)));

        let mut near_miss: Option<ClaimError> = None;
        for esc in candidates {
            match esc.status_at(now) {
                Status::Approved => {
                    if esc.claimable_at(now) {
                        esc.status = Status::Consumed;
                        return Ok(esc.clone());
                    }
                    near_miss.get_or_insert(ClaimError::Stale {
                        decided_at: esc.decided_at.unwrap_or(0),
                    });
                }
                Status::Consumed => {
                    near_miss.get_or_insert(ClaimError::AlreadySpent {
                        decided_at: esc.decided_at.unwrap_or(0),
                    });
                }
                _ => {}
            }
        }
        Err(near_miss.unwrap_or(ClaimError::NoGrant))
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

    /// Drop entries that have been terminal for a while, and can never change an answer while
    /// doing it.
    ///
    /// That property was free before grants existed — `status_at` already reads a missing id and
    /// an expired id identically, so forgetting a lapsed escalation changed nothing. It is NOT
    /// free now: an approval decided at second 119 outlives its escalation's own deadline by the
    /// whole grant window, and reaping on `expires_at` alone would delete a live approval and
    /// report it as `NoGrant`. Fail-closed, and still a bug — a human said yes and the machine
    /// forgot. So the horizon is the later of the two clocks.
    pub fn reap(&mut self, now: u64, keep_secs: u64) -> usize {
        let before = self.by_id.len();
        self.by_id.retain(|_, e| {
            if e.status_at(now) == Status::Pending {
                return true;
            }
            let grant_until = e
                .decided_at
                .map(|d| d.saturating_add(GRANT_TTL_SECS))
                .unwrap_or(0);
            now < e.expires_at.max(grant_until).saturating_add(keep_secs)
        });
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
        let a = s.open("claude-code", "r", "Edit", "a.py", T0, 120).unwrap();
        let b = s.open("claude-code", "r", "Edit", "b.py", T0, 120).unwrap();
        assert_ne!(a.id, b.id, "two different files, same second, must still differ");
    }

    #[test]
    fn re_asking_for_the_same_file_returns_the_same_pending_request() {
        // Under deny-now/retry a refused member retries. Minting a new id per retry would fill
        // the operator's queue with duplicates of one question and burn MAX_PENDING until the
        // member could no longer ask at all — a lockout with no decision behind it.
        let mut s = EscalationStore::default();
        let a = s.open("claude-code", "r", "Edit", "gate.py", T0, 120).unwrap();
        let b = s.open("claude-code", "r", "Write", "gate.py", T0 + 3, 120).unwrap();
        assert_eq!(a.id, b.id);
        assert_eq!(s.pending(T0 + 3).len(), 1);
        // A DIFFERENT member asking about the same file is a different question.
        let c = s.open("kimi-code", "r", "Edit", "gate.py", T0 + 3, 120).unwrap();
        assert_ne!(a.id, c.id);
    }

    #[test]
    fn a_retry_loop_cannot_exhaust_the_quota_on_one_question() {
        let mut s = EscalationStore::default();
        for i in 0..500 {
            s.open("claude-code", "r", "Edit", "gate.py", T0 + i % 60, 120)
                .expect("a retry of the same question must never be refused for flooding");
        }
        assert_eq!(s.len(), 1);
    }

    // ---- the grant: one approval buys one write, and not forever ----

    fn approved(marker: &str, at: u64) -> (EscalationStore, String) {
        let mut s = EscalationStore::default();
        let e = s.open("claude-code", "r", "Edit", marker, T0, 120).unwrap();
        s.decide(&e.id, true, "dp", Channel::OperatorSession, None, at)
            .expect("approve");
        (s, e.id)
    }

    #[test]
    fn an_approval_is_spent_by_the_write_that_uses_it() {
        let (mut s, id) = approved("gate.py", T0 + 5);
        let got = s.claim("claude-code", "gate.py", T0 + 6).expect("first claim");
        assert_eq!(got.id, id);
        // The whole point of Consumed. A second write must not ride the first one's approval.
        assert_eq!(
            s.claim("claude-code", "gate.py", T0 + 7).unwrap_err(),
            ClaimError::AlreadySpent { decided_at: T0 + 5 }
        );
        assert_eq!(s.status_of(&id, T0 + 7), Status::Consumed);
        assert!(!Status::Consumed.permits_write());
    }

    #[test]
    fn an_unspent_approval_goes_stale_but_the_record_still_says_yes() {
        let (mut s, id) = approved("gate.py", T0 + 5);
        assert_eq!(
            s.claim("claude-code", "gate.py", T0 + 5 + GRANT_TTL_SECS)
                .unwrap_err(),
            ClaimError::Stale { decided_at: T0 + 5 }
        );
        // "A human approved this" is a fact and does not decay; "a write may proceed" does.
        assert_eq!(s.status_of(&id, T0 + 100_000), Status::Approved);
        assert_eq!(s.get(&id).unwrap().decided_by.as_deref(), Some("dp"));
    }

    #[test]
    fn the_grant_window_runs_from_the_decision_not_from_the_open() {
        // Approved at second 119 of a 120s escalation. If the window were measured from
        // `opened_at` this grant would be born already dead.
        let (mut s, _) = approved("gate.py", T0 + 119);
        assert!(s.claim("claude-code", "gate.py", T0 + 121).is_ok());
    }

    #[test]
    fn a_grant_cannot_be_spent_on_a_file_it_was_not_for() {
        let (mut s, _) = approved("gate.py", T0 + 5);
        assert_eq!(
            s.claim("claude-code", "witness.py", T0 + 6).unwrap_err(),
            ClaimError::NoGrant
        );
        // ...and the grant it declined to spend is still there for its own file.
        assert!(s.claim("claude-code", "gate.py", T0 + 6).is_ok());
    }

    #[test]
    fn pending_and_denied_and_expired_all_yield_no_grant() {
        let mut s = EscalationStore::default();
        let p = s.open("claude-code", "r", "Edit", "p.py", T0, 120).unwrap();
        let d = s.open("claude-code", "r", "Edit", "d.py", T0, 120).unwrap();
        s.decide(&d.id, false, "dp", Channel::LocalCli, Some("no"), T0 + 1)
            .unwrap();
        assert_eq!(s.claim("claude-code", "p.py", T0 + 1).unwrap_err(), ClaimError::NoGrant);
        assert_eq!(s.claim("claude-code", "d.py", T0 + 2).unwrap_err(), ClaimError::NoGrant);
        // p lapses undecided.
        assert_eq!(s.claim("claude-code", "p.py", T0 + 200).unwrap_err(), ClaimError::NoGrant);
        assert_eq!(s.status_of(&p.id, T0 + 200), Status::Expired);
    }

    #[test]
    fn claiming_is_the_only_thing_that_permits_and_it_permits_once_per_approval() {
        // Two approvals for the same file buy two writes — no more, no fewer. The count of
        // writes that may proceed is exactly the count of times a human said yes.
        let mut s = EscalationStore::default();
        for i in 0..2u64 {
            let e = s
                .open("claude-code", "r", "Edit", "gate.py", T0 + i * 200, 120)
                .unwrap();
            s.decide(&e.id, true, "dp", Channel::OperatorSession, None, T0 + i * 200 + 1)
                .unwrap();
        }
        let t = T0 + 210;
        assert!(s.claim("claude-code", "gate.py", t).is_ok());
        assert!(s.claim("claude-code", "gate.py", t).is_ok());
        assert!(s.claim("claude-code", "gate.py", t).is_err(), "a third write had no third yes");
    }

    #[test]
    fn an_anonymous_approval_is_refused() {
        // The record exists to say WHO. Storing Some("") would satisfy the type and destroy the
        // product. (kimi-code, #114 review, finding 3.)
        let (mut s, id) = store_with_one();
        assert_eq!(
            s.decide(&id, true, "   ", Channel::LocalCli, None, T0 + 1)
                .unwrap_err(),
            DecideError::AnonymousDecider
        );
        assert_eq!(s.status_of(&id, T0 + 1), Status::Pending, "a refused decision must not mutate");
    }

    #[test]
    fn housekeeping_cannot_delete_a_live_grant() {
        // reap() moved onto the hot path (finding 1). Its "can never change an answer" property
        // was free before grants existed and is not free now: this approval outlives its own
        // escalation deadline by the whole grant window.
        let (mut s, _) = approved("gate.py", T0 + 119);
        let t = T0 + 121;
        s.reap(t, REAP_KEEP_SECS);
        assert!(
            s.claim("claude-code", "gate.py", t).is_ok(),
            "reap deleted an approval a human had granted"
        );
    }

    #[test]
    fn the_reap_horizon_clears_the_grant_window() {
        // The guard behind the test above, stated as the invariant rather than as one sample.
        assert!(
            REAP_KEEP_SECS > GRANT_TTL_SECS,
            "housekeeping must not be able to reach a spendable grant"
        );
    }

    #[test]
    fn opening_reaps_so_the_store_does_not_grow_without_bound() {
        let mut s = EscalationStore::default();
        for i in 0..60u64 {
            s.open("claude-code", "r", "Edit", &format!("f{i}.py"), T0 + i, 120)
                .unwrap();
        }
        assert_eq!(s.len(), 60);
        // Long after every clock on them has run out, one more open clears the lot.
        s.open("claude-code", "r", "Edit", "new.py", T0 + 100_000, 120)
            .unwrap();
        assert_eq!(s.len(), 1, "expired entries accumulated despite reap on the open path");
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

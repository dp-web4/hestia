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
//!   the caller might mistake for "still working on it".
//!
//!   This used to add: *"a daemon restart drops the store, so every escalation in flight across a
//!   restart correctly reads as denied."* True as written, and it described a real cost as if it
//!   were a safety property. Deploying a law change REQUIRES a restart, so the act of governing
//!   destroyed the governance: on 2026-08-01 dp approved a governance write and a deploy minutes
//!   later erased the ruling — a human had decided and the system had no memory of it. Under
//!   fail-closed with one gate, that is a fleet stopped mid-approval with the approval gone.
//!
//!   The store is now REHYDRATED from the chain at startup (`rehydrate`), so a decision is
//!   durable because it was witnessed. Fail-closed is unchanged and is what makes replay safe:
//!   anything the replay cannot positively identify as a grant is not a grant, a spent approval
//!   restores spent, and a decision whose `opened` entry is outside the window is skipped rather
//!   than synthesised.
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

/// How long a pending escalation stays decidable.
///
/// It was 120s, from dp's original instruction: *"deny on timeout of a couple minutes."* That
/// number was correct for the design it was written against and is wrong for the one that
/// shipped, so it is worth being explicit about why rather than quietly changing it.
///
/// **What "a couple of minutes" was bounding.** In the first design the hook BLOCKED, waiting
/// in-process for a decision. Two minutes was a bound on *how long a member sits frozen* — a
/// generous ceiling on the cost of asking. The blocking design was removed (it failed OPEN
/// under the harness timeout; see the module header), and replaced with deny-now /
/// decide-out-of-band / retry.
///
/// **Nothing waits any more.** The write is refused immediately and stays refused. The window
/// is no longer a member sitting frozen; it is only *how long a decider has to answer before
/// the ask goes stale*. The constraint the 120s was protecting no longer exists, and keeping
/// the number preserved the digit while discarding the reason.
///
/// **And it made peer arbitration unusable.** #118 lets a NOT-SAME peer rule an escalation, and
/// a peer is ASYNCHRONOUS — another agent on another schedule, reached by a mesh notice it will
/// see when it next drains. Two minutes means it essentially never arrives in time. Measured
/// 2026-07-30: escalation `8bb08a85` was opened, kimi-code was notified over the mesh, and it
/// expired unruled. Not a failure of the peer; a window sized for someone already watching.
///
/// One hour is sized for the decider that actually exists. It costs nothing to be generous
/// here: a pending escalation permits NOTHING, so a longer window widens no permission — it
/// only widens the chance that somebody answers. What must stay tight is
/// `APPROVAL_CLAIM_WINDOW_SECS`, because that one bounds how long a GRANTED approval can be
/// ridden, and that is where a loose number would actually cost something.
pub const DEFAULT_TTL_SECS: u64 = 3600;

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
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Channel {
    /// Authenticated operator HTTP session (LCT challenge/response). Strong.
    OperatorSession,
    /// Local CLI, authenticated only by filesystem access to HESTIA_HOME. Same-UID as every
    /// member on this box, so this is convenience, not proof.
    ///
    /// NOTHING OUTSIDE TESTS CONSTRUCTS THIS. Verified crate-wide 2026-07-31 (claude-code,
    /// kimi-code): every `Channel::LocalCli` in `core/src` sits inside a `#[cfg(test)]` module.
    /// That is an absent caller, not a design property — and read `bar_met` before you supply
    /// one. `is_sovereign` counts this variant as the `sov` conjunct of `SovereignPlusPeer`,
    /// the bar reserved for the surfaces whose silent compromise ends the model. Wire up a
    /// member-reachable producer and that bar is met by two same-UID members with filesystem
    /// access: the two-CHANNEL requirement becomes one channel wearing two names, while the
    /// diff reads as plumbing. The steward's note at `bar_for` says the sovereign half being
    /// hard to reach is the intended state — those writes wait rather than proceed under a
    /// weaker bar. Making it reachable IS that policy change, and belongs in a reviewed diff
    /// that says which bar it is lowering.
    LocalCli,
    /// A NOT-SAME peer member decided it, through the same independence rules the appeal
    /// arbiter uses. At A1 this is not an enforced boundary — the peer shares this UID — so it
    /// is recorded SECOND-PARTY REVIEW, not a stronger permission. What it buys is that the
    /// approval was looked at by something that is not the asker, and the record says how
    /// different that something is.
    PeerMember,
    /// THE ASKER ITSELF, refusing its own request. Not a review of any kind — the weakest
    /// thing in this enum, and deliberately its own name rather than a `PeerMember` with an
    /// absent `independence`.
    ///
    /// It can only ever accompany a DENY (`arbiter::eligibility_for` returns
    /// `SelfWithdrawal` solely in the AgainstAppellant direction), so nothing recorded under
    /// this channel ever authorised a write. `is_sovereign` excludes it and `bar_met`
    /// therefore counts it toward no bar; that is the point of a separate variant. A
    /// withdrawal filed as `PeerMember` would read, correctly in every field, as though a
    /// second party had looked at it.
    SelfWithdrawn,
}

/// A stated evidence threshold — the bar an approval must clear, RECORDED on the escalation
/// so a reader can audit "sufficient for this context" instead of inferring sufficiency from
/// the fact that a decision happened.
///
/// dp, 2026-07-30: "no single auth point is 100% trustworthy. this is why we build
/// constellations, which provide many-factor preponderance of evidence. absolute proof is
/// unachievable. but enough-for-this absolutely is achievable… sufficient evidence to pass
/// the trust bar in a specific context." And claude-code, same day: "we record the evidence
/// and we record the verdict. We do not record the bar… 'sufficient for this context' is
/// unauditable if the context's bar is never written down."
///
/// This is the bar, written down. It is not a wall: at A1 every factor is same-UID evidence,
/// so a met bar is *stated sufficiency*, not proof. What it changes is that a reader can now
/// see the criterion, the factors present, and whether they met it — the mismatch becomes a
/// recorded fact instead of an implicit one.
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Bar {
    /// One decision from a sovereign channel (operator session / operator CLI) OR a NOT-SAME
    /// peer — the everyday rule since #114 + #118.
    SingleApprover,
    /// One sovereign-channel factor AND one not-same-peer factor — for the surfaces whose
    /// silent compromise is the whole model.
    SovereignPlusPeer,
}

/// The bar a governance file's write must clear. This is POLICY, stated in one place so a
/// change is a reviewed diff — and copied onto every escalation at open, so the record
/// carries the criterion that was in force at the time, not today's.
///
/// The surfaces differ because the stakes differ: the enforcement path and the outcome
/// recorder are the two files whose silent compromise ends the model (a gate that permits
/// everything, a recorder that writes nothing), so they ask for two factors from different
/// channels; a law renderer is one approver's call. NOTE for the steward: on a box with no
/// operator session configured, the sovereign half of `SovereignPlusPeer` is hard to reach —
/// which makes enforcement-path writes wait rather than proceed under a weaker bar. That is
/// the honest state, and it is visible here rather than implicit. If that is the wrong
/// trade, this is the one line to change.
pub fn bar_for(marker: &str) -> Bar {
    if marker.contains("pre_tool_use.py")
        || marker.contains("post_tool_use.py")
        || marker.contains("witness.py")
        // The shared in-process society-safety mechanism: it decides allow/deny on every adopting
        // harness, so editing it is priced two-factor like the gate/witness. Ratified STRONG by the
        // steward (dp, 2026-08-12) when PR #372 made it LIVE — the "DECIDE before the shims adopt
        // it" the governance-class declaration named. Live clause: the name is not shadowed in the
        // matcher tuple, so this is the deciding branch for its own marker (governance_class_drift).
        || marker.contains("hestia_gate_mechanism.py")
    {
        Bar::SovereignPlusPeer
    } else {
        Bar::SingleApprover
    }
}

/// One piece of evidence present for a decision. The channels ARE the factor types
/// (claude-code, 2026-07-30: "Channel — phrase / peer / operator session — I wrote as
/// alternatives, any one of which approves. They're factor types."); `independence` is the
/// weighting, already recorded elsewhere. A bar is evaluated against the SET, never against
/// whichever answer arrived first.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct Factor {
    pub channel: Channel,
    pub by: String,
    pub role: Option<String>,
    pub independence: Option<crate::arbiter::Independence>,
    pub at: u64,
    /// A peer that looked and DISAGREED. Under invitation semantics this is evidence for
    /// review, never a veto — dp: dissent is *"surfaced to the live UI"*, and a sovereign
    /// decision stands regardless. Defaults false so every existing factor reads as
    /// concurrence, which is what it was.
    #[serde(default)]
    pub dissent: bool,
    /// The peer's stated argument, in its own words. Load-bearing for dissent — evidence
    /// with no content is not reviewable, and issue #367's live specimen (99417cc39a7acb5d,
    /// 2026-08-14) is a dissent argument silently discarded at the door while the factor
    /// recorded the opposite stance. Defaults None so every factor written before this
    /// field existed reads as "no argument recorded", which is what it was.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub argument: Option<String>,
}

impl Channel {
    /// The sovereign channels: the operator, by either door. Who fills the sovereign role is
    /// contingent; the authority is not (dp, 2026-07-30). A peer is never a sovereign factor,
    /// which is what makes sovereign-plus-peer a DIFFERENT quantity from two approvals.
    fn is_sovereign(self) -> bool {
        matches!(self, Channel::OperatorSession | Channel::LocalCli)
    }
}


#[derive(Clone, Debug, serde::Serialize)]
pub struct Escalation {
    pub id: String,
    /// Seats invited to participate in this decision. Plural: dp, on whether the
    /// invitation should reach more than one peer — *"i think yes."* One invited seat
    /// asleep is an availability accident; three that never looked is a finding, and only
    /// a list can tell those apart.
    #[serde(default)]
    pub invited_peers: Vec<String>,
    /// The subset of `invited_peers` no watcher has ever read a mailbox for, AT INVITE TIME.
    ///
    /// Kept as a subset rather than removed from the invitation: they WERE invited, the
    /// notice IS queued, and a member whose watcher starts tomorrow will read it. What this
    /// field buys is that `absent` stops accusing them in the meantime — see
    /// `peer_participation`. Restored empty for every escalation opened before the field
    /// existed, which reads as "every invitee had a reader" and is the direction that
    /// under-claims this finding rather than over-claiming it.
    #[serde(default)]
    pub invited_without_reader: Vec<String>,
    /// The member asking. Recorded as claimed — `plugin_id` is caller-asserted (HST-005), and
    /// this field inherits that weakness rather than laundering it.
    pub plugin_id: String,
    /// Whether `plugin_id` was PROVEN against a live session at open or is caller-ASSERTED
    /// (#128). This is the field `arbiter::eligibility` clause 0 reads: an asserted asker
    /// cannot be peer-cleared, because NOT-SAME would be grading a forgeable operand — and
    /// an unrecognised one as maximally independent. Fail-closed by default: rows written
    /// before this field existed carry no proof, so they deserialize as `Asserted` and only
    /// the sovereign channels (which do not rely on NOT-SAME) can still decide them.
    #[serde(default)]
    pub asker_basis: crate::arbiter::AskerBasis,
    pub role: String,
    pub tool_name: String,
    /// Which governance file the write would reach.
    pub marker: String,
    /// WHY the member says it needs this, in its own words. Caller-asserted like everything
    /// else here, and worth exactly what a self-declaration is worth — which is more than
    /// nothing, because it is the only account of intent the decider gets.
    ///
    /// dp, 2026-08-02: *"the escalations currently don't provide enough information to
    /// actually make an informed decision. that's a real issue."*
    ///
    /// It was worse than missing. The deny text has always instructed the member to *"say
    /// what you need changed and why"* — and no field existed to say it in. The operator saw
    /// an id, an (unattributed) asker, a tool name and a path fragment, then chose. Every
    /// approval in this system so far was granted on out-of-band trust, because the
    /// mechanism supplied nothing to judge. A governance surface that asks for a decision
    /// while withholding the basis is not a control; it is a prompt for a coin flip.
    /// NB: distinct from `reason` below, which is the DECIDER's rationale. Naming both
    /// `reason` would merge the asker's claim with the ruler's finding into one field, and
    /// the whole value of the record is that they are separately attributable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stated_reason: Option<String>,
    /// WHAT the act would do — the command, or a summary of the edit. Separate from
    /// `stated_reason` on purpose: intent and effect are different claims and an operator
    /// needs to compare them. **A stated reason that does not match the payload is the single
    /// most useful thing this record can surface**, and that comparison is impossible if only
    /// one of the two is stored.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stated_detail: Option<String>,
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
    /// The stated bar this escalation must clear — copied from `bar_for(marker)` at open, so
    /// the record carries the criterion in force at the time. See Bar's doc: this is what
    /// makes "sufficient for this context" auditable.
    pub bar: Bar,
    /// The evidence present, in arrival order. `decide` always appends the decider's factor;
    /// `corroborate` can add a peer factor while Pending. The bar is evaluated against this
    /// set — never against whichever answer arrived first.
    pub factors: Vec<Factor>,
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

    /// How long this approval may still be SPENT — the countdown a holder actually needs.
    ///
    /// Distinct from `secs_remaining`, which counts down the RECORD's life (`expires_at`,
    /// anchored at the open). The two diverge by construction once a decision lands, and the
    /// record outlives the claim: measured live 2026-08-08, three permits polled
    /// `secs_remaining ~1500` while ~24 minutes past their grant-anchored horizon. Reporting
    /// the record clock where a holder reads for the claim clock is how a spent permit gets
    /// published as live.
    pub fn claim_window_secs_remaining(&self, now: u64) -> u64 {
        self.decided_horizon().saturating_sub(now)
    }

    /// May this approval still authorise the write it was granted for?
    ///
    /// Four conditions, all of which have to hold, and each of which is a way this could
    /// otherwise become a standing permit or a quiet widening: it was actually approved, the
    /// stated bar is MET (an approval short of the bar is recorded but permits nothing — the
    /// mismatch is visible, never silently sufficient), it has not already been spent, and the
    /// retry window has not closed.
    pub fn is_claimable(&self, now: u64) -> bool {
        self.status == Status::Approved
            && self.bar_met()
            && self.consumed_at.is_none()
            && now < self.decided_horizon()
    }

    /// Does the evidence present meet the stated bar? Evaluated against the factor SET, so a
    /// cross-vendor peer plus a sovereign decision is a different recorded quantity than
    /// either alone — which is the whole point of having a bar at all.
    pub fn bar_met(&self) -> bool {
        match self.bar {
            Bar::SingleApprover => self
                .factors
                .iter()
                .any(|f| f.channel.is_sovereign() || f.channel == Channel::PeerMember),
            // TWO-BAR IS AN INVITATION TO PARTICIPATE, NOT A BLOCKER.
            //
            // dp, decision of record 2026-08-06: *"On sovereign decisions, two-bar is an
            // invitation to participate, not a blocker. It should have a liveness timeout
            // that's fairly short, and a mechanism to surface dissent to the live UI."*
            // And on the bar's continuing value: *"that doesn't invalidate the bar — the
            // invitation is valuable, and if acted on, so is the feedback. but it's the
            // same 'go with best we can get' — if none accept the invitation, that cannot
            // become a block."*
            //
            // WHY IT HAD TO CHANGE, measured (#219): `sovereign_plus_peer` was **0 of 66
            // bar-met, lifetime**. Decisions are single-shot, `corroborate` refused decided
            // escalations, and the median ruling landed 69s after opening — faster than a
            // mesh round trip. The peer factor could not arrive in time, ever. A bar that
            // has never once been satisfiable is not a standard; it is an outage wearing
            // a standard's clothes, and it spent this fleet's attention for weeks.
            //
            // So the sovereign conjunct decides. The peer conjunct is retained as
            // EVIDENCE, not as a gate: `peer_participation()` reports whether the invited
            // seats accepted, dissented, or were absent, and that record is what makes the
            // invitation worth issuing. The bar still shapes WHO IS ASKED and what is
            // recorded — it no longer shapes whether a sovereign may act.
            //
            // This is the same primitive as `OccupancyBasis::Provisional`, D-1's
            // `OnExceeded`, D-3's `NotSameRequirement::Preferred`, and `ReadBasis`:
            // proceed with the best available, never silently, always with the deficiency
            // on the record.
            Bar::SovereignPlusPeer => self.factors.iter().any(|f| f.channel.is_sovereign()),
        }
    }

    /// What the invited peers actually did — the half of the bar that survives.
    ///
    /// Under blocker semantics a missing peer was indistinguishable from a peer that
    /// looked and declined, because both rendered as `bar_met: false`. Under invitation
    /// semantics those are different facts about different seats, and only one of them
    /// says anything about the decision.
    ///
    /// Reported rather than enforced, and reported for MORE THAN ONE PEER — dp, on whether
    /// the invitation should go to several seats: *"i think yes."* One invited seat that
    /// happens to be asleep is an availability accident; three invited seats that all
    /// declined to look is a finding.
    pub fn peer_participation(&self) -> PeerParticipation {
        let concurred = self
            .factors
            .iter()
            .filter(|f| f.channel == Channel::PeerMember && !f.dissent)
            .count();
        let dissented = self
            .factors
            .iter()
            .filter(|f| f.channel == Channel::PeerMember && f.dissent)
            .count();
        // Invited seats whose mailbox had a reader when they were asked. `absent` is derived
        // over THESE SEATS, not over every invitee.
        //
        // Measured (`tools/invitation_deadletter_census.py`, 60k-entry window): 172 of 272
        // invitation rows went to registry ids with no `member_inbox_touch` row at all —
        // probe residue that `plugin_id`-at-connect mints and nothing ever prunes. Counted as
        // `absent`, they read exactly like a peer that saw the ask and declined, which is the
        // one distinction this function exists to make. Reported, never hidden: `invited`
        // still names everyone, and the count moves to `invited_without_reader`.
        let no_reader = self
            .invited_peers
            .iter()
            .filter(|p| self.invited_without_reader.contains(p))
            .count();
        // PER IDENTITY, never by subtracting global factor counts from a reduced population
        // (codex, PR#454 review). Two ways the subtraction lies, both toward silence:
        //
        // 1. A readerless invitee whose watcher starts later may still corroborate —
        //    `corroborate` allows it, expressly including after the decision. Its factor was
        //    subtracted from a population it had already been held out of, so one answer
        //    cancelled a DIFFERENT seat's absence: invite A (no reader) and B (reader), let A
        //    answer, and the record said `absent: 0` while B had never looked.
        // 2. A peer factor from someone who was never invited subtracted an invited seat's
        //    absence for the same reason — the arithmetic knew a count, not a name.
        //
        // Matching on `Factor::by` costs the identity join both cases were missing. `concurred`
        // and `dissented` stay global on purpose: they count the evidence that actually
        // arrived, from whoever sent it. So the four numbers do NOT sum to `invited.len()`,
        // and that is the honest shape — an uninvited corroboration is real evidence and an
        // invited silence is real absence, and neither cancels the other.
        let answered: std::collections::HashSet<&str> = self
            .factors
            .iter()
            .filter(|f| f.channel == Channel::PeerMember)
            .map(|f| f.by.as_str())
            .collect();
        let absent = self
            .invited_peers
            .iter()
            .filter(|p| !self.invited_without_reader.contains(p))
            .filter(|p| !answered.contains(p.as_str()))
            .count();
        PeerParticipation {
            invited: self.invited_peers.clone(),
            concurred,
            dissented,
            // Absent is derived, never stored: a seat that has not answered YET is not the
            // same as one that declined, and storing "absent" would freeze a moment as a
            // verdict. Post-decision participation is expressly allowed, so this number
            // can fall after a decision — which is the mechanism working, not drift.
            absent,
            invited_without_reader: no_reader,
        }
    }

    /// What a DECIDER is told about the decision they just made — built once, for every
    /// surface that can rule.
    ///
    /// WHY THIS IS A FUNCTION AND NOT A JSON LITERAL AT EACH CALL SITE, measured. #219 found
    /// that `gate_escalation_decided` recorded `bar`/`bar_met` to the CHAIN while the reply
    /// withheld both from the decider, so 63 approvals were granted by someone who could not
    /// see they had authorised nothing. The fix was applied to `tool_gate_arbitrate_escalation`
    /// — and only there. The other writer, `http::operator_gate_escalation`, kept returning
    /// `{escalation_id, status, witnessEntryHash}`.
    ///
    /// That is the surface that decides. Censused over 111,620 chain entries
    /// (private deployment census): of 210 decided escalations, **207 came through
    /// `operator_session` and 3 through `peer_member`**. So the remedy landed on the path used
    /// 3 times and skipped the path used 207 times, and every `sovereign_plus_peer` decision on
    /// the chain — 72 of them, `bar_met` true on ZERO — was reported to its decider as a bare
    /// `approved`. A control certifies only the surface it ran on.
    ///
    /// The MCP handler already carried the comment *"two places deciding what 'permits the
    /// write' means is how they come to disagree."* It was right, and they disagreed anyway,
    /// one layer up. So the answer moves here and both callers read it.
    pub fn decision_reply(&self, now: u64) -> serde_json::Value {
        let bar_met = self.bar_met();
        // THE GRANT AND THE PERMISSION ARE TWO DIFFERENT FACTS, and this field is named for
        // the second one. `granted` is the decision as a decision: approved, bar met. It is
        // fixed the moment the ruling lands and never changes again. `permits_write` asks
        // whether the write would be allowed IF RE-ISSUED NOW, which is what its name claims
        // and what `is_claimable` enforces — and that answer decays, through `consumed_at`
        // and through the claim horizon.
        //
        // This used to be `granted`, published under the name `permits_write`. Two of four
        // conjuncts, on a field with no clock, so it could not have tracked the other two at
        // any time. Nothing was lost by keeping `status` and `bar_met` beside it: a reader
        // who wants the decision fact reads those.
        let granted = self.stored_status() == Status::Approved && bar_met;
        let permits_write = self.is_claimable(now);
        let spent = self.consumed_at.is_some();
        serde_json::json!({
            "escalation_id": self.id,
            "status": self.stored_status(),
            "decided_by": self.decided_by,
            "decided_role": self.decided_role,
            "bar": self.bar,
            "bar_met": bar_met,
            // The same conjunction `is_claimable` enforces — the SAME FOUR, evaluated
            // against the same clock, not two of them re-derived without one.
            "permits_write": permits_write,
            // The decision as a decision, so nothing this field used to carry is lost.
            "granted": granted,
            // The countdown that belongs to the holder. Zero once the window has shut, which
            // is the state `secs_remaining` cannot distinguish from a live permit.
            "claim_window_secs_remaining": self.claim_window_secs_remaining(now),
            // The invitation half of the bar, reported as a RECORD (#226). Under blocker
            // semantics an absent peer showed up as `bar_met: false`; now that the sovereign
            // conjunct decides alone, nothing on any surface would say whether a peer was ever
            // asked. `invited` is empty on every escalation this daemon has ever opened —
            // `open()` sets `Vec::new()` and no production path writes it — so this currently
            // reports, truthfully, that no invitation was issued. That is the point: it must
            // read as "nobody was asked", never as "asked and they agreed".
            "peer_participation": self.peer_participation(),
            "note": if permits_write {
                "the asker must RE-ISSUE the write to claim this; approvals are single use"
            } else if granted && spent {
                "this approval has ALREADY BEEN CLAIMED. Approvals are single use: re-issuing \
                 the write will be refused, and a new escalation must be opened."
            } else if granted {
                "this approval was granted and its CLAIM WINDOW HAS CLOSED. It is recorded as \
                 approved and it authorises nothing: re-issuing the write will be refused, \
                 and a new escalation must be opened."
            } else if bar_met {
                "this decision does not permit the write: it is a DENY, recorded as one"
            } else {
                "this decision does NOT permit the write: the stated bar is UNMET. It is \
                 recorded, and re-issuing the write will still be refused. Decisions are \
                 single-shot, so this escalation can no longer accumulate the missing \
                 factor — a new one must be opened."
            },
        })
    }

    /// The instant after which an approval stops being claimable.
    ///
    /// Two ceilings, and BOTH have to hold — which is what makes this change monotone: no
    /// input can ride longer than it could under the previous single ceiling.
    ///
    /// 1. **One window after the grant.** `APPROVAL_CLAIM_WINDOW_SECS` bounds how long a
    ///    GRANTED approval stays spendable, so it is measured from the grant. Anchored at
    ///    `opened_at` it quietly meant "the TTL remainder plus the window": measured on the
    ///    live chain, median ride after a grant was 4160s against a documented 600s, 63/63
    ///    escalations over it, and 15 of 18 cross-session relays — a permit opened by one
    ///    session and spent by another — fit inside the slack.
    /// 2. **One window after the record dies.** An approval must not outlive the escalation
    ///    it belongs to by more than a window. Needed independently of (1): the replay path
    ///    restores a decided entry carrying no `decided_at` as `decided_at = replay time`
    ///    (`or(Some(now))` below), and a grant anchor alone would hand a restarted daemon a
    ///    fresh window an arbitrary distance after the open. This reads `expires_at` rather
    ///    than the DEFAULT ttl, which the hardcoded form got wrong for any escalation opened
    ///    with a shorter one.
    ///
    /// Pinned by `the_claim_window_is_measured_from_the_grant_not_the_open` (the EVENT) and
    /// `re_anchoring_the_claim_window_can_only_shorten_it` (the monotonicity, incl. the
    /// replay input). `the_claim_window_stays_tight_even_though_the_decision_window_grew`
    /// pins the constant and passes under any anchor — it is not a check on this.
    fn decided_horizon(&self) -> u64 {
        let one_window_after_grant = self
            .decided_at
            .unwrap_or(self.opened_at)
            .saturating_add(APPROVAL_CLAIM_WINDOW_SECS);
        let one_window_after_death = self.expires_at.saturating_add(APPROVAL_CLAIM_WINDOW_SECS);
        one_window_after_grant.min(one_window_after_death)
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
/// The outcome of an invitation, as a record rather than a gate.
#[derive(Debug, Clone, serde::Serialize)]
pub struct PeerParticipation {
    /// Seats invited to participate. Plural by design (dp: *"should invitation go out to
    /// more than one peer? i think yes."*).
    pub invited: Vec<String>,
    pub concurred: usize,
    pub dissented: usize,
    /// Invited seats that HAD A MAILBOX READER and have not answered — counted by identity,
    /// not by subtracting `concurred + dissented`. Derived, not stored; see
    /// `peer_participation` for why the difference is load-bearing.
    ///
    /// Does NOT complete a partition with the fields above it: `concurred`/`dissented` count
    /// every peer factor, including one from a seat that was never invited, while this counts
    /// only invited seats. `absent + invited_without_reader <= invited.len()` is the invariant;
    /// equality holds exactly while no invited seat has answered.
    pub absent: usize,
    /// Invited seats no watcher had ever read a mailbox for at invite time. Held out of
    /// `absent` because they cannot have looked, and reported beside it because they were
    /// still asked: a reader must be able to see that the invitation went somewhere nobody
    /// listens, which is a finding about the ROUTE, not about the seat.
    pub invited_without_reader: usize,
}

#[derive(Default)]
pub struct EscalationStore {
    by_id: HashMap<String, Escalation>,
    /// Monotonic, so two escalations opened in the same second still differ.
    seq: u64,
    /// Markers a GATE has actually presented, per member — the authoritative spellings.
    ///
    /// THE MARKER IS A JOIN KEY, NOT A LABEL, and nothing said so (dp, 2026-08-04: *"yes,
    /// that's a problem — fix it"*). `claim()` matches on `(plugin_id, marker)`. A member
    /// filing a reasoned escalation via `hestia_gate_escalation_open` chooses that string
    /// itself and has **no way to learn** what its gate will present later.
    ///
    /// Live instance: claude-code filed one with a human-readable marker — written to read
    /// well for the operator — while its gate matches on the hook directory path. dp approved
    /// it. The escalation was `approved`, `permits_write=true`, and permanently unclaimable,
    /// and the failure was indistinguishable from "not approved yet".
    ///
    /// The perverse part is the incentive. The DEGRADED path always works, because when a gate
    /// auto-opens on a deny it supplies both sides of the join. The CORRECT path — file
    /// deliberately, state a reason — is the only one that can silently mismatch. Asking
    /// properly was punished; tripping the gate was not. That is the "efficient path and
    /// correct path must be the same path" principle inverted, inside the mechanism built to
    /// reward asking.
    ///
    /// Populated from `claim()` ONLY. Those spellings come from a gate presenting its own
    /// matched rule, so they are evidence. `open()` markers are caller-asserted and are never
    /// taught back — otherwise a member could seed the vocabulary with its own invention and
    /// have it read as authoritative.
    ///
    /// (This doc deliberately does not quote the literal marker string. Writing it makes the
    /// comment itself match the gate's own governance-path rule, and editing this file — a
    /// daemon file, not gate code — is then refused as a write to the gate. That is the same
    /// mention-not-resolution defect tracked in #158, hit while fixing a different one.)
    gate_markers: HashMap<String, std::collections::BTreeSet<String>>,
    /// Escalations whose lapse has already been witnessed (`gate_escalation_expired`
    /// appended) by the periodic lapse recorder. MEMORY-ONLY, and that is
    /// sufficient: `rehydrate` skips expired opens, so after a restart no row that
    /// could double-record a lapse is ever restored — a lapse that crossed while
    /// the daemon was down is simply never recorded (accepted gap, #480 revised
    /// review item 6: process newly-crossed expiries, page history explicitly or
    /// not at all). The chain entry is the durable record; this set only dedups
    /// the append within one daemon lifetime.
    lapse_recorded: std::collections::HashSet<String>,
}

pub fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

impl EscalationStore {
    /// Rebuild this store from the witness chain (dp, 2026-08-01).
    ///
    /// THE STORE IS A PROJECTION, NOT AN AUTHORITY. Escalations were held in memory only, so a
    /// daemon restart destroyed every pending escalation AND every approval a human had already
    /// granted. Measured on 2026-08-01: dp approved a governance write, a deploy restarted the
    /// daemon minutes later, and the ruling was gone — the operator had made a real decision and
    /// the system had no memory of it. Deploying a law change requires a restart, so the act of
    /// governing was what destroyed the governance.
    ///
    /// Rebuilt by replay rather than by adding a sidecar table, per dp's ruling: the ruling is
    /// already "a separate act, linked to the previous act it modifies, both properly witnessed,
    /// all one chain". A second durable copy would be exactly the two-copies-no-comparison shape
    /// the supervisor thread died on — and it would let the store and the chain disagree about
    /// who approved what, which is the one disagreement this subsystem must never have. Replay
    /// means a decision is durable BECAUSE it was witnessed, not in addition to being witnessed.
    ///
    /// Entries must arrive OLDEST FIRST; later events amend earlier ones in arrival order, which
    /// is how the chain already reads. Unknown ids on a decide/claim are skipped rather than
    /// synthesised: an escalation whose `opened` entry is outside the replay window is one this
    /// store cannot describe honestly, and inventing a shell for it would put a governance record
    /// in front of an operator that no witnessed act supports.
    pub fn rehydrate(&mut self, entries: &[crate::storage::chain::ChainEntry], now: u64) -> usize {
        let s = |v: &serde_json::Value, k: &str| {
            v.get(k).and_then(|x| x.as_str()).map(|x| x.to_string())
        };
        let u = |v: &serde_json::Value, k: &str| v.get(k).and_then(|x| x.as_u64());
        let mut restored = 0usize;
        for e in entries {
            let d = &e.event_data;
            let Some(id) = s(d, "escalation_id") else { continue };
            match e.event_type.as_str() {
                "gate_escalation_opened" => {
                    let (Some(plugin_id), Some(marker), Some(expires_at)) =
                        (s(d, "plugin_id"), s(d, "marker"), u(d, "expires_at"))
                    else {
                        continue;
                    };
                    // Terminal-by-time entries are not worth restoring: they cannot be ruled and
                    // would only pad an operator's queue with things that are already answers.
                    if expires_at <= now {
                        continue;
                    }
                    self.by_id.insert(
                        id.clone(),
                        Escalation {
                            id,
                            // RESTORE THE INVITATION, not just the ask. Exactly the defect
                            // `factors_present` below was written to close, one field over: an
                            // escalation restored with an empty invitation reads `absent: 0`
                            // and `peer_participation()` reports "nobody was asked" about a
                            // decision where three seats WERE asked and none looked. That is
                            // the finding the invitation exists to produce, and a daemon
                            // restart would erase it — silently, and in the direction that
                            // flatters the record.
                            //
                            // Absent key restores empty, which is honest for every escalation
                            // opened before this writer existed (all 317 of them) and for
                            // every `SingleApprover` open, whose bar asks for no peer.
                            invited_peers: d
                                .get("invited_peers")
                                .and_then(|v| {
                                    serde_json::from_value::<Vec<String>>(v.clone()).ok()
                                })
                                .unwrap_or_default(),
                            // Derived from the same entry rather than stored twice: the open
                            // writer records the doorbell fact per peer inside
                            // `invitation_evidence`, so a restart rebuilds the split from the
                            // evidence the decision was issued on, not from today's mailboxes
                            // — which is the whole reason it is captured at invite time.
                            invited_without_reader: d
                                .get("invitation_evidence")
                                .and_then(|v| v.as_array())
                                .map(|rows| {
                                    rows.iter()
                                        .filter(|r| r.get("mailbox_reader") == Some(&serde_json::Value::Bool(false)))
                                        .filter_map(|r| {
                                            r.get("peer").and_then(|p| p.as_str()).map(str::to_string)
                                        })
                                        .collect()
                                })
                                .unwrap_or_default(),
                            plugin_id,
                            // Restored from the entry when present — the open writer emits
                            // `asker_basis` on every `gate_escalation_opened`. Absent fails
                            // closed to `Asserted`: a restored escalation with no recorded
                            // basis has no proven asker, and no peer may clear it (#128).
                            asker_basis: d
                                .get("asker_basis")
                                .and_then(|v| {
                                    serde_json::from_value::<crate::arbiter::AskerBasis>(v.clone()).ok()
                                })
                                .unwrap_or_default(),
                            role: s(d, "role").unwrap_or_default(),
                            tool_name: s(d, "tool_name").unwrap_or_default(),
                            // Recomputed from the marker rather than read from the entry: the
                            // claim path's `opened` event does not carry `bar`, and a default
                            // would silently lower the criterion an escalation is judged against.
                            stated_reason: s(d, "stated_reason"),
                            stated_detail: s(d, "stated_detail"),
                            bar: bar_for(&marker),
                            marker,
                            opened_at: u(d, "opened_at").unwrap_or(now),
                            expires_at,
                            status: Status::Pending,
                            decided_at: None,
                            decided_by: None,
                            decided_via: None,
                            decided_role: None,
                            reason: None,
                            independence: None,
                            consumed_at: None,
                            factors: Vec::new(),
                        },
                    );
                    restored += 1;
                }
                "gate_escalation_decided" => {
                    if let Some(esc) = self.by_id.get_mut(&id) {
                        esc.status = match s(d, "status").as_deref() {
                            Some(x) if x.eq_ignore_ascii_case("approved") => Status::Approved,
                            Some(x) if x.eq_ignore_ascii_case("denied") => Status::Denied,
                            // An unreadable status must not restore as Approved. Anything this
                            // replay cannot positively identify as a grant is not a grant.
                            _ => Status::Denied,
                        };
                        esc.decided_at = u(d, "decided_at").or(Some(now));
                        esc.decided_by = s(d, "decided_by");
                        esc.decided_role = s(d, "decided_role");
                        esc.reason = s(d, "reason");
                        // RESTORE THE EVIDENCE, not just the verdict. `claim` re-checks
                        // `bar_met()`, which is evaluated against the factor SET — so an
                        // escalation restored with an empty set reads Approved and then refuses
                        // to be claimed. That is the worst of both outcomes: the operator sees
                        // their approval survived the restart and the write is still blocked,
                        // with nothing on any surface explaining why. Caught by
                        // `replay_restores_rulings_without_re_arming_spent_ones` before it
                        // shipped; without that assertion this would have looked like it worked.
                        if let Some(fs) = d.get("factors_present") {
                            if let Ok(parsed) = serde_json::from_value::<Vec<Factor>>(fs.clone()) {
                                esc.factors = parsed;
                            }
                        }
                    }
                }
                "gate_escalation_corroborated" => {
                    // RESTORE THE PEER'S EVIDENCE while the escalation is still pending —
                    // the same restore `gate_escalation_decided` performs, one lifecycle
                    // stage earlier. Without this arm a restart erased every factor on a
                    // pending escalation, and it erased in the direction that flatters the
                    // record: a dissent lodged before the crash (#367) reads afterwards as
                    // a peer who never looked. The event carries the full set AFTER its
                    // factor, so the last entry wins and order is preserved.
                    if let Some(esc) = self.by_id.get_mut(&id) {
                        if let Some(fs) = d.get("factors_present") {
                            if let Ok(parsed) = serde_json::from_value::<Vec<Factor>>(fs.clone()) {
                                esc.factors = parsed;
                            }
                        }
                    }
                }
                "gate_escalation_claimed" => {
                    // An approval is single-use. If the chain shows it was already spent, the
                    // restored copy must be spent too — otherwise a restart would RE-ARM every
                    // approval ever granted, turning a crash into a way to reuse a human's yes.
                    if let Some(esc) = self.by_id.get_mut(&id) {
                        esc.consumed_at = u(d, "consumed_at").or(Some(now));
                    }
                }
                _ => {}
            }
        }
        restored
    }

    pub fn open(
        &mut self,
        plugin_id: &str,
        role: &str,
        tool_name: &str,
        marker: &str,
        stated_reason: Option<&str>,
        stated_detail: Option<&str>,
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
            invited_peers: Vec::new(),
            invited_without_reader: Vec::new(),
            plugin_id: plugin_id.to_string(),
            // Fail closed: every `open` caller is unproven until the handler records
            // otherwise via `record_asker_basis`. An asserted-by-default asker can be
            // decided by the sovereign and can never collect a peer factor (#128).
            asker_basis: crate::arbiter::AskerBasis::default(),
            role: role.trim().to_string(),
            tool_name: tool_name.to_string(),
            marker: marker.to_string(),
            stated_reason: stated_reason.map(str::to_string).filter(|v| !v.trim().is_empty()),
            stated_detail: stated_detail.map(str::to_string).filter(|v| !v.trim().is_empty()),
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
            // The bar is stated AT OPEN and copied from policy, so the record carries the
            // criterion in force at the time — a later tightening of `bar_for` must not
            // rewrite what this escalation was judged against.
            bar: bar_for(marker),
            factors: Vec::new(),
        };
        self.by_id.insert(id, esc.clone());
        Ok(esc)
    }

    /// Record which seats were INVITED to participate — the production writer the invitation
    /// half never had.
    ///
    /// #226 implemented dp's ruling that the two-bar is *"an invitation to participate, not a
    /// blocker"*: `bar_met` for `SovereignPlusPeer` stopped requiring the peer conjunct, and
    /// the peer half was retained *as evidence* through `invited_peers` /
    /// `peer_participation()`. The removal shipped. The evidence did not. Censused over
    /// 111,620 chain entries (private deployment census): `invited_peers` had NO
    /// production writer — `open()` and `rehydrate()` both set `Vec::new()`, and the only
    /// assignment in the crate was inside a test — and **0 of 317 `gate_escalation_opened`
    /// payloads carried any key naming a peer**. So the record could not tell *invited and
    /// absent* from *never asked*, which is the one distinction the ruling says it preserves.
    ///
    /// Separate from `open` on purpose. `open` is pure over the store and takes no view of the
    /// society; resolving a peer pool needs the member registry and a chain window, which live
    /// a layer up (`handler::tool_gate_escalation_open`). Keeping the resolution there and the
    /// recording here means this store never has to know what a member is — and it means the
    /// invitation is written by the same call that witnesses it, not by a background sweep
    /// that could disagree with the chain.
    ///
    /// Idempotent by overwrite: the last invitation wins. There is no accumulate semantics
    /// because a second invitation to a different set is a different fact, not more of the
    /// same one, and `absent` is derived from this list — appending would inflate it.
    ///
    /// Returns false for an unknown id rather than synthesising a shell. An invitation
    /// attached to an escalation this store cannot describe is a record of nothing, and
    /// `rehydrate` already refuses to invent shells for the same reason.
    pub fn invite(&mut self, id: &str, peers: Vec<String>) -> bool {
        match self.by_id.get_mut(id) {
            Some(e) => {
                e.invited_peers = peers;
                true
            }
            None => false,
        }
    }

    /// Which of the invited seats had no mailbox reader when they were asked.
    ///
    /// Separate from `invite` for the reason `record_asker_basis` is: the fact belongs to the
    /// handler, which owns the inbox store, and `invite`'s existing callers — every one a
    /// test — keep the honest default (nobody flagged) without a signature change. Silently
    /// ignores ids that were not invited: a flag on a seat nobody asked is not a fact about
    /// this escalation, and letting it through would let `absent` be reduced by a name that
    /// never appeared in the invitation.
    pub fn record_invitee_readers(&mut self, id: &str, without_reader: Vec<String>) -> bool {
        match self.by_id.get_mut(id) {
            Some(e) => {
                e.invited_without_reader = without_reader
                    .into_iter()
                    .filter(|p| e.invited_peers.contains(p))
                    .collect();
                true
            }
            None => false,
        }
    }

    /// Record how the asker's identity was established (#128). Separate from `open` for the
    /// same reason `invite` is: the proof happens in the handler, which owns the session
    /// registry, and `open`'s existing callers — every one a test with no session to prove
    /// anything by — keep the fail-closed default without a signature change. Returns false
    /// only for an unknown id, which cannot happen from the handler's own flow.
    pub fn record_asker_basis(&mut self, id: &str, basis: crate::arbiter::AskerBasis) -> bool {
        match self.by_id.get_mut(id) {
            Some(e) => {
                e.asker_basis = basis;
                true
            }
            None => false,
        }
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
    /// Marker spellings this member's gate has actually presented. Empty is HONEST, not
    /// permissive: it means no gate has claimed for this member yet, so nothing is known —
    /// which a caller must render as "unknown", never as "your marker is fine".
    pub fn known_gate_markers(&self, plugin_id: &str) -> Vec<String> {
        self.gate_markers
            .get(plugin_id.trim())
            .map(|s| s.iter().cloned().collect())
            .unwrap_or_default()
    }

    /// Would an approval against this marker ever be claimable?
    ///
    /// Three-valued on purpose, because "no evidence" and "contradicted by evidence" are
    /// different facts and collapsing them is the defect this whole surface keeps producing:
    ///   `Some(true)`  — a gate has presented exactly this spelling. The join will match.
    ///   `Some(false)` — gates have presented OTHER spellings for this member, and not this
    ///                   one. An approval here is very likely to be unclaimable.
    ///   `None`        — nothing known yet. Say so; do not reassure.
    pub fn marker_is_recognised(&self, plugin_id: &str, marker: &str) -> Option<bool> {
        let known = self.gate_markers.get(plugin_id.trim())?;
        if known.is_empty() {
            return None;
        }
        Some(known.contains(marker.trim()))
    }

    pub fn claim(&mut self, plugin_id: &str, marker: &str, now: u64) -> Option<Escalation> {
        let plugin_id = plugin_id.trim();
        let marker = marker.trim();
        if plugin_id.is_empty() || marker.is_empty() {
            return None;
        }
        // LEARN THE SPELLING, whether or not an approval is found. A gate reaching this call
        // has just matched one of its own rules, so this string is the authoritative join key
        // for this member — and the failure case (no approval yet) is precisely when a member
        // is about to file one and needs to know it.
        self.gate_markers
            .entry(plugin_id.to_string())
            .or_default()
            .insert(marker.to_string());
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
        // The decider's own factor, always recorded — the bar is evaluated against the SET,
        // and a decision is evidence first, a verdict second.
        esc.factors.push(Factor {
            channel: via,
            by: decided_by.trim().to_string(),
            role: esc.decided_role.clone(),
            independence,
            // A decision is concurrence with itself. Dissent is a PEER verb, and the
            // decision's own rationale already lives on `reason`.
            dissent: false,
            argument: None,
            at: now,
        });
        Ok(esc.clone())
    }

    /// Undo a decision, restoring the exact pre-decision row. Exists for ONE
    /// caller pattern (revised #480 review, defect 2): the decision surfaces
    /// apply `decide` and then witness, because the witness payload is built
    /// from the post-decision record — and if the `gate_escalation_decided`
    /// append fails, the ruling must NOT become final. An applied-but-unwitnessed
    /// decision has no ruling hash, no projector source, and no representable
    /// disposition obligation: finality without its terminal witness. So the
    /// caller clones the row before `decide` and hands it back here on append
    /// failure. Not a general undo — nothing else may call this.
    pub fn undo_decide(&mut self, prior: Escalation) {
        self.by_id.insert(prior.id.clone(), prior);
    }

    /// Add a peer's evidence to a PENDING escalation without deciding it.
    ///
    /// This is the accumulation half of the constellation model: approval is not a boolean
    /// from whichever channel answered first. A peer co-signs here (NOT-SAME, enforced by the
    /// caller the same way arbitration enforces it), the operator decides later, and `bar_met`
    /// evaluates the whole set. A corroboration is NOT a decision: it permits nothing by
    /// itself, it is witnessed separately (so it cannot be laundered into a ruling), and it
    /// freezes the moment a decision lands — evidence after the fact would let a weak ruling
    /// be dressed up retroactively.
    pub fn corroborate(
        &mut self,
        id: &str,
        by: &str,
        role: &str,
        independence: Option<crate::arbiter::Independence>,
        // A peer that looked and DISAGREED. Recorded, surfaced, and never a veto — dp's
        // ruling makes dissent evidence for review rather than a brake on the sovereign.
        dissent: bool,
        // The peer's stated argument, verbatim. The CALLER decides whether it is required
        // (the MCP door requires it for dissent); the store records what it is handed.
        argument: Option<&str>,
        now: u64,
    ) -> Result<Escalation, DecideError> {
        if by.trim().is_empty() {
            return Err(DecideError::AnonymousDecider);
        }
        let esc = self.by_id.get_mut(id).ok_or(DecideError::Unknown)?;
        // PARTICIPATION MAY LAND AFTER THE DECISION. Under blocker semantics, refusing a
        // decided escalation was right: a late factor could have flipped an outcome. Under
        // invitation semantics it is wrong, and kimi's decision-of-record says so directly
        // — the sovereign has already ruled, nothing here can reopen it, and a peer that
        // looked afterwards is exactly the feedback the invitation was issued to collect.
        //
        // Expired still refuses. That is not a decision the peer is commenting on; it is a
        // record whose window closed, and a factor arriving after it would attach evidence
        // to something the hook already denied for a different reason.
        if esc.status_at(now) == Status::Expired {
            return Err(DecideError::Expired);
        }
        esc.factors.push(Factor {
            channel: Channel::PeerMember,
            by: by.trim().to_string(),
            role: Some(role.trim().to_string()).filter(|r| !r.is_empty()),
            independence,
            dissent,
            argument: argument
                .map(|a| a.trim().to_string())
                .filter(|a| !a.is_empty()),
            at: now,
        });
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

    /// Live-store rows that have crossed their deadline with no decision and no
    /// recorded lapse — the bounded input to the lapse recorder (#480 revised
    /// review, item 6). Bounded by construction: open rows are few and reaped,
    /// so this never scans history. `status_at` does the clock derivation; the
    /// stored-Pending predicate excludes decided and withdrawn rows; the marker
    /// set excludes rows already witnessed this daemon lifetime.
    pub fn newly_lapsed(&self, now: u64) -> Vec<Escalation> {
        self.by_id
            .values()
            .filter(|e| {
                e.stored_status() == Status::Pending
                    && e.status_at(now) == Status::Expired
                    && !self.lapse_recorded.contains(&e.id)
            })
            .cloned()
            .collect()
    }

    /// Mark a lapse as witnessed. Called only AFTER the `gate_escalation_expired`
    /// append succeeded — a failed append leaves the row eligible so the next
    /// pass retries, and a recorded one never appends twice.
    pub fn mark_lapse_recorded(&mut self, id: &str) {
        self.lapse_recorded.insert(id.to_string());
    }

    /// Drop entries that have been terminal for a while. Purely housekeeping: it can never
    /// change an answer, because `status_at` already treats a missing id and an expired id the
    /// same way.
    pub fn reap(&mut self, now: u64, keep_secs: u64) -> usize {
        let before = self.by_id.len();
        self.by_id
            .retain(|_, e| e.status_at(now) == Status::Pending || now < e.expires_at + keep_secs);
        // The lapse markers name rows; a reaped row's marker is dead weight, and
        // an unbounded set would grow with daemon uptime for no reader.
        self.lapse_recorded.retain(|id| self.by_id.contains_key(id));
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

    fn chain_entry(event_type: &str, data: serde_json::Value) -> crate::storage::chain::ChainEntry {
        crate::storage::chain::ChainEntry {
            chain_position: 0,
            hash: String::new(),
            prev_hash: String::new(),
            event_type: event_type.to_string(),
            event_data: data,
            signer_lct: "test".into(),
            timestamp: chrono::Utc::now(),
        }
    }

    /// Replay must restore a human's ruling AND must never re-arm one that was already spent.
    ///
    /// The second half is the dangerous direction: if a restart resurrected consumed approvals,
    /// crashing the daemon would become a way to reuse a yes — one approval licensing every
    /// later write to the same surface, which is exactly what single-use exists to prevent.
    #[test]
    fn replay_restores_rulings_without_re_arming_spent_ones() {
        let opened = |id: &str| {
            chain_entry(
                "gate_escalation_opened",
                serde_json::json!({
                    "escalation_id": id, "plugin_id": "kimi-code", "role": "role:constellation:member",
                    "tool_name": "Bash", "marker": "law_inject.py",
                    "opened_at": T0, "expires_at": T0 + 3600,
                }),
            )
        };
        let decided = |id: &str, status: &str| {
            chain_entry(
                "gate_escalation_decided",
                serde_json::json!({
                    "escalation_id": id, "status": status, "decided_by": "operator",
                    "decided_at": T0 + 10, "reason": "because",
                    // The evidence, as the real event carries it. Restoring the verdict without
                    // this leaves the bar unmet and the approval unclaimable.
                    "factors_present": [{
                        "channel": "operator_session", "by": "operator",
                        "role": "role:constellation:sovereign", "independence": null, "at": T0 + 10,
                    }],
                }),
            )
        };

        // Approved and unspent -> restored as usable.
        let mut s = EscalationStore::default();
        assert_eq!(s.rehydrate(&[opened("aaa1"), decided("aaa1", "approved")], T0 + 20), 1);
        assert_eq!(s.status_of("aaa1", T0 + 20), Status::Approved);
        assert!(s.claim("kimi-code", "law_inject.py", T0 + 20).is_some());

        // Approved then CLAIMED -> restored as spent, and unclaimable.
        let mut s2 = EscalationStore::default();
        s2.rehydrate(
            &[
                opened("bbb2"),
                decided("bbb2", "approved"),
                chain_entry("gate_escalation_claimed", serde_json::json!({"escalation_id": "bbb2"})),
            ],
            T0 + 20,
        );
        assert!(
            s2.claim("kimi-code", "law_inject.py", T0 + 20).is_none(),
            "a restart re-armed an approval the chain shows was already spent — crashing the \
             daemon must not be a way to reuse a human's yes"
        );

        // An unreadable status must NOT restore as a grant.
        let mut s3 = EscalationStore::default();
        s3.rehydrate(&[opened("ccc3"), decided("ccc3", "¯\\_(ツ)_/¯")], T0 + 20);
        assert!(!s3.status_of("ccc3", T0 + 20).permits_write());

        // A decision whose `opened` entry fell outside the replay window is skipped, not
        // synthesised: a governance record no witnessed act supports must never reach an operator.
        let mut s4 = EscalationStore::default();
        assert_eq!(s4.rehydrate(&[decided("ddd4", "approved")], T0 + 20), 0);
        assert_eq!(s4.status_of("ddd4", T0 + 20), Status::Expired);

        // Already terminal by time -> not restored; it cannot be ruled and would only pad the queue.
        let mut s5 = EscalationStore::default();
        assert_eq!(s5.rehydrate(&[opened("eee5")], T0 + 7200), 0);
    }

    /// #367's restore half: a peer factor lodged while the escalation is still PENDING must
    /// survive a restart. RED before the `gate_escalation_corroborated` replay arm existed:
    /// every pre-decision factor was erased, and erased in the flattering direction — a
    /// dissent lodged before the crash read afterwards as a peer who never looked.
    #[test]
    fn replay_restores_pending_peer_factors_dissent_and_argument_included() {
        let mut s = EscalationStore::default();
        s.rehydrate(
            &[
                chain_entry(
                    "gate_escalation_opened",
                    serde_json::json!({
                        "escalation_id": "fff6", "plugin_id": "claude-code",
                        "role": "role:constellation:member", "tool_name": "Bash",
                        "marker": "witness.py", "opened_at": T0, "expires_at": T0 + 3600,
                    }),
                ),
                chain_entry(
                    "gate_escalation_corroborated",
                    serde_json::json!({
                        "escalation_id": "fff6",
                        "stance": "dissent", "dissent": true,
                        "argument": "evidence insufficient to review",
                        "factors_present": [{
                            "channel": "peer_member", "by": "codex",
                            "role": "role:constellation:member",
                            "independence": "cross_vendor", "at": T0 + 30,
                            "dissent": true,
                            "argument": "evidence insufficient to review",
                        }],
                    }),
                ),
            ],
            T0 + 60,
        );
        let esc = s.get("fff6").expect("restored as pending");
        assert_eq!(esc.status_at(T0 + 60), Status::Pending);
        assert_eq!(esc.factors.len(), 1, "the pre-decision factor must be restored");
        assert!(esc.factors[0].dissent, "restored AS the dissent it was, not flattened");
        assert_eq!(
            esc.factors[0].argument.as_deref(),
            Some("evidence insufficient to review"),
            "the argument survives the restart with it"
        );
        assert_eq!(esc.peer_participation().dissented, 1);
    }

    /// #128, the restore half. A `gate_escalation_opened` entry written before `asker_basis`
    /// existed restores as ASSERTED — fail closed, so a daemon restart cannot launder an
    /// unproven asker into a peer-clearable one — and an entry that carries the basis
    /// restores it. The basis the open writer emits and the basis the store enforces must be
    /// the same fact, or a restart is a privilege boundary.
    #[test]
    fn a_restored_escalation_keeps_its_asker_basis_and_an_absent_one_fails_closed() {
        let opened_with = |id: &str, basis: Option<&str>| {
            let mut data = serde_json::json!({
                "escalation_id": id, "plugin_id": "codex", "role": "r",
                "tool_name": "Edit", "marker": "pre_tool_use.py",
                "opened_at": T0, "expires_at": T0 + 3600,
            });
            if let Some(b) = basis {
                data["asker_basis"] = serde_json::json!(b);
            }
            chain_entry("gate_escalation_opened", data)
        };

        // No basis on the entry (every entry before the basis writer) -> Asserted.
        let mut s = EscalationStore::default();
        assert_eq!(s.rehydrate(&[opened_with("f004", None)], T0 + 20), 1);
        assert_eq!(
            s.get("f004").map(|e| e.asker_basis),
            Some(crate::arbiter::AskerBasis::Asserted),
            "an unrestored basis must fail closed, not default to proven"
        );

        // A recorded basis survives the restart.
        let mut s2 = EscalationStore::default();
        assert_eq!(s2.rehydrate(&[opened_with("f005", Some("session"))], T0 + 20), 1);
        assert_eq!(
            s2.get("f005").map(|e| e.asker_basis),
            Some(crate::arbiter::AskerBasis::Session),
        );

        // And the live path: `open` defaults to Asserted until the handler records the proof.
        let mut s3 = EscalationStore::default();
        let e = s3.open("codex", "r", "Edit", "pre_tool_use.py", None, None, T0, 120).unwrap();
        assert_eq!(e.asker_basis, crate::arbiter::AskerBasis::Asserted);
        assert!(s3.record_asker_basis(&e.id, crate::arbiter::AskerBasis::Session));
        assert_eq!(s3.get(&e.id).map(|e| e.asker_basis), Some(crate::arbiter::AskerBasis::Session));
    }

    /// A restart must not erase WHO WAS ASKED.
    ///
    /// The same defect `factors_present` above was written to close, one field over, and it
    /// fails in the flattering direction: an escalation restored with an empty invitation
    /// reports `absent: 0`, so `peer_participation()` says "nobody was asked" about a decision
    /// where three seats were asked and none looked — which is precisely the finding the
    /// invitation exists to produce (dp: one asleep is an availability accident, three that
    /// never looked is a finding).
    ///
    /// RED ARM: with `invited_peers` restored as `Vec::new()` — what `rehydrate` did until
    /// this commit — the first `absent` assertion below reads 0 and fails.
    #[test]
    fn replay_restores_who_was_invited_not_only_who_answered() {
        let opened_with = |id: &str, invited: serde_json::Value| {
            chain_entry(
                "gate_escalation_opened",
                serde_json::json!({
                    "escalation_id": id, "plugin_id": "claude-code",
                    "role": "role:constellation:member", "tool_name": "Edit",
                    "marker": "pre_tool_use.py",
                    "opened_at": T0, "expires_at": T0 + 3600,
                    "invited_peers": invited,
                }),
            )
        };

        let mut s = EscalationStore::default();
        assert_eq!(
            s.rehydrate(
                &[opened_with("f001", serde_json::json!(["kimi-code", "codex", "thor"]))],
                T0 + 20
            ),
            1
        );
        let p = s.get("f001").unwrap().peer_participation();
        assert_eq!(
            p.invited,
            vec!["kimi-code".to_string(), "codex".to_string(), "thor".to_string()],
            "the invitation is part of the record, not a runtime detail — a restart that \
             drops it turns 'three were asked and none looked' into 'nobody was asked'"
        );
        assert_eq!(
            p.absent, 3,
            "absent is DERIVED from the invitation; an erased invitation reports 0 absent, \
             which is the same number a never-invited escalation reports"
        );
        assert_eq!(p.concurred, 0);

        // And it survives a peer answering after the replay — the arithmetic still refers to
        // the restored list rather than to whoever happened to show up.
        s.corroborate("f001", "kimi-code", "role:constellation:member", None, false, None, T0 + 30)
            .expect("an invited peer may participate");
        let p2 = s.get("f001").unwrap().peer_participation();
        assert_eq!(p2.concurred, 1);
        assert_eq!(p2.absent, 2, "two of the three invited seats still have not looked");

        // A pre-invitation entry — every one of the 317 opens on this chain before this
        // commit — restores empty. That is honest, not a gap: nobody was asked.
        let mut s2 = EscalationStore::default();
        s2.rehydrate(
            &[chain_entry(
                "gate_escalation_opened",
                serde_json::json!({
                    "escalation_id": "f002", "plugin_id": "claude-code", "role": "r",
                    "tool_name": "Edit", "marker": "pre_tool_use.py",
                    "opened_at": T0, "expires_at": T0 + 3600,
                }),
            )],
            T0 + 20,
        );
        assert!(s2.get("f002").unwrap().peer_participation().invited.is_empty());

        // A malformed value must not poison the replay. Fail closed to "nobody asked" rather
        // than dropping the escalation: an unrulable governance record is worse than an
        // unattributed one, and `invited_peers` is evidence, never a gate.
        let mut s3 = EscalationStore::default();
        assert_eq!(
            s3.rehydrate(&[opened_with("f003", serde_json::json!("kimi-code"))], T0 + 20),
            1,
            "the escalation still restores"
        );
        assert!(s3.get("f003").unwrap().peer_participation().invited.is_empty());
    }

    /// `invite` refuses an id the store cannot describe.
    ///
    /// `rehydrate` already refuses to synthesise shells for unknown ids, for the reason its
    /// doc gives: a governance record no witnessed act supports must not reach an operator.
    /// An invitation attached to nothing is the same object, and returning `true` here would
    /// let the caller witness "we asked three peers about escalation X" where X does not
    /// exist.
    #[test]
    fn an_invitation_to_an_unknown_escalation_is_refused() {
        let (mut s, id) = store_with_one();
        assert!(!s.invite("deadbeefdeadbeef", vec!["kimi-code".into()]));
        assert!(s.invite(&id, vec!["kimi-code".into()]));

        // Overwrite, not append: a second invitation to a different set is a different fact,
        // and appending would inflate `absent` with seats counted twice.
        assert!(s.invite(&id, vec!["codex".into()]));
        assert_eq!(s.get(&id).unwrap().peer_participation().invited, vec!["codex".to_string()]);
        assert_eq!(s.get(&id).unwrap().peer_participation().absent, 1);
    }

    /// Opens on `law_inject.py` — the SingleApprover surface. Claim-mechanics tests live
    /// here because their subject is the claim, not the bar; bar semantics have their own
    /// module (bar_factor_tests).
    fn store_with_one_simple_marker() -> (EscalationStore, String) {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "role:constellation:member", "Edit", "law_inject.py", None, None, T0, 120)
            .expect("open");
        (s, e.id)
    }

    fn store_with_one() -> (EscalationStore, String) {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "role:constellation:member", "Edit", "pre_tool_use.py", None, None, T0, 120)
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
    fn a_sovereign_may_rule_a_two_bar_alone_and_the_absent_peer_is_recorded() {
        // dp, decision of record 2026-08-06: "On sovereign decisions, two-bar is an
        // invitation to participate, not a blocker."
        //
        // The measurement that forced it (#219): sovereign_plus_peer was 0 of 66 bar-met,
        // LIFETIME. Decisions are single-shot, corroborate refused decided escalations,
        // and the median ruling landed 69s after opening — faster than a mesh round trip.
        // This test is the arithmetic of that ruling: it FAILS on the old semantics.
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "r", "Bash", "pre_tool_use.py", None, None, T0, DEFAULT_TTL_SECS)
            .unwrap();
        let id = e.id.clone();
        assert_eq!(s.get(&id).unwrap().bar, Bar::SovereignPlusPeer);

        let decided = s
            .decide(&id, true, "operator", "role:constellation:sovereign",
                    Channel::OperatorSession, None, Some("deploy the merged hook"), T0 + 10)
            .unwrap();

        assert!(decided.bar_met(), "a sovereign decision meets a two-bar alone");
        assert!(
            decided.is_claimable(T0 + 20),
            "and it PERMITS — the whole defect was an approval that granted nothing"
        );

        // The peer half survives as evidence, not as a gate.
        let p = decided.peer_participation();
        assert_eq!(p.concurred, 0);
        assert_eq!(p.dissented, 0);
        assert_eq!(p.absent, 0, "nobody was invited, so nobody is absent — absent is DERIVED");
    }

    /// One peer's answer must not cancel a DIFFERENT peer's silence.
    ///
    /// codex's review of PR#454 (the change that first held readerless invitees out of
    /// `absent`) named the hole in that change: it subtracted a GLOBAL factor count from a
    /// REDUCED population, so the two numbers were about different sets of seats. The
    /// specimen it prescribed, run verbatim here — invite a readerless seat and a readable
    /// one, flag only the readerless seat, let only the readerless seat answer.
    ///
    /// The late reader is not hypothetical: `corroborate` expressly admits a factor after the
    /// decision, which is precisely the window in which a watcher that was not running at
    /// invite time starts and reads its queue. Under the subtraction that answer drove
    /// `absent` to 0, so the record said every invited seat had participated while the seat
    /// with a live mailbox had never looked — the exact confusion the field was added to end,
    /// reintroduced one layer in.
    #[test]
    fn a_late_readers_answer_cannot_hide_a_readable_peers_absence() {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "r", "Bash", "pre_tool_use.py", None, None, T0, DEFAULT_TTL_SECS)
            .unwrap();
        let id = e.id.clone();
        s.invite(&id, vec!["late-reader".into(), "readable-but-absent".into()]);
        s.record_invitee_readers(&id, vec!["late-reader".into()]);

        // Nothing has landed yet: one flagged, one genuinely awaited.
        let p = s.get(&id).unwrap().peer_participation();
        assert_eq!((p.absent, p.invited_without_reader), (1, 1), "{p:?}");

        // The flagged seat's watcher starts and it answers. Its own row leaves `absent`
        // untouched — it was never counted there — and, critically, does not consume the
        // other seat's.
        let after = s
            .corroborate(&id, "late-reader", "role:constellation:member", None, false,
                         Some("read the queue late, concur"), T0 + 30)
            .unwrap()
            .peer_participation();
        assert_eq!(after.concurred, 1, "the late answer is still counted as evidence: {after:?}");
        assert_eq!(
            after.absent, 1,
            "`readable-but-absent` has a reader and has said nothing — one answer from a \
             DIFFERENT seat must not report it as participating: {after:?}"
        );

        // Same defect, other cause: a peer nobody invited is real evidence, and it is not an
        // invited seat's absence either. `absent` is a fact about the invitation list.
        let uninvited = s
            .corroborate(&id, "a-passing-probe", "role:constellation:member", None, false,
                         Some("was not asked, looked anyway"), T0 + 40)
            .unwrap()
            .peer_participation();
        assert_eq!(uninvited.concurred, 2, "recorded as the evidence it is: {uninvited:?}");
        assert_eq!(
            uninvited.absent, 1,
            "but it cannot stand in for the seat that WAS asked: {uninvited:?}"
        );

        // And when the awaited seat finally answers, absence closes — by identity.
        let done = s
            .corroborate(&id, "readable-but-absent", "role:constellation:member", None, true,
                         Some("looked, and disagree"), T0 + 50)
            .unwrap()
            .peer_participation();
        assert_eq!((done.absent, done.dissented), (0, 1), "{done:?}");
    }

    /// The two deciding surfaces must answer the same question, because the last time they
    /// did not, the fix went to the wrong one.
    ///
    /// #219 added `bar`/`bar_met`/`permits_write` to the MCP arbitrate reply. The operator
    /// HTTP reply kept returning `{escalation_id, status, witnessEntryHash}` — and that is
    /// the surface that rules: 207 of 210 decided escalations on this chain came through
    /// `operator_session`, 3 through `peer_member` (private deployment census).
    ///
    /// This exercises `decision_reply` directly. It does NOT drive the axum route, so it
    /// proves the shared answer is correct, not that the route calls it —
    /// `the_operator_route_still_reads_the_shared_answer` covers that half, differently and
    /// more weakly.
    #[test]
    fn one_answer_serves_both_deciding_surfaces() {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "r", "Bash", "pre_tool_use.py", None, None, T0, DEFAULT_TTL_SECS)
            .unwrap();
        let id = e.id.clone();
        let decided = s
            .decide(&id, true, "operator", "role:constellation:sovereign",
                    Channel::OperatorSession, None, Some("proceed"), T0 + 5)
            .unwrap();

        let r = decided.decision_reply(T0 + 6);
        // The three fields the operator surface has never carried.
        assert!(r.get("bar").is_some(), "name the criterion: {r}");
        assert_eq!(r.get("bar_met").and_then(serde_json::Value::as_bool), Some(true));
        assert_eq!(
            r.get("permits_write").and_then(serde_json::Value::as_bool),
            Some(true),
            "an approval that IS claimable must say so: {r}"
        );
        // The reply must agree with the enforcement, not merely resemble it.
        assert_eq!(
            r.get("permits_write").and_then(serde_json::Value::as_bool).unwrap(),
            decided.is_claimable(T0 + 6),
            "the reported answer and `is_claimable` are one predicate or they will diverge"
        );
    }

    /// `permits_write` must track `is_claimable` ACROSS THE TWO CONJUNCTS THAT MOVE.
    ///
    /// WHY A SECOND TEST, when `one_answer_serves_both_deciding_surfaces` already asserts
    /// `permits_write == is_claimable`: because it asserts it at ONE instant, on a fresh
    /// unspent approval, six seconds after the grant. Both conjuncts that can differ —
    /// `consumed_at.is_none()` and `now < decided_horizon()` — are trivially satisfied
    /// there, so that equality held for a `permits_write` that did not contain either of
    /// them, and could not have. The field took no clock at all. A time-independent
    /// predicate cannot equal a time-dependent one except on the sub-domain where the
    /// time-dependent conjuncts are constant, and that test picked exactly that sub-domain.
    /// It named the divergence in its own failure message — "one predicate or they will
    /// diverge" — and was structurally incapable of observing it.
    ///
    /// So this samples the axis instead of a point, and asserts the equality at each
    /// sample. Sabotage arm: restore `permits_write` to the old two-conjunct form
    /// (`stored_status() == Approved && bar_met`) and the horizon and spent samples below
    /// both go red; the fresh sample stays green, which is the whole reason the old pin
    /// passed.
    #[test]
    fn permits_write_tracks_the_two_conjuncts_that_move() {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "r", "Bash", "pre_tool_use.py", None, None, T0, DEFAULT_TTL_SECS)
            .unwrap();
        let id = e.id.clone();
        let decided = s
            .decide(&id, true, "operator", "role:constellation:sovereign",
                    Channel::OperatorSession, None, Some("proceed"), T0 + 5)
            .unwrap();

        // --- sample 1: inside the window. The only point the old pin ever looked at.
        let live = decided.decision_reply(T0 + 6);
        assert_eq!(live["permits_write"], serde_json::json!(true));
        assert_eq!(live["granted"], serde_json::json!(true));
        assert_eq!(
            live["claim_window_secs_remaining"],
            serde_json::json!(APPROVAL_CLAIM_WINDOW_SECS - 1),
            "the countdown is anchored at the GRANT, not the open: {live}"
        );

        // --- sample 2: one second past the claim horizon. `granted` is unchanged forever;
        // `permits_write` is not, and this is the interval in which a spent-or-stale permit
        // was published as live.
        let past = T0 + 5 + APPROVAL_CLAIM_WINDOW_SECS + 1;
        assert!(!decided.is_claimable(past), "the enforcement refuses here");
        let stale = decided.decision_reply(past);
        assert_eq!(
            stale["permits_write"], serde_json::json!(false),
            "past the horizon the reporting surface must refuse too: {stale}"
        );
        assert_eq!(
            stale["granted"], serde_json::json!(true),
            "the decision fact does not decay — it is still an approval that met its bar"
        );
        assert_eq!(stale["claim_window_secs_remaining"], serde_json::json!(0));
        assert!(
            stale["note"].as_str().unwrap().contains("CLAIM WINDOW HAS CLOSED"),
            "and the note must name WHICH conjunct failed: {stale}"
        );

        // --- sample 3: SPENT, well inside the window. The other moving conjunct, and the
        // one that produced the false publication on 2026-08-18: a permit already claimed,
        // polled back as live.
        let claimed = s
            .claim("claude-code", "pre_tool_use.py", T0 + 10)
            .expect("the approval is claimable at T0+10, so the claim must find it");
        assert_eq!(claimed.consumed_at, Some(T0 + 10), "and the claim spends it");
        let spent = s.get(&id).unwrap().decision_reply(T0 + 11);
        assert_eq!(
            spent["permits_write"], serde_json::json!(false),
            "a SPENT approval permits nothing, one second later and 589s inside the \
             window — the case `secs_remaining` cannot see: {spent}"
        );
        assert_eq!(spent["granted"], serde_json::json!(true));
        assert!(
            spent["note"].as_str().unwrap().contains("ALREADY BEEN CLAIMED"),
            "name this conjunct too: {spent}"
        );

        // --- the invariant, asserted on the whole axis rather than at a point.
        let e_final = s.get(&id).unwrap();
        for offset in [0u64, 1, 6, 11, 300, 599, 600, 601, 4200] {
            let now = T0 + offset;
            assert_eq!(
                e_final.decision_reply(now)["permits_write"],
                serde_json::json!(e_final.is_claimable(now)),
                "reporting and enforcement are one predicate at every sample, or they are \
                 not one predicate at all (offset {offset})"
            );
        }
    }

    /// An approval short of the bar must say it permits nothing — the class #219 found, kept
    /// under test after #226 narrowed it.
    ///
    /// #226 made `SovereignPlusPeer` read the sovereign conjunct alone, so an operator's own
    /// approval now meets it and this class is CLOSED for that bar going forward. It is not
    /// closed retroactively and it was not closed on the box: the daemon serving this fleet
    /// was still built from a pre-#226 commit 42 minutes after #226 merged, and four more
    /// `sovereign_plus_peer` approvals were granted in that gap with `bar_met: false`. So the
    /// warning path stays pinned against a bar that genuinely is not met.
    #[test]
    fn an_approval_that_meets_no_bar_reports_that_it_permits_nothing() {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "r", "Bash", "pre_tool_use.py", None, None, T0, DEFAULT_TTL_SECS)
            .unwrap();
        let id = e.id.clone();
        s.decide(&id, true, "operator", "role:constellation:sovereign",
                 Channel::OperatorSession, None, Some("proceed"), T0 + 5)
            .unwrap();
        // Strip the evidence, keeping the grant: the shape a replay restores when the
        // `factors_present` array is missing, and the shape `is_claimable` refuses.
        let hollow = {
            let x = s.by_id.get_mut(&id).unwrap();
            x.factors.clear();
            x.clone()
        };
        let r = hollow.decision_reply(T0 + 6);
        assert_eq!(r.get("bar_met").and_then(serde_json::Value::as_bool), Some(false));
        assert_eq!(r.get("permits_write").and_then(serde_json::Value::as_bool), Some(false));
        assert!(
            r.get("note").and_then(serde_json::Value::as_str).unwrap().contains("does NOT permit"),
            "silence here is what cost 63 approvals: {r}"
        );
        assert!(!hollow.is_claimable(T0 + 6), "and the enforcement agrees");
    }

    /// "Nobody was invited" must be VISIBLE, not inferred from an absent field.
    ///
    /// #226 retained the peer conjunct as evidence via `peer_participation()`, on the
    /// reasoning that the bar "still shapes WHO IS ASKED and what is recorded". Neither half
    /// is true yet: `invited_peers` has no production writer (`open` and `rehydrate` both set
    /// `Vec::new()`), and before this change `peer_participation()` had no production reader
    /// at all. Censused over 111,620 chain entries: NO key on any `gate_escalation_opened` or
    /// `_decided` payload names an invited peer, across 317 opens.
    ///
    /// So this asserts the honest current state and guards the direction of the lie. An empty
    /// `invited` with `absent: 0` reads "nobody was asked". The failure to guard against is a
    /// future writer populating `invited` from a roster WITHOUT sending anything — that would
    /// make the record assert an invitation that was never issued.
    #[test]
    fn an_uninvited_peer_reads_as_uninvited_not_as_agreement() {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "r", "Bash", "pre_tool_use.py", None, None, T0, DEFAULT_TTL_SECS)
            .unwrap();
        assert!(
            e.invited_peers.is_empty(),
            "no production path invites anyone yet — if this fails, an invitation is being \
             RECORDED and the test that must accompany it is 'a notice was sent'"
        );
        let id = e.id.clone();
        let decided = s
            .decide(&id, true, "operator", "role:constellation:sovereign",
                    Channel::OperatorSession, None, Some("proceed"), T0 + 5)
            .unwrap();

        let p = decided.decision_reply(T0 + 6);
        let part = p.get("peer_participation").expect("participation must be ON the reply");
        assert_eq!(part.get("invited").and_then(serde_json::Value::as_array).unwrap().len(), 0);
        assert_eq!(part.get("concurred").and_then(serde_json::Value::as_u64), Some(0));
        assert_eq!(
            part.get("absent").and_then(serde_json::Value::as_u64),
            Some(0),
            "absent is derived from invited — nobody asked means nobody absent, NOT nobody \
             missing"
        );
    }

    /// The weak half of the parity check, and labelled weak on purpose.
    ///
    /// `operator_gate_escalation` is an axum handler over `SharedState`; driving it here would
    /// need a daemon fixture this module does not have. So this reads the source and asserts
    /// the operator route still routes through the shared answer. It is LEXICAL: it proves a
    /// call is written, not that it is reached, and a rename defeats it.
    ///
    /// It earns its place by being the only assertion in this file that goes RED on `main`
    /// today — the others cannot even compile there, and a compile error is not a measurement
    /// of the defect.
    ///
    /// IT COMMENTS OUT THE COMMENTS FIRST, and that line is the whole reason this test is
    /// trustworthy. The first version matched `contains("decision_reply")` against the raw
    /// source. Sabotaged — call deleted, route rebuilt as the bare pre-#219 literal — it
    /// still passed, because the explanatory comment ABOVE the call says the word
    /// `decision_reply`. The guard was certifying that someone had written *about* the shared
    /// answer, which is exactly the property a drifting reimplementation would preserve: a
    /// future author who rebuilds the literal will almost certainly leave the comment
    /// explaining why they shouldn't. Match the CALL, on comment-free source.
    #[test]
    fn the_operator_route_still_reads_the_shared_answer() {
        let src = include_str!("http.rs");
        let start = src
            .find("async fn operator_gate_escalation")
            .expect("the operator decide route must still exist under this name");
        let body = &src[start..];
        let end = body.find("\n}\n").map(|i| i + 3).unwrap_or(body.len());
        let code: String = body[..end]
            .lines()
            .map(|l| match l.find("//") {
                Some(i) => &l[..i],
                None => l,
            })
            .collect::<Vec<_>>()
            .join("\n");
        assert!(
            code.contains(".decision_reply("),
            "the operator decide route builds its own reply again. That is the exact drift \
             #219 left behind: the chain records `bar`/`bar_met` and the decider is told \
             neither, on the path that rules 207 of 210 escalations."
        );
    }

    #[test]
    fn dissent_is_recorded_and_does_not_veto() {
        // "a mechanism to surface dissent to the live UI" — evidence for review, never a
        // brake on the sovereign. A dissent that could block would make the invitation a
        // blocker again by the back door.
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "r", "Bash", "pre_tool_use.py", None, None, T0, DEFAULT_TTL_SECS)
            .unwrap();
        let id = e.id.clone();
        s.decide(&id, true, "operator", "role:constellation:sovereign",
                 Channel::OperatorSession, None, Some("proceed"), T0 + 5)
            .unwrap();

        // Invited seats, plural — dp: "should invitation go out to more than one peer?
        // i think yes."
        //
        // Through `invite()`, the production writer. This line used to reach into `by_id`
        // directly, and that WAS the whole population of writers: `invited_peers` was set
        // nowhere else in the crate, so this assertion passed on an invitation no escalation
        // outside a test could ever have.
        assert!(s.invite(&id, vec!["kimi-code".to_string(), "codex".to_string()]));

        let after = s
            .corroborate(&id, "kimi-code", "role:constellation:member", None, true, Some("recorded dissent"), T0 + 90)
            .expect("a peer may participate AFTER the decision — that is what invitation means");

        assert!(after.is_claimable(T0 + 95), "dissent records; it does not veto");
        let p = after.peer_participation();
        assert_eq!(p.dissented, 1, "the disagreement is on the record");
        assert_eq!(p.concurred, 0);
        assert_eq!(p.absent, 1, "codex was invited and has not answered — not the same as declining");
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
            s.open("", "r", "Edit", "gate.py", None, None, T0, 120).unwrap_err(),
            OpenError::MissingField("plugin_id")
        );
        assert_eq!(
            s.open("claude-code", "r", "", "gate.py", None, None, T0, 120).unwrap_err(),
            OpenError::MissingField("tool_name")
        );
        assert_eq!(
            s.open("claude-code", "r", "Edit", "   ", None, None, T0, 120).unwrap_err(),
            OpenError::MissingField("marker")
        );
    }

    #[test]
    fn a_flood_is_refused_and_expired_entries_do_not_hold_the_quota() {
        let mut s = EscalationStore::default();
        for i in 0..MAX_PENDING {
            s.open("claude-code", "r", "Edit", &format!("f{i}.py"), None, None, T0, 120)
                .expect("under the cap");
        }
        assert_eq!(
            s.open("claude-code", "r", "Edit", "one-too-many.py", None, None, T0, 120)
                .unwrap_err(),
            OpenError::TooManyPending(MAX_PENDING)
        );
        // Once they lapse, the quota frees — otherwise a member's own timeouts would lock it out
        // of ever escalating again, which is a deny with no decision behind it.
        s.open("claude-code", "r", "Edit", "later.py", None, None, T0 + 121, 120)
            .expect("expired entries must not hold the quota");
    }

    #[test]
    fn ids_are_distinct_within_the_same_second() {
        let mut s = EscalationStore::default();
        let a = s.open("claude-code", "r", "Edit", "gate.py", None, None, T0, 120).unwrap();
        let b = s.open("claude-code", "r", "Edit", "gate.py", None, None, T0, 120).unwrap();
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
        let (mut s, id) = store_with_one_simple_marker();
        s.decide(&id, true, "kimi-code", "role:constellation:reviewer",
                 Channel::PeerMember, Some(Independence::CrossVendor), Some("ok"), T0 + 2)
            .unwrap();
        assert!(s.claim("claude-code", "law_inject.py", T0 + 3).is_some());
        assert!(
            s.claim("claude-code", "law_inject.py", T0 + 4).is_none(),
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
        let (mut s, id) = store_with_one_simple_marker();
        s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), T0 + 5).unwrap();
        let first = s.claim("claude-code", "law_inject.py", T0 + 6);
        assert!(first.is_some(), "the approval it was granted for must be claimable");
        assert_eq!(first.unwrap().consumed_at, Some(T0 + 6));
        let second = s.claim("claude-code", "law_inject.py", T0 + 7);
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
    fn the_claim_window_is_measured_from_the_grant_not_the_open() {
        // What the window bounds is how long a GRANTED approval stays spendable, so the
        // grant is the only event it can be measured from. Anchored at `opened_at` it
        // quietly meant "the TTL remainder PLUS the window": on the live chain the median
        // ride after a grant was 4160s against a documented 600s, 63/63 escalations over,
        // and 15 of 18 cross-session relays fell inside that slack (forum 2026-08-06;
        // kimi-code reproduced it chain-only, notice 1175).
        //
        // This test pins the EVENT. The neighbouring guard
        // `the_claim_window_stays_tight_even_though_the_decision_window_grew` pins the
        // NUMBER, and passes under any anchor — which is how the drift stayed green.
        //
        // What this replaced asserted, for the record: with this same 120s fixture, that
        // `claim` at T0+4199 was `is_some()`. A 120-second escalation, still spendable 68
        // minutes after the record it belongs to had expired.
        let granted_at = T0 + 90; // late in this fixture's 120s ttl, where the slack lived
        let (mut s, id) = store_with_one_simple_marker();
        s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), granted_at).unwrap();
        assert!(
            s.claim("claude-code", "law_inject.py", granted_at + APPROVAL_CLAIM_WINDOW_SECS - 1).is_some(),
            "an approval must stay claimable through grant + window - 1"
        );

        let (mut s2, id2) = store_with_one_simple_marker();
        s2.decide(&id2, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), granted_at).unwrap();
        for t in [granted_at + APPROVAL_CLAIM_WINDOW_SECS, T0 + 4_199, T0 + 86_400] {
            assert!(
                s2.claim("claude-code", "law_inject.py", t).is_none(),
                "grant + window has closed; nothing at {t} may still ride it"
            );
        }
    }

    #[test]
    fn re_anchoring_the_claim_window_can_only_shorten_it() {
        // Re-anchoring is safe only if it tightens for EVERY input, including the ones
        // nobody typed. The replay path restores a `gate_escalation_decided` entry that
        // carries no `decided_at` as `decided_at = replay time` (`or(Some(now))`), so a
        // grant anchor ALONE would hand a restarted daemon a brand-new window an
        // arbitrary distance after the open. The record's own death is kept as a second
        // ceiling for exactly that input, which is what makes the change monotone.
        let ttl = 120;
        let old_ceiling = T0 + DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS;
        for grant in [T0, T0 + 1, T0 + 90, T0 + 119] {
            let mut s = EscalationStore::default();
            let e = s.open("claude-code", "r", "Edit", "gate.py", None, None, T0, ttl).unwrap();
            s.decide(&e.id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), grant).unwrap();
            let esc = s.get(&e.id).unwrap();
            assert!(
                esc.decided_horizon() <= old_ceiling,
                "grant at {grant}: re-anchoring LENGTHENED the ride past what it was before"
            );
            assert!(
                esc.decided_horizon() <= esc.expires_at + APPROVAL_CLAIM_WINDOW_SECS,
                "grant at {grant}: an approval outlived its own record by more than one window"
            );
        }

        // The synthesised grant, directly: bounded by the record, not by the timestamp
        // the replay invented.
        let mut s = EscalationStore::default();
        let e = s.open("claude-code", "r", "Edit", "gate.py", None, None, T0, ttl).unwrap();
        s.decide(&e.id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), T0 + 1).unwrap();
        let mut esc = s.get(&e.id).unwrap().clone();
        esc.decided_at = Some(T0 + 1_000_000);
        assert_eq!(
            esc.decided_horizon(),
            T0 + ttl + APPROVAL_CLAIM_WINDOW_SECS,
            "a replay-synthesised decided_at must not mint a fresh claim window"
        );
        assert!(
            !esc.is_claimable(T0 + 1_000_000),
            "a replay-synthesised grant must not be claimable long after the record died"
        );
    }

    #[test]
    fn a_claim_matches_on_member_and_file_together() {
        // Approving a change to the gate must not silently authorise a change to witness.py,
        // nor let a different member spend someone else's approval.
        let (mut s, id) = store_with_one_simple_marker();
        s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::LocalCli, None, Some("ok"), T0 + 1).unwrap();
        assert!(s.claim("claude-code", "witness.py", T0 + 2).is_none(), "wrong file");
        assert!(s.claim("kimi-code", "law_inject.py", T0 + 2).is_none(), "wrong member");
        assert!(s.claim("", "law_inject.py", T0 + 2).is_none(), "empty member");
        assert!(s.claim("claude-code", "", T0 + 2).is_none(), "empty file");
        assert!(s.claim("claude-code", "law_inject.py", T0 + 2).is_some(), "the exact pair");
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
        let (mut s, id) = store_with_one_simple_marker();
        let decided = s
            .decide(&id, true, "dp", "role:constellation:sovereign", Channel::OperatorSession, None, Some("legit gate edit"), T0 + 119)
            .expect("decide");
        assert_eq!(decided.decided_at, Some(T0 + 119));
        assert_ne!(
            decided.decided_at,
            Some(decided.opened_at),
            "a decision that lands 119s after the ask must not be recorded at the ask"
        );

        let now = T0 + 120;
        let claimed = s.claim("claude-code", "law_inject.py", now).expect("claim");
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
            s.open("claude-code", "r", "Edit", &format!("f{i}.py"), None, None, T0, 120).unwrap();
        }
        assert_eq!(s.len(), 10);
        // Long after they lapsed, one more open sweeps them.
        s.open("claude-code", "r", "Edit", "later.py", None, None, T0 + DEFAULT_TTL_SECS + REAP_KEEP_SECS + 1, 120)
            .unwrap();
        assert_eq!(s.len(), 1, "reap must run on open, not only in its own test");
    }

    #[test]
    fn pending_lists_oldest_first_and_hides_the_expired() {
        let mut s = EscalationStore::default();
        let old = s.open("claude-code", "r", "Edit", "a.py", None, None, T0, 120).unwrap();
        let new = s.open("kimi-code", "r", "Write", "b.py", None, None, T0 + 30, 120).unwrap();
        let ids: Vec<&str> = s.pending(T0 + 31).iter().map(|e| e.id.as_str()).collect();
        assert_eq!(ids, vec![old.id.as_str(), new.id.as_str()]);
        // `old` lapses first; the list must stop offering it as decidable.
        let ids: Vec<&str> = s.pending(T0 + 121).iter().map(|e| e.id.as_str()).collect();
        assert_eq!(ids, vec![new.id.as_str()]);
    }
}

#[cfg(test)]
mod bar_factor_tests {
    //! The bar and the factor set (dp 2026-07-30 + claude-code): the record must carry the
    //! criterion, the evidence, and whether the evidence met it — "sufficient for this
    //! context" is unauditable if the bar is never written down.
    use super::*;

    fn open_with(marker: &str) -> (EscalationStore, String) {
        let mut s = EscalationStore::default();
        let e = s
            .open("claude-code", "role:constellation:member", "Edit", marker, None, None, T0, 120)
            .expect("open");
        (s, e.id)
    }

    const T0: u64 = 1_800_000_000;

    #[test]
    fn the_bar_is_stated_at_open_and_differs_by_surface() {
        // A law renderer and the enforcement path are not the same stakes, and the record
        // must say which criterion each was judged against — inferred sufficiency is the
        // defect this exists to remove.
        let (s1, id1) = open_with("law_inject.py");
        assert_eq!(s1.get(&id1).unwrap().bar, Bar::SingleApprover);
        let (s2, id2) = open_with("pre_tool_use.py");
        assert_eq!(s2.get(&id2).unwrap().bar, Bar::SovereignPlusPeer);
        let (s3, id3) = open_with("witness.py");
        assert_eq!(s3.get(&id3).unwrap().bar, Bar::SovereignPlusPeer);
    }

    #[test]
    /// The marker is a JOIN KEY, and a member filing deliberately cannot learn it.
    ///
    /// The live failure, reproduced: a member files with its own readable string, an operator
    /// approves, and the approval is permanently unclaimable because the gate joins on a
    /// different spelling. `bar_met` is true and `is_claimable` is true the whole time — the
    /// escalation is not broken, it is simply unreachable, which from the member's side is
    /// indistinguishable from "not approved yet".
    #[test]
    fn a_marker_the_gate_never_presented_yields_an_unclaimable_approval() {
        let mut s = EscalationStore::default();
        let gate_marker = "some/dir/the/gate/matches";
        let readable = "the thing I am editing, described for a human";

        // Nothing known yet — the honest answer is None, never "fine".
        assert_eq!(s.marker_is_recognised("m", readable), None);

        // A gate claims (finding nothing) and in doing so teaches its authoritative spelling.
        assert!(s.claim("m", gate_marker, T0).is_none());
        assert_eq!(s.known_gate_markers("m"), vec![gate_marker.to_string()]);
        assert_eq!(s.marker_is_recognised("m", gate_marker), Some(true));
        assert_eq!(
            s.marker_is_recognised("m", readable),
            Some(false),
            "gates have presented another spelling for this member and not this one — a \
             different fact from 'nothing known', and collapsing them is what made the \
             original failure silent"
        );

        // THE FAILURE: file under the readable marker, approve it, watch the gate find nothing.
        let esc = s
            .open("m", "r", "Edit", readable, Some("a stated reason"), None, T0, 3600)
            .expect("open");
        let id = esc.id.clone();
        let decided = s
            .decide(&id, true, "dp", "role:constellation:sovereign",
                    Channel::OperatorSession, None, None, T0 + 5)
            .expect("approve");
        assert!(decided.bar_met(), "the approval is real and meets its bar");
        assert!(decided.is_claimable(T0 + 6), "and it is claimable — under ITS marker");
        assert!(
            s.claim("m", gate_marker, T0 + 6).is_none(),
            "APPROVED AND UNREACHABLE: the gate joins on its own spelling, so a genuine \
             operator approval buys nothing and the member cannot tell why"
        );
    }

    fn a_single_approval_meets_a_single_approver_bar() {
        let (mut s, id) = open_with("law_inject.py");
        let e = s
            .decide(&id, true, "dp", "role:constellation:sovereign", Channel::OperatorSession, None, None, T0 + 5)
            .expect("approve");
        assert!(e.bar_met());
        assert!(e.is_claimable(T0 + 6));
        // The decider's own factor was recorded — a decision is evidence first, verdict second.
        assert_eq!(e.factors.len(), 1);
        assert_eq!(e.factors[0].channel, Channel::OperatorSession);
    }

    #[test]
    fn a_sovereign_alone_on_a_two_bar_surface_permits_and_records_the_absent_peer() {
        // REPLACES `an_approval_short_of_the_bar_is_recorded_but_permits_nothing`, which
        // pinned the pre-ruling semantics: operator-alone was recorded but permitted
        // nothing. dp's decision of record (2026-08-06) inverts that — "two-bar is an
        // invitation to participate, not a blocker" — after #219 censused the old rule at
        // 0 of 66 bar-met, lifetime. The old test was not wrong; it is superseded, and it
        // is rewritten rather than deleted so the change of law stays legible here.
        let (mut s, id) = open_with("pre_tool_use.py");
        let e = s
            .decide(&id, true, "dp", "role:constellation:sovereign", Channel::OperatorSession, None, None, T0 + 5)
            .expect("approve is recorded even when short of the bar");
        assert_eq!(e.stored_status(), Status::Approved);
        assert!(e.bar_met(), "the sovereign conjunct decides; the peer one invites");
        assert!(
            e.is_claimable(T0 + 6),
            "an approval that permits nothing was the defect, not the safeguard"
        );
        assert_eq!(s.status_of(&id, T0 + 6), Status::Approved);
        let p = e.peer_participation();
        assert_eq!(p.concurred + p.dissented, 0, "no peer spoke");
        assert_eq!(p.absent, 0, "and none was invited — absent is derived from the invite list");
    }

    #[test]
    fn corroboration_accumulates_and_completes_the_bar() {
        // The constellation model in one test: peer evidence first, operator decision second,
        // and the set — never the first answer — is what the bar evaluates.
        let (mut s, id) = open_with("witness.py");
        let e = s
            .corroborate(&id, "kimi-code", "role:constellation:member", None, false, None, T0 + 3)
            .expect("peer corroboration lands while pending");
        assert_eq!(e.factors.len(), 1);
        assert_eq!(e.factors[0].channel, Channel::PeerMember);
        // Not decided yet: evidence, not a verdict.
        assert_eq!(e.stored_status(), Status::Pending);
        assert!(!e.bar_met());

        let e = s
            .decide(&id, true, "dp", "role:constellation:sovereign", Channel::OperatorSession, None, Some("reviewed the diff"), T0 + 9)
            .expect("operator decision after corroboration");
        assert_eq!(e.factors.len(), 2, "decision appends the decider's own factor");
        assert!(e.bar_met(), "operator + not-same peer meets the stated bar");
        assert!(e.is_claimable(T0 + 10));
    }

    #[test]
    fn post_decision_participation_is_recorded_and_cannot_dress_up_a_ruling() {
        // REPLACES `corroboration_freezes_at_decision`. Its concern was real and is worth
        // stating: evidence after the fact could let a weak ruling be dressed up as a
        // strong one. Under invitation semantics that risk is structurally gone rather
        // than merely accepted — `bar_met` now reads ONLY the sovereign conjunct, so a
        // late peer factor cannot move it. Participation is recorded beside the decision,
        // never folded into its authority.
        let (mut s, id) = open_with("law_inject.py");
        s.decide(&id, true, "dp", "role:constellation:sovereign", Channel::OperatorSession, None, None, T0 + 5)
            .expect("decided");
        let before = s.get(&id).unwrap().bar_met();

        let after = s
            .corroborate(&id, "kimi-code", "r", None, false, None, T0 + 6)
            .expect("a peer may participate after the ruling — that is the invitation");

        assert_eq!(after.bar_met(), before, "a late factor MUST NOT change the bar verdict");
        assert_eq!(after.peer_participation().concurred, 1, "but it is on the record");
        assert_eq!(after.stored_status(), Status::Approved, "and the ruling is untouched");
    }

    #[test]
    fn corroboration_requires_a_named_peer() {
        let (mut s, id) = open_with("law_inject.py");
        let err = s
            .corroborate(&id, "  ", "r", None, false, None, T0 + 3)
            .expect_err("anonymous evidence in an attribution record is worse than none");
        assert_eq!(err, DecideError::AnonymousDecider);
    }

    #[test]
    fn an_expired_escalation_takes_no_more_evidence() {
        let (mut s, id) = open_with("law_inject.py");
        let err = s
            .corroborate(&id, "kimi-code", "r", None, false, None, T0 + 121)
            .expect_err("expired is expired");
        assert_eq!(err, DecideError::Expired);
    }
}

#[cfg(test)]
mod ttl_tests {
    use super::*;

    const T0: u64 = 1_800_000_000;

    #[test]
    fn the_decision_window_outlives_an_asynchronous_peer() {
        // The regression this guards is not "the number is 3600". It is that a peer reached by
        // a mesh notice, on its own schedule, can still rule when it gets there. Two minutes
        // could not, and that is how escalation 8bb08a85 expired unruled on 2026-07-30.
        let mut s = EscalationStore::default();
        let e = s.open("claude-code", "r", "Edit", "gate.py", None, None, T0, DEFAULT_TTL_SECS).unwrap();
        let ten_minutes_later = T0 + 600;
        assert_eq!(
            s.status_of(&e.id, ten_minutes_later),
            Status::Pending,
            "a peer that answers ten minutes later must still find something to rule"
        );
        assert!(s
            .decide(&e.id, true, "kimi-code", "role:constellation:reviewer",
                    Channel::PeerMember, Some(crate::arbiter::Independence::CrossMember),
                    Some("reviewed"), ten_minutes_later)
            .is_ok());
    }

    #[test]
    fn a_longer_window_widens_no_permission_while_it_is_open() {
        // The whole justification for being generous: pending permits NOTHING, so the extra
        // time buys a chance of an answer and grants nothing in the meantime. If this ever
        // fails, the generosity became a hole.
        let mut s = EscalationStore::default();
        let e = s.open("claude-code", "r", "Edit", "gate.py", None, None, T0, DEFAULT_TTL_SECS).unwrap();
        for t in [T0 + 1, T0 + 600, T0 + 3599] {
            assert_eq!(s.status_of(&e.id, t), Status::Pending);
            assert!(!s.status_of(&e.id, t).permits_write(), "pending permitted a write at {t}");
            assert!(s.claim("claude-code", "gate.py", t).is_none(), "claimable while pending");
        }
    }

    #[test]
    fn the_claim_window_stays_tight_even_though_the_decision_window_grew() {
        // The two bound different risks and must not drift together. Decision window: how long
        // someone has to answer (harmless). Claim window: how long a GRANTED approval can be
        // ridden (not harmless). Widening the first must not widen the second.
        assert!(
            APPROVAL_CLAIM_WINDOW_SECS <= 900,
            "the claim window bounds how long a granted approval stays spendable; it must not \
             be relaxed alongside the decision window"
        );
    }

    #[test]
    fn an_undecided_escalation_still_expires() {
        // Generous is not unbounded. An ask nobody ever answers must still go stale, or the
        // store accumulates open grants forever and 'pending' stops meaning anything.
        let mut s = EscalationStore::default();
        let e = s.open("claude-code", "r", "Edit", "gate.py", None, None, T0, DEFAULT_TTL_SECS).unwrap();
        assert_eq!(s.status_of(&e.id, T0 + DEFAULT_TTL_SECS), Status::Expired);
        assert!(s
            .decide(&e.id, true, "kimi-code", "r", Channel::PeerMember, None, Some("late"),
                    T0 + DEFAULT_TTL_SECS + 1)
            .is_err());
    }
}

//! The adjudicator contract — `PRD_ADJUDICATOR_LADDER` §3.1, and the instrument §4.3 says is
//! the actual mechanism of evolution.
//!
//! dp's directive (§0, verbatim): *"the policy entity AGENT is still intended to slot in
//! between heuristic slot and human, as a middle escalation layer. and even that can be a
//! neural net, and THEN an agent."* This module is the seam that makes such a rung droppable
//! in without rebuilding anything around it, plus the measurement that decides whether it has
//! earned promotion.
//!
//! WHY THE MEASUREMENT COMES BEFORE THE REASONER. §4.3 is blunt: *"an advisory rung that is
//! never measured never earns promotion. It sits at stage A forever, recording verdicts nobody
//! reads."* The failure mode for this fleet is not that a reasoner is hard to wire; it is that
//! a wired reasoner produces plausible verdicts nobody compares to anything, and coherence
//! substitutes for measurement. So the instrument exists first, and the first rung behind it is
//! deliberately weak.
//!
//! **The baseline rung is a CONTROL ARM, not a placeholder.** "The agent agreed with the
//! operator 80% of the time" is not a result until you know what agreeing-by-reflex scores on
//! the same cases. A rung that always declines, or always concurs, can post a high number on a
//! population that is mostly one answer. `BaselineRung` is the thing any future reasoner must
//! beat, and `AgreementReport` refuses to report a rate without the denominator that makes it
//! readable.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;

/// What a rung concluded. Reuses the existing verdict vocabulary rather than minting a third
/// spelling: `tool_witness_adjudication`'s `ADJUDICATION_VERDICTS` already carries `deferred`,
/// which is the same act as `Decline`, and §3.1 warns that a third spelling of one verdict is
/// how a vocabulary split starts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Decision {
    Approve,
    Deny,
    /// FIRST-CLASS, NEVER AN ERROR. A rung that cannot form a view must be able to say so and
    /// pass the case up without the escalation entering a failure state. Today a rung that
    /// timed out and a rung that abstained would be indistinguishable, and the second most
    /// dangerous thing this interface could do is let silence read as assent.
    ///
    /// Falsifier: `a_verdict_refuses_the_four_shapes_that_would_make_it_unreadable` — a
    /// decline without a named reason is refused at construction.
    Decline,
}

/// WHY a rung declined. §3.2 requires decline, timeout and unreachable to be three
/// distinguishable records, *"and none of them reads as concurrence"*.
///
/// The distinction is not bookkeeping. An `rc=124` is anti-evidence — it says the rung never
/// saw the case — while `Abstained` says it looked and had no view, and `NotAuthorised` says it
/// was never entitled to an opinion at this consequence. Collapsing them would make the
/// agreement measurement count a dead transport as a considered abstention.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Decline {
    /// It read the case and has no view worth recording.
    Abstained,
    /// It has a view, and its own confidence is under the threshold the LADDER holds for it.
    BelowThreshold,
    /// The case exceeds the consequence this rung may decide. Checked BEFORE the rung is
    /// asked (§3.2), so a rung is never handed a bundle it could not have been permitted to
    /// decide — but recorded here too, because the record must say why nothing was asked.
    NotAuthorised,
    /// The rung could not be reached at all.
    Unreachable,
    /// The rung was reached and did not answer in time. Distinct from `Unreachable` because
    /// the case may have been half-processed, and distinct from `Abstained` because nothing
    /// was considered.
    TimedOut,
    /// The bundle itself was unreadable — e.g. the act text is UNAVAILABLE (#1066), so there
    /// is nothing to have a view ABOUT. A rung that "approves" a case it cannot see is the
    /// filter this interface exists to make visible.
    EvidenceInsufficient,
}

/// One rung's answer. §3.1's contract, with its four invariants enforced at construction
/// rather than trusted to callers.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Verdict {
    pub rung: String,
    pub decision: Decision,
    pub declined_because: Option<Decline>,
    /// Required to APPROVE, optional to deny. This asymmetry already exists on the operator
    /// and peer doors and is deliberate: refusing is the default and costs nothing to explain;
    /// PERMITTING is what a later reader has to weigh. §3.1 says not to invent a second
    /// asymmetry, so this one is copied rather than reasoned about afresh.
    pub rationale: Option<String>,
    /// REPORTED, NEVER SELF-THRESHOLDED. `arbiter.rs` holds the same line for `Independence`
    /// — "recorded, never thresholded here". A rung that decided its own sufficiency would be
    /// the `satisfied_by` inversion CLAUDE.md names: the surface smuggling in a verdict that
    /// belongs to the relying party.
    ///
    /// Falsifier: the threshold lives in `promotion_verdict`, and
    /// `promotion_refuses_below_threshold_and_quotes_what_it_measured` holds it there — a
    /// verdict carrying its own cutoff would make that function's argument redundant.
    pub confidence: f64,
    /// WHAT IT ACTUALLY READ — not what it was offered. This is the whole auditability of a
    /// rung, and the only field that separates a rung from a filter wearing an adjudicator's
    /// clothes. "The rung and the human disagreed" is uninteresting until you can see that the
    /// rung never opened the payload.
    pub consulted: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum VerdictError {
    ApprovalWithoutRationale,
    ConfidenceOutOfRange(f64),
    DecideWithDeclineReason,
    DeclineWithoutReason,
    NothingConsulted,
}

impl std::fmt::Display for VerdictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ApprovalWithoutRationale => write!(
                f,
                "a rung may deny without explaining itself and may not APPROVE without: \
                 permitting is what a later reader has to weigh"
            ),
            Self::ConfidenceOutOfRange(c) => {
                write!(f, "confidence {c} is outside [0,1] and cannot be compared to a threshold")
            }
            Self::DecideWithDeclineReason => write!(
                f,
                "a decided verdict carries no decline reason — a record that says both is one \
                 a census must guess at"
            ),
            Self::DeclineWithoutReason => write!(
                f,
                "a decline must say WHICH kind: abstained, timed out and unreachable are three \
                 different facts and none of them may read as concurrence"
            ),
            Self::NothingConsulted => write!(
                f,
                "a verdict that consulted nothing is a filter's output, not an adjudication"
            ),
        }
    }
}

impl Verdict {
    /// Build and CHECK. The invariants are §3.1's, and they are enforced here because a rung
    /// is the kind of component that gets reimplemented per vendor — each reimplementation an
    /// opportunity to drop the one field that made the record auditable.
    pub fn new(
        rung: impl Into<String>,
        decision: Decision,
        declined_because: Option<Decline>,
        rationale: Option<String>,
        confidence: f64,
        consulted: Vec<String>,
    ) -> Result<Self, VerdictError> {
        if !(0.0..=1.0).contains(&confidence) || confidence.is_nan() {
            return Err(VerdictError::ConfidenceOutOfRange(confidence));
        }
        match (decision, &declined_because) {
            (Decision::Decline, None) => return Err(VerdictError::DeclineWithoutReason),
            (Decision::Approve | Decision::Deny, Some(_)) => {
                return Err(VerdictError::DecideWithDeclineReason)
            }
            _ => {}
        }
        if decision == Decision::Approve
            && rationale.as_ref().map(|r| r.trim().is_empty()).unwrap_or(true)
        {
            return Err(VerdictError::ApprovalWithoutRationale);
        }
        if consulted.is_empty() {
            return Err(VerdictError::NothingConsulted);
        }
        Ok(Self { rung: rung.into(), decision, declined_because, rationale, confidence, consulted })
    }

    /// Does this verdict PERMIT anything by itself? No — and the method exists so that the
    /// answer is written down once rather than re-derived at each call site. An advisory rung
    /// decides nothing; its verdict is a factor, and a factor permits nothing (§4.2).
    pub fn permits_write(&self) -> bool {
        false
    }

    /// The witnessed shape (§3.4). Every rung's verdict is recorded whether or not it decided
    /// anything, because advisory verdicts ARE the measurement and an unrecorded advisory
    /// verdict is an unmeasurable one.
    pub fn to_row(&self, escalation_id: &str, ladder_generation: u64) -> Value {
        json!({
            "escalation_id": escalation_id,
            "rung": self.rung,
            "decision": self.decision,
            // Explicit null when decided, so a census can separate "decided" from "declined
            // for a reason this record forgot to carry".
            "declined_because": self.declined_because,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "consulted": self.consulted,
            "ladder_generation": ladder_generation,
            // Stated on every row: an advisory verdict that could be mistaken for a grant is
            // the one way this surface could cause harm.
            "permits_write": false,
        })
    }
}

/// One rung. Deliberately a trait over the BUNDLE rather than over the escalation: a rung that
/// can reach past its evidence into daemon state is a rung whose `consulted` list is a fiction.
pub trait Adjudicator {
    fn rung_id(&self) -> &str;
    fn adjudicate(&self, bundle: &Value) -> Verdict;
}

/// The control arm: a rung with NO reasoner behind it.
///
/// It exists to make the instrument measurable before anything intelligent is wired in, and it
/// stays afterwards as the baseline every reasoner must beat. Its verdicts are deliberately
/// weak and its confidence deliberately low — what it offers is that it reads the same bundle
/// a real rung would and reports honestly what it could and could not see.
///
/// It NEVER approves. An approval from a rung that cannot read the act would be exactly the
/// filter-wearing-adjudicator's-clothes failure §3.1 warns about, and a baseline that could
/// approve would also make the control arm dangerous rather than merely uninformative.
///
/// Falsifier: `the_baseline_separates_unreadable_evidence_from_an_abstention_and_never_approves`
/// asserts the decision on every arm, and
/// `the_baseline_rung_can_actually_read_a_bundle_this_daemon_produces` pins it against a
/// bundle this daemon really emits.
pub struct BaselineRung;

pub const BASELINE_RUNG_ID: &str = "baseline:v1";

impl Adjudicator for BaselineRung {
    fn rung_id(&self) -> &str {
        BASELINE_RUNG_ID
    }

    fn adjudicate(&self, bundle: &Value) -> Verdict {
        let mut consulted = vec!["escalation.marker".to_string()];
        let ev = &bundle["escalation"];

        // Can the act be READ at all? Rows opened before #1066 retained only the digest, so
        // there may be nothing to have a view about. That is an evidence failure,
        // not an abstention, and the two must not be recorded as one thing.
        let act_unreadable = bundle
            .get("act_text_source")
            .and_then(Value::as_str)
            .map(|s| s.starts_with("UNAVAILABLE"))
            .unwrap_or(true);
        consulted.push("act_text_source".to_string());
        if act_unreadable {
            return Verdict::new(
                BASELINE_RUNG_ID,
                Decision::Decline,
                Some(Decline::EvidenceInsufficient),
                Some("the act text is not retained on this escalation (it predates #1066), \
                      so there is nothing here to form a view about".into()),
                0.0,
                consulted,
            )
            .expect("baseline decline is well-formed by construction");
        }

        let effect = &bundle["write_effect"];
        consulted.push("write_effect".to_string());
        if effect.is_null() {
            return Verdict::new(
                BASELINE_RUNG_ID,
                Decision::Decline,
                Some(Decline::Abstained),
                Some("the act is not copy-shaped, so this rung — which reads only the diff — \
                      has no view".into()),
                0.0,
                consulted,
            )
            .expect("baseline decline is well-formed by construction");
        }

        // The one thing a diff-reader can say without reasoning: a write that changes nothing
        // against the copy now enforcing is a no-op. It is still not an approval — the
        // baseline never approves — but it is a genuine observation, and the cheapest approval
        // an operator will ever give is the one most likely to mean something went wrong
        // upstream.
        consulted.push("write_effect.identical_to_enforcing".to_string());
        let no_op = effect["identical_to_enforcing"].as_bool().unwrap_or(false);
        let prior = &bundle["prior_on_this_marker"];
        consulted.push("prior_on_this_marker.denied".to_string());
        let prior_denials = prior["denied"].as_u64().unwrap_or(0);
        let asserted = ev["asker_basis"].as_str() == Some("Asserted");
        consulted.push("escalation.asker_basis".to_string());

        let note = format!(
            "diff vs the enforcing copy: +{} -{}{}{}",
            effect["added_lines"].as_u64().unwrap_or(0),
            effect["removed_lines"].as_u64().unwrap_or(0),
            if no_op { "; identical to what is enforcing" } else { "" },
            if prior_denials > 0 {
                format!("; {prior_denials} prior deny(s) on this marker")
            } else {
                String::new()
            },
        );

        // Confidence is REPORTED, not thresholded here. It is low on purpose: this rung read a
        // diff and counted rows. An asserted asker lowers it further, because the name the
        // case is filed under was never proven.
        let confidence = if asserted { 0.10 } else { 0.20 };
        Verdict::new(
            BASELINE_RUNG_ID,
            Decision::Decline,
            Some(Decline::Abstained),
            Some(format!(
                "{note}. This rung has no reasoner: it reports what it read and defers. \
                 It exists as the control arm any reasoning rung must beat."
            )),
            confidence,
            consulted,
        )
        .expect("baseline decline is well-formed by construction")
    }
}

/// One rung's verdict placed beside what the human actually decided.
#[derive(Debug, Clone, PartialEq)]
pub struct Comparison {
    pub act_kind: String,
    pub rung: Decision,
    pub human: Decision,
    pub confidence: f64,
    pub escalation_id: String,
}

impl Comparison {
    /// Agreement counts only where BOTH parties decided. A decline is not a wrong answer and
    /// must not be scored as one — counting it as disagreement would punish exactly the
    /// behaviour §3.1 made first-class, and a rung optimised against that metric learns to
    /// guess instead of defer.
    pub fn is_comparable(&self) -> bool {
        self.rung != Decision::Decline && self.human != Decision::Decline
    }
    pub fn agreed(&self) -> bool {
        self.is_comparable() && self.rung == self.human
    }
}

/// Agreement with the human decision, PER ACT KIND, with the disagreements preserved.
///
/// §4.3's three guards, each earned elsewhere in this repo:
///
/// 1. **the denominator names its population** — a bare rate is true of more than one
///    population, and this fleet has published windowed rates as whole-chain facts twice;
/// 2. **both arms must be able to fire** — a promotion criterion that can only be satisfied is
///    not a criterion, so [`promotion_verdict`] returns a refusal that QUOTES the number;
/// 3. **per act kind** — an aggregate hides the mixture, and a rung at 95% overall may be at
///    60% on the one kind that matters.
#[derive(Debug, Clone, PartialEq)]
pub struct KindStats {
    pub compared: usize,
    pub agreed: usize,
    pub declined: usize,
    /// Kept, not counted: §4.3 calls the disagreements *"the payload, not the residue"* — a
    /// rung that disagreed and was right is the strongest argument for promotion there is.
    pub disagreements: Vec<Comparison>,
}

impl KindStats {
    /// `None` rather than 0.0 when nothing was comparable. A rate of zero and no data are
    /// different facts, and only one of them is an argument against promotion.
    pub fn agreement_rate(&self) -> Option<f64> {
        (self.compared > 0).then(|| self.agreed as f64 / self.compared as f64)
    }
}

#[derive(Debug, Clone, Default)]
pub struct AgreementReport {
    pub by_kind: BTreeMap<String, KindStats>,
}

impl AgreementReport {
    pub fn from_comparisons(rows: impl IntoIterator<Item = Comparison>) -> Self {
        let mut by_kind: BTreeMap<String, KindStats> = BTreeMap::new();
        for c in rows {
            let e = by_kind.entry(c.act_kind.clone()).or_insert(KindStats {
                compared: 0,
                agreed: 0,
                declined: 0,
                disagreements: Vec::new(),
            });
            if !c.is_comparable() {
                e.declined += 1;
                continue;
            }
            e.compared += 1;
            if c.agreed() {
                e.agreed += 1;
            } else {
                e.disagreements.push(c);
            }
        }
        Self { by_kind }
    }

    pub fn to_json(&self) -> Value {
        json!({
            "by_kind": self.by_kind.iter().map(|(k, s)| {
                json!({
                    "act_kind": k,
                    // The denominator travels WITH the rate, always.
                    "compared": s.compared,
                    "agreed": s.agreed,
                    "declined": s.declined,
                    "agreement_rate": s.agreement_rate(),
                    "disagreements": s.disagreements.iter().map(|d| json!({
                        "escalation_id": d.escalation_id,
                        "rung": d.rung,
                        "human": d.human,
                        "confidence": d.confidence,
                    })).collect::<Vec<_>>(),
                })
            }).collect::<Vec<_>>(),
        })
    }
}

/// Minimum comparisons before a rate is allowed to argue anything. Three agreements out of
/// three is not evidence of 100%; it is evidence of three.
pub const MIN_COMPARISONS_FOR_PROMOTION: usize = 20;

/// Whether the measured record supports promoting this rung for this act kind — and, when it
/// does not, WHY, quoting the number.
///
/// This is the arm that must be able to fail. A promotion gate that can only say yes is
/// ceremony, and §4.3 requires the refusal to quote what it measured so that a later reader
/// can check the gate rather than trust it.
pub fn promotion_verdict(stats: &KindStats, threshold: f64) -> Result<String, String> {
    match stats.agreement_rate() {
        None => Err(format!(
            "REFUSED: nothing comparable. {} verdict(s) declined and none decided, so there is \
             no agreement to measure — an unmeasured rung is not a rung with a perfect record",
            stats.declined
        )),
        Some(_) if stats.compared < MIN_COMPARISONS_FOR_PROMOTION => Err(format!(
            "REFUSED: only {} comparable decision(s), under the {} this gate requires. A rate \
             over too few cases is a statement about the cases, not about the rung",
            stats.compared, MIN_COMPARISONS_FOR_PROMOTION
        )),
        Some(rate) if rate < threshold => Err(format!(
            "REFUSED: measured agreement {:.3} over {} comparable decision(s), under the {:.3} \
             required. {} disagreement(s) are preserved and are the thing to read next",
            rate,
            stats.compared,
            threshold,
            stats.disagreements.len()
        )),
        Some(rate) => Ok(format!(
            "measured agreement {:.3} over {} comparable decision(s), at or above {:.3}. \
             Promotion remains an OPERATOR act at the ladder store's ceremony tier — this \
             function reports evidence and grants nothing",
            rate, stats.compared, threshold
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn consulted() -> Vec<String> {
        vec!["escalation.marker".into()]
    }

    /// §3.1's invariants, each of which is a defect this repo has paid for somewhere else.
    #[test]
    fn a_verdict_refuses_the_four_shapes_that_would_make_it_unreadable() {
        // Approve with no rationale. The asymmetry is deliberate and copied, not invented:
        // denying is the default and costs nothing to explain; permitting is what a later
        // reader must weigh.
        assert_eq!(
            Verdict::new("r", Decision::Approve, None, None, 0.9, consulted()),
            Err(VerdictError::ApprovalWithoutRationale)
        );
        // ... and denying without one is FINE. If this ever starts failing, someone has
        // invented the second asymmetry §3.1 warns against.
        assert!(Verdict::new("r", Decision::Deny, None, None, 0.9, consulted()).is_ok());

        assert_eq!(
            Verdict::new("r", Decision::Deny, None, None, 1.5, consulted()),
            Err(VerdictError::ConfidenceOutOfRange(1.5))
        );
        assert_eq!(
            Verdict::new("r", Decision::Decline, None, None, 0.0, consulted()),
            Err(VerdictError::DeclineWithoutReason)
        );
        assert_eq!(
            Verdict::new("r", Decision::Deny, Some(Decline::Abstained), None, 0.5, consulted()),
            Err(VerdictError::DecideWithDeclineReason)
        );
        // A verdict that consulted nothing is a filter's output. This is the field that makes
        // "the rung and the human disagreed" worth reading at all.
        assert_eq!(
            Verdict::new("r", Decision::Deny, None, None, 0.5, vec![]),
            Err(VerdictError::NothingConsulted)
        );
    }

    /// NO VERDICT PERMITS A WRITE, and the record says so on its face.
    #[test]
    fn an_advisory_verdict_permits_nothing_and_its_row_states_that() {
        let v = Verdict::new(
            "r", Decision::Approve, None, Some("read the diff".into()), 0.99, consulted(),
        )
        .unwrap();
        assert!(!v.permits_write(), "even a confident approval from a rung grants nothing");
        let row = v.to_row("abc123", 7);
        assert_eq!(row["permits_write"], json!(false));
        assert_eq!(row["ladder_generation"], json!(7));
        assert!(row["consulted"].as_array().is_some_and(|a| !a.is_empty()));
        // Explicit null rather than omitted, so a census can tell a decided row from one whose
        // decline reason was dropped.
        assert!(row.get("declined_because").is_some() && row["declined_because"].is_null());
    }

    fn bundle_with(effect: Value, act_readable: bool) -> Value {
        json!({
            "escalation": {"marker": "plugins/*/hooks", "asker_basis": "Asserted"},
            "act_text_source": if act_readable {
                "retained at open — the exact text act_digest binds"
            } else {
                "UNAVAILABLE: only act_digest is retained, and a hash is not readable evidence"
            },
            "write_effect": effect,
            "prior_on_this_marker": {"denied": 0},
        })
    }

    /// The baseline NEVER approves, and it distinguishes "I could not see it" from "I looked
    /// and have no view". Those are the two facts §3.2 refuses to let collapse.
    #[test]
    fn the_baseline_separates_unreadable_evidence_from_an_abstention_and_never_approves() {
        let r = BaselineRung;

        let unreadable = r.adjudicate(&bundle_with(Value::Null, false));
        assert_eq!(unreadable.decision, Decision::Decline);
        assert_eq!(unreadable.declined_because, Some(Decline::EvidenceInsufficient));
        assert!(unreadable.consulted.contains(&"act_text_source".to_string()),
                "and it must say it looked: {:?}", unreadable.consulted);

        let no_effect = r.adjudicate(&bundle_with(Value::Null, true));
        assert_eq!(no_effect.declined_because, Some(Decline::Abstained),
                   "a non-copy act is an abstention, not an evidence failure");

        let with_diff = r.adjudicate(&bundle_with(
            json!({"added_lines": 15, "removed_lines": 2, "identical_to_enforcing": false}),
            true,
        ));
        assert_eq!(with_diff.decision, Decision::Decline, "the baseline never decides");
        assert!(with_diff.rationale.as_deref().unwrap().contains("+15 -2"),
                "it reports what it read: {:?}", with_diff.rationale);
        assert!(with_diff.confidence < 0.5, "a diff-reader with no reasoner is not confident");
        assert!(with_diff.consulted.len() >= 4, "and lists the fields it used: {:?}",
                with_diff.consulted);
    }

    fn cmp(kind: &str, rung: Decision, human: Decision, id: &str) -> Comparison {
        Comparison {
            act_kind: kind.into(),
            rung,
            human,
            confidence: 0.5,
            escalation_id: id.into(),
        }
    }

    /// A DECLINE IS NOT A WRONG ANSWER.
    ///
    /// If declines were scored as disagreement, a rung optimised against this metric would
    /// learn to guess rather than defer — destroying the one behaviour §3.1 made first-class.
    /// So they are counted separately and excluded from the denominator.
    #[test]
    fn declines_are_counted_but_never_scored_as_disagreement() {
        let rep = AgreementReport::from_comparisons(vec![
            cmp("gov.write", Decision::Deny, Decision::Deny, "a"),
            cmp("gov.write", Decision::Approve, Decision::Deny, "b"),
            cmp("gov.write", Decision::Decline, Decision::Deny, "c"),
        ]);
        let s = &rep.by_kind["gov.write"];
        assert_eq!((s.compared, s.agreed, s.declined), (2, 1, 1));
        assert_eq!(s.agreement_rate(), Some(0.5), "the decline is out of the denominator");
        assert_eq!(s.disagreements.len(), 1, "and the disagreement is KEPT, not tallied away");
        assert_eq!(s.disagreements[0].escalation_id, "b");

        // Per act kind, because an aggregate hides the mixture.
        let split = AgreementReport::from_comparisons(vec![
            cmp("gov.write", Decision::Deny, Decision::Deny, "a"),
            cmp("scope.grant", Decision::Approve, Decision::Deny, "b"),
        ]);
        assert_eq!(split.by_kind.len(), 2);
        assert_eq!(split.by_kind["scope.grant"].agreement_rate(), Some(0.0));
    }

    /// A RATE OF ZERO AND NO DATA ARE DIFFERENT FACTS, and only one argues against promotion.
    /// This is the same distinction as an absent measurement versus a measured absence, which
    /// this fleet has now conflated in three separate surfaces.
    #[test]
    fn a_rung_that_only_declines_has_no_rate_and_cannot_be_promoted_on_a_perfect_record() {
        let rep = AgreementReport::from_comparisons(vec![
            cmp("gov.write", Decision::Decline, Decision::Deny, "a"),
            cmp("gov.write", Decision::Decline, Decision::Approve, "b"),
        ]);
        let s = &rep.by_kind["gov.write"];
        assert_eq!(s.agreement_rate(), None, "nothing comparable is not 0.0 and not 1.0");
        let verdict = promotion_verdict(s, 0.9);
        let why = verdict.unwrap_err();
        assert!(why.contains("nothing comparable"), "{why}");
        assert!(why.contains("not a rung with a perfect record"), "{why}");
    }

    /// THE NEGATIVE ARM MUST BE ABLE TO FIRE, AND MUST QUOTE THE NUMBER.
    ///
    /// §4.3: a promotion criterion that can only be satisfied is not a criterion. A refusal
    /// that does not say what it measured asks the reader to trust the gate instead of
    /// checking it.
    #[test]
    fn promotion_refuses_below_threshold_and_quotes_what_it_measured() {
        let mut rows = Vec::new();
        for i in 0..30 {
            // 20 of 30 agree => 0.667, under a 0.9 bar.
            let rung = if i < 20 { Decision::Deny } else { Decision::Approve };
            rows.push(cmp("gov.write", rung, Decision::Deny, &format!("e{i}")));
        }
        let rep = AgreementReport::from_comparisons(rows);
        let s = &rep.by_kind["gov.write"];
        let why = promotion_verdict(s, 0.9).unwrap_err();
        assert!(why.starts_with("REFUSED"), "{why}");
        assert!(why.contains("0.667"), "the refusal must quote the measured rate: {why}");
        assert!(why.contains("30 comparable"), "and its denominator: {why}");

        // POSITIVE CONTROL: the same gate passes when the evidence supports it, or the test
        // above would pass against a function that refuses everything.
        let good: Vec<_> = (0..30)
            .map(|i| cmp("gov.write", Decision::Deny, Decision::Deny, &format!("g{i}")))
            .collect();
        let rep2 = AgreementReport::from_comparisons(good);
        let ok = promotion_verdict(&rep2.by_kind["gov.write"], 0.9).unwrap();
        assert!(ok.contains("1.000"), "{ok}");
        assert!(ok.contains("grants nothing"),
                "even a pass must say promotion stays an operator act: {ok}");
    }

    /// Three-for-three is evidence of three. A rate over too few cases is a statement about
    /// the cases.
    #[test]
    fn a_short_record_is_refused_even_when_it_is_perfect() {
        let rows: Vec<_> = (0..3)
            .map(|i| cmp("gov.write", Decision::Deny, Decision::Deny, &format!("s{i}")))
            .collect();
        let rep = AgreementReport::from_comparisons(rows);
        let why = promotion_verdict(&rep.by_kind["gov.write"], 0.9).unwrap_err();
        assert!(why.contains("only 3 comparable"), "{why}");
        assert!(why.contains(&MIN_COMPARISONS_FOR_PROMOTION.to_string()), "{why}");
    }
}

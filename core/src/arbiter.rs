//! Appeal arbitration — the reasoning wire, stubbed honestly.
//!
//! dp, 2026-07-27: "meaningful appeals do require a reasoning arbiter. i don't think we
//! have that wire yet." … "leave agentic entity as a stub, but provide as much scaffolding
//! as practical. and, if you can wire a 'not-same' agent in the role… well, that is where
//! we are going with it."
//!
//! WHAT AN APPEAL IS FOR, AND WHY IT NEEDED AN ARBITER BEFORE IT COULD PAY. A member that
//! believes a deny was wrong has exactly two honest moves: comply and dispute, or comply
//! and drop it. The dishonest third — reach the denied end another way — is now scored
//! (`recast-after-deny`). But disputing only *means* something if somebody reads the
//! dispute. Until this module exists, `appeal-filed` deliberately scores the same as plain
//! compliance: the member is credited for not routing around, and the extra credit waits.
//! Paying 1.0 for an unread assertion would make the top of the conduct scale purchasable
//! by anyone willing to type, which is a worse incentive than the one it replaced.
//!
//! THE ONE CONSTRAINT THAT IS NOT A STUB: **NOT-SAME**.
//!
//! Everything else here is scaffolding and will be rewritten. This is not. An arbiter must
//! be a different entity from the appellant, and — for a real ruling — from the party whose
//! gate issued the deny. The whole day's evidence is that an agent cannot see its own blind
//! spots: Thor found the inventory reporting OK over dead gates, kimi found the tests that
//! were in the wrong room, codex found the unenforced lists, dp found the appeal paying for
//! itself. Not one of those was self-detectable, and every one came from a *differently
//! placed* reader. An arbiter drawn from the same model, the same session, or the same
//! interests reproduces the blind spot it exists to cover.
//!
//! So `NotSame` is checked structurally and the check fails CLOSED. A self-arbitrated
//! appeal is not merely discouraged; it cannot be recorded.
//!
//! HETEROGENEITY IS A SPECTRUM AND WE ONLY MEASURE THE FLOOR. Distinct plugin_id is a weak
//! proxy for "differently placed" — codex and claude are different vendors and genuinely
//! see differently, while two claude sessions share almost everything but a context window.
//! The floor is enforced here; the gradient is recorded (`independence`) so a relying party
//! can weigh a ruling rather than being handed a verdict. That is the same
//! evidence-not-declaration move the rest of this codebase is built on.

use serde::{Deserialize, Serialize};

/// Why an arbiter is or is not admissible for a given appeal.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "verdict")]
pub enum Eligibility {
    /// Admissible. `independence` grades how differently-placed the arbiter is — not a
    /// threshold, an input to whoever reads the ruling.
    Eligible { independence: Independence },
    /// Structurally inadmissible. Fails closed.
    Refused { reason: String },
}

/// How different is "different"? Recorded, never thresholded here.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Independence {
    /// Different member AND different vendor lineage (e.g. codex judging claude). The
    /// strongest signal available locally: different training, different failure modes,
    /// different things invisible.
    CrossVendor,
    /// Different member, same lineage (e.g. kimi judging claude — both Claude-Code
    /// lineage). Genuinely separate context and evidence; correlated blind spots.
    CrossMember,
}

// THERE IS NO CrossSession TIER, DELIBERATELY.
//
// There was one. It was documented as "the weakest admissible form" and the code refused it
// one clause earlier — `arbiter == appellant` returns Refused before any session comparison
// can run — so the variant, the branch that built it, and the fields it read were all
// unreachable. kimi-code, reviewing: "the current state documents a behavior the code
// doesn't have." Worse, the test that claimed to prove absent sessions fail closed used the
// SAME plugin_id for both parties, so it exited at clause 1 and would still have passed with
// the entire session branch deleted. My own standard, turned around: the assertion and the
// mechanism were in different rooms.
//
// Offered the choice of making the tier real or removing it, removing it is the one that
// matches the doctrine. A second session of the same member is the same model, the same
// training, the same dispositions, differing only in what it has read. It is precisely the
// entity that cannot see this entity's blind spots. Every genuine catch on this codebase
// came from a differently-PLACED reader — kimi, codex, dp, Thor — and none from another
// session of the same member. Admitting one, even at the bottom of a gradient, would let a
// member arbitrate its own appeal by opening a second terminal, which is what NotSame exists
// to prevent.

/// The parties to an appeal, as the daemon knows them.
#[derive(Debug, Clone)]
pub struct AppealParties<'a> {
    /// Who filed the appeal — the member the deny landed on.
    pub appellant: &'a str,
    /// Which gate issued the deny (`plugin-gate:<id>`, `hestia-gate`, or a rule id).
    pub deny_adjudicator: Option<&'a str>,
    /// Who proposes to rule.
    pub arbiter: &'a str,
}

/// Vendor lineage, for the independence gradient. Deliberately coarse and openly
/// incomplete: an unknown id is treated as its own lineage rather than assumed to match,
/// because guessing "same" would inflate independence and guessing "different" would
/// deflate it — and the first error is the dangerous one.
fn lineage(plugin_id: &str) -> Option<&'static str> {
    match plugin_id {
        id if id.starts_with("claude") => Some("anthropic"),
        id if id.starts_with("codex") => Some("openai"),
        id if id.starts_with("kimi") => Some("moonshot"),
        id if id.starts_with("gemini") => Some("google"),
        _ => None,
    }
}

/// UNRECOGNISED IS NOT INDEPENDENT — it is unrecognised.
///
/// Found live, on the first real appeal this surface ever handled. hestia's member registry
/// holds every entity that has ever connected: reasoning harnesses, but also timers,
/// watchers and plugins. `agent-inventory` — an hourly cron that reads config files — was
/// selected as arbiter and graded **cross_vendor**, the STRONGEST independence tier, purely
/// because "agent-inventory" matched no known vendor prefix and `!=` therefore read as
/// "maximally different". The receipt said "routed to a not-same arbiter."
///
/// It was not-same. It also cannot reason, cannot read an appeal, and will never rule. The
/// appeal would have sat routed-and-answered-looking forever: the exact defect this codebase
/// keeps finding — a reassuring state bit-identical to the null state. Worse than an
/// unrouted appeal, because an unrouted one says so.
///
/// So an arbiter must be a RECOGNISED reasoning lineage. This is a real restriction and it
/// fails closed: a new harness cannot arbitrate until it is added here, which is a
/// deliberate cost. The alternative — admitting anything unrecognised — is what just
/// happened, and it dressed a cron job as the most independent judge on the machine.
///
/// This is emphatically not a competence claim. It is the floor: we know what this entity
/// is. Whether it reasons WELL is what `rationale` and `independence` are for, and that
/// judgement belongs to whoever reads the ruling.
fn is_recognised_reasoner(plugin_id: &str) -> bool {
    lineage(plugin_id).is_some()
}

/// Can this arbiter rule on this appeal?
///
/// Fails closed on every ambiguity. The refusals are structural facts, not judgements
/// about quality — a competent arbiter that happens to be the appellant is still refused.
pub fn eligibility(p: &AppealParties<'_>) -> Eligibility {
    // 1. NOT THE APPELLANT. The whole point.
    if p.arbiter == p.appellant {
        return Eligibility::Refused {
            reason: format!(
                "'{}' cannot arbitrate its own appeal — an appeal upheld by its filer is an \
                 assertion wearing a verdict's clothes, and the scale would pay 1.0 for it",
                p.arbiter
            ),
        };
    }
    // 2. NOT THE GATE THAT DENIED. A gate ruling on a dispute about its own decision is
    //    reviewing itself one layer up. Weaker than (1) — the gate is not the appellant —
    //    but the same shape, and today's evidence says a system does not find its own
    //    defects.
    if let Some(adj) = p.deny_adjudicator {
        let gate_owner = adj.strip_prefix("plugin-gate:").unwrap_or(adj);
        if gate_owner == p.arbiter {
            return Eligibility::Refused {
                reason: format!(
                    "'{}' issued the deny under appeal; the gate cannot arbitrate a dispute \
                     about its own decision",
                    p.arbiter
                ),
            };
        }
    }
    // 3. RECOGNISED REASONER. See `is_recognised_reasoner` — this clause exists because a
    //    cron plugin was routed an appeal and graded maximally independent.
    if !is_recognised_reasoner(p.arbiter) {
        return Eligibility::Refused {
            reason: format!(
                "'{}' is not a recognised reasoning harness — an appeal needs an entity that \
                 can read it and rule. Unrecognised is not independent; it is unrecognised, \
                 and grading it as the former routes disputes into silence",
                p.arbiter
            ),
        };
    }
    // 4. GRADE THE DISTANCE. The appellant's lineage may be unrecognised (anything can be
    //    denied, so anything can appeal); only the ARBITER must be recognised. An
    //    unrecognised appellant never matches a lineage, so every eligible arbiter grades
    //    cross-vendor against it — the honest reading: we cannot show they share a lineage.
    // Clause 1 already refused `arbiter == appellant`, so by here the two are different
    // members and the only question left is how far apart they are.
    let independence = if lineage(p.arbiter) != lineage(p.appellant) {
        Independence::CrossVendor
    } else {
        Independence::CrossMember
    };
    Eligibility::Eligible { independence }
}

/// Pick the most independent eligible arbiter from a candidate pool.
///
/// THIS IS THE "NOT-SAME AGENT IN THE ROLE" WIRE, and it is deliberately thin. It does not
/// reason, does not rank by competence, and does not know whether the candidate is awake.
/// It answers one question — *who, of the entities this machine knows about, is admissible
/// and furthest from the appellant* — and hands that answer to the dispatcher.
///
/// Ordering is by `Independence`, which sorts by declaration (`CrossVendor` strongest).
/// Ties break on plugin_id so the choice is reproducible; a random pick would make the same
/// appeal route differently on replay and there would be no way to audit the routing.
///
/// Returns `None` when nobody is admissible. That is a real and expected state on a
/// single-member machine, and it must render as "no arbiter available" rather than
/// defaulting to anyone — the whole constraint is that an inadmissible arbiter is worse
/// than none, because a ruling carries weight a missing ruling does not.
pub fn select_arbiter<'a>(
    appellant: &str,
    deny_adjudicator: Option<&str>,
    candidates: impl IntoIterator<Item = &'a str>,
) -> Option<(&'a str, Independence)> {
    let mut best: Option<(&'a str, Independence)> = None;
    for cand in candidates {
        let parties = AppealParties {
            appellant,
            deny_adjudicator,
            arbiter: cand,
        };
        let Eligibility::Eligible { independence } = eligibility(&parties) else {
            continue;
        };
        let better = match best {
            None => true,
            Some((prev_id, prev)) => (independence, cand) < (prev, prev_id),
        };
        if better {
            best = Some((cand, independence));
        }
    }
    best
}

/// A ruling, once an arbiter has actually reasoned about an appeal.
///
/// STUB. The reasoning is not here and is not simulated. This type exists so the storage,
/// the eligibility check and the derivation contract can be built and tested against a
/// stable shape while the reasoner is still a person or a dispatched agent. `rationale` is
/// mandatory and unbounded-by-design: a ruling without stated reasoning is the declaration
/// this whole architecture rejects, and there is no path here that produces one.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Ruling {
    pub deny_hash: String,
    pub appellant: String,
    pub arbiter: String,
    pub independence: Independence,
    /// `true` = the deny was wrong. Upholding an APPEAL means overturning a DENY.
    pub upheld: bool,
    /// Why. Required. A verdict without it is not admissible as evidence.
    pub rationale: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parties<'a>(appellant: &'a str, arbiter: &'a str, gate: Option<&'a str>) -> AppealParties<'a> {
        AppealParties { appellant, deny_adjudicator: gate, arbiter }
    }

    /// The constraint that is not a stub.
    #[test]
    fn a_member_cannot_arbitrate_its_own_appeal() {
        let e = eligibility(&parties("codex", "codex", None));
        assert!(matches!(e, Eligibility::Refused { .. }),
                "self-arbitration must be structurally impossible, not merely discouraged");
    }

    /// A gate ruling on a dispute about its own deny is self-review one layer up.
    #[test]
    fn the_gate_that_denied_cannot_arbitrate_the_appeal() {
        let e = eligibility(&parties("claude-code", "codex", Some("plugin-gate:codex")));
        assert!(matches!(e, Eligibility::Refused { .. }));
    }

    /// Cross-vendor is the strongest local signal — different training, different blind spots.
    #[test]
    fn a_different_vendor_grades_as_the_most_independent() {
        let e = eligibility(&parties("claude-code", "codex", Some("hestia-gate")));
        assert_eq!(e, Eligibility::Eligible { independence: Independence::CrossVendor });
    }

    /// Same lineage, different member: admissible, and recorded as WEAKER than
    /// cross-vendor. `Ord` follows declaration order, so smaller == more independent.
    ///
    /// The first version of this test used claude-code vs kimi-code and failed, because
    /// those are different VENDORS in the lineage map — a useful reminder that "different
    /// member" and "differently placed" are not the same claim, which is the entire reason
    /// independence is graded instead of asserted.
    #[test]
    fn same_lineage_different_member_is_admissible_but_weaker() {
        let e = eligibility(&parties("claude-code", "claude-mesh-worker", None));
        match e {
            Eligibility::Eligible { independence } => {
                assert_eq!(independence, Independence::CrossMember);
                assert!(Independence::CrossVendor < independence,
                        "cross-vendor must rank strongest");
            }
            other => panic!("a different member is admissible, got {other:?}"),
        }
    }

    /// The dispatch wire: given a real pool, route to the furthest-placed admissible entity.
    #[test]
    fn dispatch_routes_to_the_most_independent_admissible_candidate() {
        let pool = ["claude-code", "claude-mesh-worker", "codex", "kimi-code"];
        let picked = select_arbiter("claude-code", Some("hestia-gate"), pool);
        // codex and kimi are both cross-vendor; the tie breaks on id, reproducibly.
        assert_eq!(picked, Some(("codex", Independence::CrossVendor)));
    }

    /// The gate that denied is excluded from the pool it would otherwise win.
    #[test]
    fn dispatch_skips_the_gate_that_issued_the_deny() {
        let pool = ["codex", "kimi-code"];
        let picked = select_arbiter("claude-code", Some("plugin-gate:codex"), pool);
        assert_eq!(picked, Some(("kimi-code", Independence::CrossVendor)));
    }

    /// A machine with only the appellant on it has no arbiter, and says so. Rendering this
    /// as anything other than "none" is how a self-arbitration gets laundered by plumbing.
    #[test]
    fn a_single_member_machine_has_no_arbiter_rather_than_a_default_one() {
        assert_eq!(select_arbiter("codex", None, ["codex"]), None);
    }

    /// THE LIVE ONE. Regression for the first real appeal this surface handled, which was
    /// routed to `agent-inventory` — an hourly config-reading cron — and graded
    /// `cross_vendor`, the strongest tier, because its id matched no vendor prefix.
    #[test]
    fn a_cron_plugin_is_not_the_most_independent_judge_on_the_machine() {
        // The registry as it actually was: reasoning harnesses alongside plumbing.
        let registry = ["agent-inventory", "claude-code", "hestia-timer", "mesh-watcher"];
        assert_eq!(
            select_arbiter("claude-code", None, registry),
            None,
            "with no other harness present the honest answer is 'no arbiter' — anything else \
             routes the dispute into something that cannot rule, while reporting success"
        );
        // And with a real peer present, the peer wins over the plumbing.
        let with_peer = ["agent-inventory", "claude-code", "kimi-code"];
        assert_eq!(
            select_arbiter("claude-code", None, with_peer),
            Some(("kimi-code", Independence::CrossVendor))
        );
    }

    /// The same floor applies to the direct ruling path, not only to routing — otherwise an
    /// unrecognised caller could simply skip dispatch and rule anyway.
    #[test]
    fn an_unrecognised_entity_cannot_rule_even_if_it_asks_directly() {
        let e = eligibility(&parties("claude-code", "agent-inventory", None));
        assert!(matches!(e, Eligibility::Refused { .. }), "got {e:?}");
    }

    /// A second session of the same member is the same member.
    ///
    /// This test replaces `unknown_sessions_fail_closed_rather_than_assuming_independence`,
    /// which claimed to exercise session comparison while passing both parties the SAME
    /// plugin_id — so it exited at clause 1 and would have passed with the entire session
    /// branch deleted (kimi-code, reviewing). The branch is gone now, and this asserts the
    /// property that actually holds: identity is per MEMBER, and opening another terminal
    /// does not manufacture an independent judge.
    #[test]
    fn a_second_session_of_the_same_member_is_still_the_same_member() {
        let e = eligibility(&parties("codex", "codex", None));
        assert!(matches!(e, Eligibility::Refused { .. }),
                "no session-level escape hatch may exist: got {e:?}");
        // And the tier that used to promise one is gone from the type.
        assert_eq!(
            serde_json::to_string(&Independence::CrossMember).unwrap(),
            "\"cross_member\"",
            "the gradient is cross_vendor | cross_member — nothing weaker is admissible"
        );
    }
}

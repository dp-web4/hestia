//! The member-presence census. This test asserts ENUMERATIONS, not the
//! property — read this header before citing its verdict.
//!
//! **What a green census means:** the two consumer sets pinned below have not
//! changed since a person last looked. That is a fact about *attention*, not
//! about *safety*. It must never be cited as evidence for "member presence is
//! not a safety gate." Those are different claims, and hestia#80 is the proof
//! that they are different: while the first version of this test stood green
//! on the naming function, a live presence consumer — `tool_appeal`'s arbiter
//! pool, `handler.rs` — sat outside its keying entirely (found by claude-code,
//! 2026-07-27, exploration thread `r6-routing-tcpip-of-trust-2026-07-26`).
//! The property "no consumer gates on presence" was established by a human
//! reading every call site on one afternoon (2026-07-27, kimi-code;
//! re-derived and corrected on `main` by claude-code, same date), and this
//! test preserves only the conditions under which that reading stays
//! applicable. The reading itself is UNCONFIRMED the moment this file is the
//! only thing you have checked — the same distinction
//! `tools/workspace_root_test.py` learned as agreement vs. correctness
//! (#75/#77): a gauge that enforces agreement is not a gauge that reports
//! correctness.
//!
//! **Two tables, because the symbols are not interchangeable.**
//!
//! - `REGISTRY_CENSUS` pins the consumers of *presence itself* — accesses to
//!   `member_registry`, `load_members(`, `ensure_member(`,
//!   `attach_citizenship(`, `MemberRegistry::`, `.iter_sorted(`. This is the
//!   table that schedules the safety question: a new site here reads
//!   membership, and "is this a gate?" must be answered by the author, at
//!   write time. The definition lines of the three registry fns are excluded
//!   (same rule that excludes `fn member_lct` below).
//! - `MEMBER_LCT_CENSUS` pins the consumers of the *naming function* —
//!   `AppState::member_lct` (`state.rs`), which is `trim` → `is_synthetic` →
//!   sha256 over `(plugin_id, sovereign_lct)` and **never reads the
//!   registry**. It returns `Some` for any non-empty non-synthetic string,
//!   including a member that has never connected. A call site of a naming
//!   function is never a presence consumer, so this table cannot see the
//!   #80 defect class. What it pins comes in TWO classes, marked per site in
//!   the table's third column (`SiteClass`, added 2026-08-06, re-1190):
//!   `Naming` sites record or emit an identity (attribution hygiene — a red
//!   asks "does this change who gets named?"), and `Predicate` sites COMPARE
//!   two derived names to decide control flow — a gate that gates on a name
//!   (a red asks "is a name doing a gate's work?"). The split exists because
//!   neither pre-split table could flag the second class: the registry table
//!   can't see it (no registry access) and this table saw it but was
//!   documented as the not-a-gate table, so a refusal predicate
//!   (`tool_witness_adjudication`'s `adjudication_self`) sat filed as
//!   hygiene. Predicate sites additionally pin their comparison lines in
//!   `MEMBER_LCT_PREDICATE_CENSUS`.
//!
//! The first version of this test keyed on `member_lct` alone and claimed to
//! schedule judgment on presence. It could not; the keying was refuted before
//! it was ever exercised. Both tables are kept because both enumerations are
//! real — `tool_appeal` appears in each, once as the appeal's identity
//! filter (naming) and once as its candidate pool (presence) — but only the
//! registry table is about presence.
//!
//! **Grain, and the sabotage that chose it.** The first grain was per-file
//! counts, with the claim that counts go red *exactly* when the consumer set
//! changes. Sabotage B falsified the word: remove one call site and write a
//! gate-shaped one four lines away in the same file and the count nets to
//! zero — green, while the substitution the census exists to catch just
//! happened (claude-code 2026-07-27; reproduced independently by kimi-code,
//! same day: `handler.rs` 12 → 12, `1 passed`). Line numbers were already
//! rejected — a check that cries red on innocent edits teaches a team to
//! ignore red. So the grain is now **per `(file, enclosing fn)`, pinning the
//! trimmed text of every call-site line**. Red exactly when the set of
//! call-site lines changes: an add, a remove, a move across files or across
//! fns, a within-fn substitution (its line text differs), or any edit
//! touching a call-site line itself. Green on everything else — comments,
//! new fns, edits above or below a call site.
//!
//! Two residual blind spots, stated so the instrument is not overread:
//!
//! 1. A substitution whose new line is byte-identical to the removed one
//!    nets to zero. That is a semantic no-op modulo shadowing, not a gate
//!    being smuggled — the multiset of lines is unchanged because the call
//!    is unchanged.
//! 2. A pure rename that touches call-site lines (e.g. renaming `plugin_id`)
//!    goes red across the table. The red is cheap to disposition — read the
//!    delta, confirm the shape, update the table — and that cost is the
//!    price of catching Sabotage B. If this ever becomes the red people
//!    ignore, that is the signal to reconsider, in the open.
//!
//! **A third, now closed, and the reason to distrust the other two less than
//! you distrust this header.** Until 2026-08-02 the scan stopped at each
//! file's FIRST `#[cfg(test)]` module. `handler.rs` has nine, interleaved, the
//! first at line 4778 of 10050 — so this census read 47% of the tree's largest
//! governance file and pinned a table describing all of it. Four live
//! attribution sites (the gate-escalation surface, #114 and #152) had never
//! appeared. Both tables were green throughout. The `member_lct` table gained
//! those four on the fix; the REGISTRY table gained nothing, which is the one
//! genuinely reassuring result here — no presence consumer was hiding below
//! the cut. Stated at this length because the lesson is not "a bug was fixed":
//! it is that this file has now twice described its own coverage more
//! confidently than its code delivered, and both times the gap was found by
//! someone walking into it rather than by reading the header.
//!
//! **What the test actually does.** "Presence is not a safety gate" is a
//! negative over an open set, and no test can assert that. The bounded,
//! performable twin is the enumeration the negative ranges over: the
//! consumer sets today are finite and greppable, so the machine runs the
//! grep. A new consumer goes red **at the moment it is written**, on the
//! author — the only person holding the context to answer "is this a safety
//! use?" That scheduled judgment is the entire function of this test. If
//! you are reading this because it went red: do not just update the table.
//! Read your new call site, answer that question (registry table) or "does
//! this change who gets named?" (naming table), then say in this header
//! that you did.
//!
//! **This is scaffolding with a known demolition date.** When #63's
//! provisional/vouched split lands and a gate naming the provisional type is
//! a *compile error*, the property stops being human-checked and becomes a
//! machine one; this census then shrinks to a tripwire on the residue.
//! Saying so here is what stops it from calcifying into a "proof."
//!
//! **Method, stated so it is checkable against its own evidence:** walk
//! `core/src/**/*.rs`, SKIP each `#[cfg(test)] mod` block and resume after it
//! (test modules are consumers of the *API*, not of *presence*), track the nearest
//! preceding `fn` definition per line (the `fn` keyword in item position —
//! start of line after visibility/modifier prefixes — so a comment saying
//! "fn" can never re-key what follows; same-named fns in one file are
//! suffixed `#2`, `#3`, … and no file in the pinned sets currently needs
//! it), and collect the trimmed text of lines
//! matching the symbol set, skipping the registry fns' own definition lines.
//! The definition of `fn member_lct` (`core/src/server/state.rs:420`) does
//! not match `.member_lct(`. Tables verified against `origin/main` at
//! `fb6cc87` — reachable from `main`, stated deliberately: a census recorded
//! against an unreachable ref is a fact about a proposal, not about the
//! repo.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

/// Consumers of the naming function: trimmed text of every `.member_lct(`
/// line, keyed `(file, enclosing fn)`.
///
/// (The header used to carry a literal "14 keys, 19 lines" here. It was
/// already wrong before this edit — `trust_graph_turtle` was appended in
/// `ae75d16` without it, making the table 15 and 20 — and a count maintained
/// by hand beside a table the compiler already enumerates is a second source
/// of truth that only drifts. Removed rather than corrected: the assertion is
/// exactness against the source, and the table below IS the count.)
///
/// Every entry here was read by a person and carries that judgment as its
/// third column (`SiteClass`, 2026-08-06). The 2026-07-27 reading judged
/// every site a NON-GATING use — attribution / emit-path identity resolution
/// — and that judgment was wrong for four of them: `tool_appeal`,
/// `tool_arbitrate_appeal`, `tool_open_appeals` and
/// `tool_witness_adjudication` each COMPARE two member_lct-derived names to
/// decide control flow (a pool filter, two refusals, one eligibility
/// verdict). Found in the re-1177 thread (claude-code, re-1190): a refusal
/// predicate had been filed as attribution hygiene, and both pre-split
/// tables were structurally unable to say so — the registry table can't see
/// a name-gate (no registry access) and this table saw it but was documented
/// as the not-a-gate table. Editing this table without performing the class
/// judgment on the delta is the one move this test exists to make expensive.
///
/// Delta readings, recorded as the header requires:
/// - 2026-07-28 (kimi-code), merge with `main` at `bc24d82` (PR #67) added
///   `tool_open_appeals`: caller and appellant are resolved through
///   `member_lct` and compared for equality — the same NOT-SAME identity
///   comparison `tool_arbitrate_appeal` performs, here as queue-listing
///   advisory (`you_may_rule`). It names two existing identities to compare
///   them; it does not change who gets named, and it does not read the
///   registry (the presence table stayed green over the same merge).
///   RECLASSIFIED 2026-08-06: that reading answered the naming question and
///   stopped; the equality comparison it describes IS a predicate, and the
///   entry is now tagged `SiteClass::Predicate`. The reading was correct
///   about naming and incomplete about gating — the two questions are
///   independent, which is why the class is a column and not a conclusion.
/// - 2026-08-07 (claude-code), the #226 invitation writer added a pool
///   filter to `tool_gate_escalation_open`, RECLASSIFYING it Naming →
///   Predicate. Full reading at the site. Two notes belong up here because
///   they are about the INSTRUMENT, not that one site: (a) it is the first
///   MIXED site — one naming line and one gate under a column that holds a
///   single word — so `Predicate` here means "contains a gate", not "is
///   only a gate", and a mostly-hygiene site with one buried comparison
///   will look identical in this column; (b) a Predicate is not necessarily
///   a refusal. This one selects an invitation pool and fails OPEN, so its
///   harm runs opposite to the four refusal predicates above: a false
///   "same entity" withholds an invitation, and the peer then reads as
///   ABSENT rather than as never-asked — the precise conflation #226 was
///   meant to end.
/// - 2026-08-07 (claude-code), hours later: the mixed site above no longer
///   exists. Factoring the invitation writer into `resolve_invitation` +
///   `opened_payload` — done because the CLAIM door had a hand-rolled
///   `open()` carrying none of #241's keys, not to fix this table — split
///   the gate away from the naming line, so `tool_gate_escalation_open` is
///   gone from all three tables and its two classes are stated separately.
///   Grep for either new name to find what used to be under the old one.
///   The instrument limit in note (a) is NOT thereby repaired: it was
///   un-mixed by a coincidence of refactoring, nothing stops the next mixed
///   site, and a re-inlining would go red on the rename alone — recoverable
///   to green by re-tagging one site, which is the cheap move the class
///   column exists to make expensive. What actually holds the gate is its
///   pinned comparison in `MEMBER_LCT_PREDICATE_CENSUS`, not the split.

/// What a `.member_lct(` consumer DOES with the name it derives.
///
/// - `Naming`: the derived LCT is recorded or emitted — attribution inside a
///   chain entry, a response field, a graph URI, a trust key. It names
///   someone, and no control-flow decision turns on two such names agreeing.
/// - `Predicate`: the derived LCT is COMPARED against another
///   member_lct-derived value and the comparison decides control flow — a
///   refusal, a pool filter, an eligibility verdict. A gate that gates on a
///   NAME is exactly where an inert alias bites: a name comparison silently
///   answers "different" for two spellings of one entity. Every Predicate
///   site must also pin its comparison line(s) verbatim in
///   `MEMBER_LCT_PREDICATE_CENSUS`, so weakening the comparison goes as red
///   as writing it did — the line census cannot hold those lines, because
///   they consume the DERIVED variables and contain no `.member_lct(`.
///
/// The column is a column — not a separate list — so that adding a site
/// forces the author to write one of the two words at the site, at compile
/// time. A class an author can omit is a class that will be omitted, and an
/// omitted Predicate reads green as hygiene: the failure this split exists
/// to close.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum SiteClass {
    Naming,
    Predicate,
}

const MEMBER_LCT_CENSUS: &[(&str, &[&str], SiteClass)] = &[
    ("server/handler.rs::gate_direct_tool", &[
        "let instance_lct = s.member_lct(&who.plugin_id);",
    ], SiteClass::Naming),
    ("server/handler.rs::tool_appeal", &[
        "let appellant_lct = s.member_lct(&appellant.plugin_id);",
        "match (&appellant_lct, s.member_lct(id)) {",
    ], SiteClass::Predicate),
    ("server/handler.rs::tool_arbitrate_appeal", &[
        "let a = s.member_lct(&arbiter.plugin_id);",
        "let b = s.member_lct(appellant);",
    ], SiteClass::Predicate),
    ("server/handler.rs::tool_open_appeals", &[
        "let a = s.member_lct(&c.plugin_id);",
        "let b = s.member_lct(appellant);",
    ], SiteClass::Predicate),
    // THIRD LINE ADDED 2026-08-07 (claude-code, #268 — the `policy_unevaluable` entry). The
    // census went red on it the moment it was written, which is the instrument working.
    //
    // READING, answering both questions this table schedules. (1) Does it change who gets
    // named? No — it names the SAME `plugin_id_for_chain` the two sites above it already
    // name, on a new entry kind rather than a new subject; a call the matcher could not
    // read is now recorded against exactly the member that made it. (2) Is any derived
    // name COMPARED to decide control flow? No: `instance_lct` is serialised into the
    // payload and read by nothing. The decision (`unevaluable`) is computed upstream from
    // `tool_name` and `target`, never from this value, and the verdict is deliberately
    // unchanged either way — so a registry miss yields a `null` in the record and alters
    // no outcome. Naming, not Predicate, same class as its two siblings.
    ("server/handler.rs::tool_query_policy", &[
        "let instance_lct = s.member_lct(&plugin_id_for_chain);",
        "let instance_lct = s.member_lct(&plugin_id_for_chain);",
        "let instance_lct = s.member_lct(&plugin_id_for_chain);",
    ], SiteClass::Naming),
    ("server/handler.rs::tool_record_outcome", &[
        "let instance_lct = s.member_lct(&plugin_id);",
    ], SiteClass::Naming),
    ("server/handler.rs::tool_record_reversal", &[
        "let subject_instance_lct = s.member_lct(&subject_plugin_id);",
    ], SiteClass::Naming),
    ("server/handler.rs::tool_witness_adjudication", &[
        "let adjudicator_instance_lct = s.member_lct(&adjudicator.plugin_id);",
        "let subject_instance_lct = s.member_lct(&subject_plugin_id);",
    ], SiteClass::Predicate),
    ("server/handler.rs::tool_witness_decision", &[
        "let instance_lct = s.member_lct(&plugin_id);",
    ], SiteClass::Naming),
    // ADDED 2026-07-28 (claude-code, #84 — the RDF projection). The census went red on this
    // site the moment it was written, which is the instrument working: it scheduled the
    // judgment call on the author, at write time, before the PR merged.
    //
    // READING: **naming, not presence.** `trust_graph_turtle` derives the entity URI for the
    // Turtle projection. It changes *who gets named* in the emitted graph — which is exactly
    // what this table pins — and it reads no registry content, so it is not a presence
    // consumer and belongs here rather than in REGISTRY_CENSUS.
    //
    // Worth stating because the derivation is deliberate: `member_lct` returns Some for any
    // non-empty non-synthetic string, so a plugin that never connected still yields a
    // well-formed LCT. For a GRAPH that is the right call — the derivation is deterministic
    // and stable, so triples join across emissions — but it means the graph's `web4:entity`
    // asserts a *name*, not attendance. The projection's own docs say so; this entry is the
    // second place that stays true.
    ("server/http.rs::trust_graph_turtle", &[
        ".member_lct(&q.plugin_id)",
    ], SiteClass::Naming),
    ("server/http.rs::operator_adjudicate", &[
        "let subject_instance_lct = s.member_lct(&a.subject_plugin_id);",
    ], SiteClass::Naming),
    // ADDED 2026-07-30 (claude-code). #114 (stage 2 of the governance-write escalation) landed
    // this site and the census went red — on `main`, not on the PR, because the merge did not
    // wait for its own checks. The instrument worked; nothing was listening. See the companion
    // finding in this PR's description.
    //
    // READING: **naming, not presence**, same class as `operator_adjudicate` directly above.
    // `subject_instance_lct` is attribution inside the `gate_escalation_decided` chain entry —
    // it records WHO the approved-or-refused governance write belonged to. It changes who gets
    // named (a new witness event type names a subject), and it reads no registry, so it belongs
    // in this table rather than REGISTRY_CENSUS.
    //
    // One caveat worth pinning at this site specifically. `member_lct` derives an LCT from any
    // non-empty non-synthetic string, and `esc.plugin_id` is caller-asserted — the escalation
    // record says so itself (`gate_escalation.rs:125`, HST-005). So the `subject_instance_lct`
    // in a decision record is a well-formed name derived from a self-reported id, not evidence
    // that the subject is a registered member. That is the same "asserts a name, not
    // attendance" property recorded for `trust_graph_turtle` above, and it lands harder here:
    // this record is the one an operator reads back to justify having permitted a write to the
    // governance surface.
    ("server/http.rs::operator_gate_escalation", &[
        "\"subject_instance_lct\": s.member_lct(&esc.plugin_id),",
    ], SiteClass::Naming),
    // Per-member policy grants (2026-08-01). Same property as the escalation record above and
    // for the same reason: `member_lct` asserts a NAME, not attendance, so the subject of a
    // grant may be a plugin_id no member has ever registered under. That is tolerable here
    // because a grant is keyed on `(plugin_id, role)` at evaluation time — an id nobody acts
    // under simply never matches and the grant is inert — but it means an operator can type a
    // typo and see a live-looking grant that governs nothing. Registered here so the next
    // reader meets that fact deliberately rather than discovering it from a grant that did
    // nothing.
    ("server/http.rs::policy_set_instance_grant", &[
        "\"subject_instance_lct\": s.member_lct(&plugin_id),",
    ], SiteClass::Naming),
    ("server/http.rs::policy_revoke_instance_grant", &[
        "\"subject_instance_lct\": s.member_lct(&plugin_id),",
    ], SiteClass::Naming),
    ("server/state.rs::apply_adjudication_ctx", &[
        "if let Some(subject_lct) = self.member_lct(subject_plugin_id) {",
    ], SiteClass::Naming),
    ("server/state.rs::apply_judgment_ctx", &[
        "if let Some(subject_lct) = self.member_lct(plugin_id) {",
    ], SiteClass::Naming),
    ("server/state.rs::apply_outcome_ctx", &[
        "if let Some(subject_lct) = self.member_lct(plugin_id) {",
    ], SiteClass::Naming),
    // ── ADDED 2026-08-02 (claude-code). FOUR OF THESE FIVE ARE NOT NEW CODE. ──
    //
    // They became visible when `production_lines` replaced `prod_prefix` (see its doc comment):
    // the scanner used to stop at the FIRST `#[cfg(test)] mod`, and `handler.rs` carries nine
    // of them interleaved with production code, the first at line 4778 of 10050. So this table
    // has been pinning 47% of that file and reporting on all of it. The gate-escalation naming
    // surface — landed in #114 and #152 — has never been in the census at all.
    //
    // This is recorded as a finding, not a tidy-up: the census's own header warns that a cut
    // which hides code "goes quiet, which is the worse direction", names two files where it
    // happened, and then the instrument had the same defect one level up, in the largest
    // governance file in the tree. It was found only because a new surface straddled the cut
    // and went red on one of its two sites. A change landing entirely below line 4778 would
    // have passed green through a whole new consequential path.
    //
    // READING for the four pre-existing sites (`tool_gate_escalation_open`,
    // `tool_gate_escalation_claim` ×2, `tool_gate_arbitrate_escalation`): **naming, not
    // presence**, identical in class to `operator_gate_escalation` above — attribution inside
    // the escalation chain entries, recording WHOSE governance write was asked for, claimed or
    // ruled. No registry read. The HST-005 caveat recorded at `operator_gate_escalation`
    // applies unchanged and now applies at four more sites: `esc.plugin_id` is caller-asserted,
    // so `subject_instance_lct` is a well-formed name derived from a self-reported id, not
    // evidence of membership. These records are what an operator reads back to justify having
    // permitted a governance write, so that caveat is load-bearing here.
    //
    // READING for `tool_request_scope` (genuinely new): **naming, not presence**, same class.
    // It attributes a scope REQUEST to its asker in the `scope_requested` entry. Asking permits
    // nothing, and the same self-reported-id caveat holds — but the paired decision record
    // (`http.rs::scope_decide`) is the one that widens reach, and it is keyed on the same
    // asserted `plugin_id`. As with `policy_set_instance_grant`, a typo yields a live-looking
    // grant that matches nothing and is inert. Read deliberately, not discovered later.
    // RECLASSIFIED 2026-08-07 (claude-code, the #226 invitation writer). This site was
    // `Naming` on one line and now carries three: the original attribution line, plus a
    // pool filter that compares the asker's derived name against each candidate's to
    // decide who is invited. That comparison decides control flow, so the site is
    // `Predicate` and pins its comparison below.
    //
    // Two things about this reading, because the honest answer is not the flattering one:
    //
    // 1. The class is per-SITE and the classes are per-LINE. This is the first genuinely
    //    MIXED site in the table — `"subject_instance_lct"` names, the filter gates, and
    //    the column can hold only one word. `Predicate` is the correct choice because it
    //    is the stronger claim and forces the comparison pin; tagging `Naming` would have
    //    made the red go away while leaving the gate unpinned, which is the exact move
    //    the class column exists to make expensive. Recorded as an instrument limit: a
    //    future site that is mostly hygiene with one buried comparison will look, in this
    //    column, identical to a pure gate.
    // 2. This predicate is NOT a refusal and must not be read as one. Nothing it decides
    //    can block the open, delay it, or move `bar_met` — it selects an invitation pool,
    //    and it fails OPEN (an unmappable candidate is invited, not dropped). What makes
    //    it a Predicate is that a name comparison chooses who is asked; what makes that
    //    consequential is the inverse of a refusal — a peer wrongly judged "same entity"
    //    is never invited, and then reads as ABSENT in `peer_participation()`. The
    //    alias-guard reach is whitespace only
    //    (`state::tests::the_member_lct_alias_guard_reaches_only_whitespace`), so
    //    `codex` vs `codex-cli` are two invitees, not one — over-inviting, the safe
    //    direction here, and the reason the fail-open was chosen deliberately.
    // SPLIT 2026-08-07, hours after the reading above was written, by the factoring that
    // moved the invitation writer to the door the gate actually walks through. The mixed
    // site is GONE, and not because the instrument improved: a production refactor done
    // for an unrelated reason (the claim path had a hand-rolled `open()` whose payload
    // carried none of #241's keys) happened to put the naming line and the gate in
    // separate functions. `opened_payload` is the attribution; `resolve_invitation` is the
    // pool filter. Both classes are now stated at their own site and the column holds one
    // word honestly.
    //
    // Two things this does NOT establish. (a) The instrument limit recorded above stands
    // unrepaired — nothing stops the next mixed site, and this one was un-mixed by luck,
    // so the limit is still the right thing to have written down. (b) Nothing prevents a
    // future re-inlining from silently re-mixing it: the census would go red on the
    // rename and an author could restore green by re-tagging one site `Predicate`, which
    // is exactly the cheap move the class column was built to make expensive. The
    // protection is the pinned comparison in `MEMBER_LCT_PREDICATE_CENSUS`, not the split.
    //
    // The reading itself is unchanged and carries over verbatim: still a pool filter,
    // still NOT a refusal, still fails OPEN, still the whitespace-only alias reach
    // (`state::tests::the_member_lct_alias_guard_reaches_only_whitespace`), so
    // over-inviting remains the safe direction it errs in.
    ("server/handler.rs::resolve_invitation", &[
        ".filter(|id| match (&asker_lct, s.member_lct(id)) {",
        "let asker_lct = s.member_lct(&esc.plugin_id);",
    ], SiteClass::Predicate),
    // The shared attribution line, now emitted once for BOTH doors. Naming, unchanged in
    // class from when it sat inline in each. The HST-005 caveat is load-bearing here and
    // is now carried on one line instead of three: `esc.plugin_id` is caller-asserted, so
    // `subject_instance_lct` is a well-formed name derived from a self-reported id, not
    // evidence of membership.
    ("server/handler.rs::opened_payload", &[
        "\"subject_instance_lct\": s.member_lct(&esc.plugin_id),",
    ], SiteClass::Naming),
    // Was two identical lines; the duplicate was the hand-rolled fallback payload this
    // change deleted in favour of `opened_payload`. The remaining line is the claim
    // response's own attribution, which is not the chain entry and did not move.
    ("server/handler.rs::tool_gate_escalation_claim", &[
        "\"subject_instance_lct\": s.member_lct(&esc.plugin_id),",
    ], SiteClass::Naming),
    ("server/handler.rs::tool_gate_arbitrate_escalation", &[
        "\"subject_instance_lct\": s.member_lct(&decided.plugin_id),",
    ], SiteClass::Naming),
    // ADDED 2026-08-16 (kimi-code, revised #480 review defect 4b — the lapse recorder's
    // `gate_escalation_expired` entry). The census went red the moment the site was written —
    // the instrument working, again on an integration test `cargo test --lib` never runs.
    //
    // READING, both questions. (1) Who gets named? The ASKER of a petition that ran out its
    // clock unruled — attribution inside the lapse record, recording WHO the lapsed
    // escalation belonged to. (2) Compared to decide control flow? No — the lapse decision
    // is the clock (`newly_lapsed` keys on stored status and `expires_at`); the derived LCT
    // is serialised into the witness entry and read by nothing. Naming, same class as the
    // decided-entry sibling directly above, and the same HST-005 caveat holds unchanged:
    // `esc.plugin_id` is caller-asserted, so this is a well-formed name derived from a
    // self-reported id, not evidence of membership.
    ("server/handler.rs::record_newly_lapsed", &[
        "\"subject_instance_lct\": s.member_lct(&esc.plugin_id),",
    ], SiteClass::Naming),
    ("server/handler.rs::tool_request_scope", &[
        "\"subject_instance_lct\": s.member_lct(&plugin_id),",
    ], SiteClass::Naming),
    // The operator's answer to a scope request. Widens what a member may reach; this line names
    // the subject in the `scope_granted`/`scope_refused` entry.
    //
    // TWO IDENTICAL LINES as of 2026-08-15, and the duplication is the fix, not sloppiness. A
    // STANDING grant now records INTENT → COMMIT → SUCCESS: the first line names the subject in
    // the `scope_grant_intent` entry, the second names it again in the `scope_granted` entry
    // that is appended only once the vault commit has landed. Before that split there was one
    // append, named `scope_granted`, written BEFORE the commit — so a failed vault write left
    // the chain asserting a grant that never came into force (GPT review of #462). The subject
    // must be named in both records because either one can be the last word: if the commit
    // fails, the intent is the only account of who the widening was for.
    //
    // Both remain Naming. Neither derived lct is compared to anything — the decision keys on
    // `request_id` and the `(plugin_id, path)` strings, and these values are serialised into
    // witness entries and read by nothing.
    ("server/http.rs::scope_decide", &[
        "\"subject_instance_lct\": s.member_lct(&plugin_id),",
        "\"subject_instance_lct\": s.member_lct(&plugin_id),",
    ], SiteClass::Naming),
    // ADDED 2026-08-14 (claude-code, Sprint F R1 — the standing-scope surface). The census
    // went red the moment the site was written — the instrument working.
    //
    // READING, both questions. (1) Who gets named? The subject of a `scope_standing_revoked`
    // chain entry — the member whose DURABLE grant an operator just removed. Same shape and
    // same caveat as `scope_decide` directly above: `plugin_id` is operator-typed here, so
    // this is a name, not attendance; a typo'd revoke 404s on the store lookup before this
    // line runs, which bounds the mismatch. (2) Compared to decide control flow? No — the
    // revoke keys on the store's `(member, path)` strings; the derived LCT is serialised
    // into the witness entry and read by nothing. Naming, like its sibling.
    ("server/http.rs::scope_standing_revoke", &[
        "\"subject_instance_lct\": s.member_lct(&plugin_id),",
    ], SiteClass::Naming),
    // ADDED 2026-08-15 (claude-code, the operator-originated grant `POST /api/scope/grant`).
    // The census went red the moment the site was written — the instrument working, and it
    // caught a change I had already convinced myself was verified: I had run only
    // `--lib server::dashboard` locally, and this is an integration test.
    //
    // READING, both questions. (1) Who gets named? The subject of a `scope_granted` entry —
    // the member whose DURABLE reach an operator just widened WITHOUT any member having asked.
    // Same shape as `scope_decide` and `scope_standing_revoke` above, with one difference
    // worth recording: those two name a subject the member itself put on the record by
    // filing a request, whereas here `plugin_id` is operator-TYPED and there is no ask to
    // corroborate the spelling. That makes this the weakest-corroborated naming site of the
    // three, which is precisely why the handler also reports `member_known` (see this same fn
    // in REGISTRY_CENSUS) so a typo is visible to the operator at the moment it is made.
    // (2) Compared to decide control flow? No. The derived LCT is serialised into the witness
    // entry and read by nothing; the grant keys on the `(plugin_id, path)` strings. Naming.
    ("server/http.rs::scope_grant", &[
        "\"subject_instance_lct\": s.member_lct(&plugin_id),",
    ], SiteClass::Naming),
    ("server/state.rs::trust_entity_key", &[
        "match self.member_lct(plugin_id) {",
    ], SiteClass::Naming),
    // ADDED 2026-08-11 (claude-code, #352 — idle-but-known harness surfacing). The census went
    // red the moment this site was written — the instrument working.
    //
    // READING, both questions. (1) Who gets named? It RECOVERS a persisted grain's harness pid
    // for the dashboard trust list: reverse-mapping a stored key (`{member_lct}#{role}`) back to
    // the registry harness that owns it, so an idle-but-known member (kimi, days quiet) shows its
    // most recent standing instead of dropping off the list. It surfaces an EXISTING name; it
    // mints and records nothing. It is the exact INVERSE of `trust_entity_key` above (which
    // derives the same lct to BUILD the key) and shares its class. (2) Compared to gate a
    // governance decision? No — the derived lct enters a reverse-lookup map, and the only control
    // flow it gates is which read-only rows appear, and under which harness name, in the trust
    // box. No allow/deny, no chain attribution, no NOT-SAME independence check. Naming, not
    // Predicate; no comparison pinned.
    ("server/dashboard.rs::dashboard_snapshot_window", &[
        "if let Some(lct) = self.member_lct(orch.id) {",
    ], SiteClass::Naming),
];

/// The comparison lines of every `SiteClass::Predicate` site, pinned verbatim
/// against the named fn's production text. These lines cannot live in the
/// line census above: they consume the DERIVED variables, so they contain no
/// `.member_lct(` and the scanner never sees them. Without this table a gate
/// weakened below the variable level (an `==` becoming an `!=`, a
/// `same_entity` arm deleted) stays green while its inputs remain pinned —
/// the substitution Sabotage B demonstrated at line level, one level down.
/// Keyed on the exact site set the main table tags Predicate; the test
/// asserts the two agree, so a new Predicate site without a pinned
/// comparison — or a pinned comparison at a Naming site — is red on arrival.
const MEMBER_LCT_PREDICATE_CENSUS: &[(&str, &[&str])] = &[
    // The arbiter pool filter: a candidate whose member LCT equals the
    // appellant's is dropped. Documents its own reach in `handler.rs`
    // (whitespace only — `the_member_lct_alias_guard_reaches_only_whitespace`).
    ("server/handler.rs::tool_appeal", &[
        "(Some(a), Some(b)) => a != &b,",
    ]),
    // The `same_entity` arm feeding `hestia.arbitration_self`.
    ("server/handler.rs::tool_arbitrate_appeal", &[
        "a.is_some() && a == b",
    ]),
    // The escalation INVITATION pool filter (#226's missing writer): a candidate whose
    // member LCT equals the asker's is not invited. Byte-identical to `tool_appeal`'s
    // arm above and deliberately so — one comparison, two pools, so a future repair to
    // the alias reach lands on both or is visibly missing from one. The direction of
    // harm inverts between them: at `tool_appeal` a false "different" admits an arbiter
    // who should not rule; here a false "same" withholds an invitation and the peer then
    // reads as absent. Same line, opposite failure — which is why the pin is per site.
    ("server/handler.rs::resolve_invitation", &[
        "(Some(a), Some(b)) => a != &b,",
    ]),
    // The same arm, advisory here (`you_may_rule: false`). An advisory
    // predicate is still a predicate: it is the answer a member acts on when
    // deciding whether to file a ruling.
    ("server/handler.rs::tool_open_appeals", &[
        "a.is_some() && a == b",
    ]),
    // The `hestia.adjudication_self` refusal. The first conjunct compares
    // plugin_id strings (not this census's symbol); the second is the
    // name-gate, pinned.
    ("server/handler.rs::tool_witness_adjudication", &[
        "|| (subject_instance_lct.is_some() && subject_instance_lct == adjudicator_instance_lct)",
    ]),
];

/// Consumers of presence itself: trimmed text of every line touching
/// `member_registry` / `load_members(` / `ensure_member(` /
/// `attach_citizenship(` / `MemberRegistry::` / `.iter_sorted(`, minus the
/// three registry fns' own definition lines, keyed `(file, enclosing fn)`.
///
/// Every entry here was read by a person on 2026-07-27 and judged: one
/// producer (`tool_connect`'s mint), one boot load, three operator surfaces,
/// one publish set, one counter — and one **consequential read**,
/// `tool_appeal`'s candidate pool, whose fail-open degradation is hestia#80.
/// That entry is the reason this table exists: the first census keying could
/// not see it at all.
const REGISTRY_CENSUS: &[(&str, &[&str])] = &[
    ("cli.rs::cmd_lct_publish", &[
        "let members = hestia::member_registry::load_members(&vault);",
    ]),
    ("cli.rs::cmd_witness_attest", &[
        "let reg = hestia::member_registry::load_members(&vault);",
    ]),
    ("cli.rs::cmd_witness_onboard", &[
        "let mut reg = hestia::member_registry::load_members(&vault);",
    ]),
    ("lct_publish.rs::collect_publish_set", &[
        "for (plugin_id, lct) in members.iter_sorted() {",
    ]),
    ("server/dashboard.rs::dashboard_snapshot_window", &[
        "member_entities: self.member_registry.len(),",
    ]),
    // Added 2026-08-17 (codex, PR #490 NOT-SAME pass). READING, answering the question
    // this table schedules — **is this a safety use of presence?**
    //
    // NO. `deployment_health` enumerates known members only to report which of them have
    // supplied an A1 gate-capability self-report. The result is dashboard evidence; it is
    // never consulted by authorization, floor serving, or mutation. A missing/corrupt
    // registry can make the coverage report incomplete (and therefore potentially
    // over-optimistic), but cannot admit an act. That limitation is stated in the returned
    // note: these are last accepted, unauthenticated self-reports, not current loaded-byte
    // attestation; #481 owns the stronger claim.
    ("server/dashboard.rs::deployment_health", &[
        ".iter_sorted()",
        ".member_registry",
    ]),
    // Added 2026-08-15 (claude-code, `POST /api/scope/grant`). READING, answering the question
    // this table schedules — **is this a safety use of presence?**
    //
    // NO, and deliberately not. The grant proceeds whether or not the member is in the
    // registry; presence changes only the ADVISORY the operator is handed back. Granting
    // ahead of a member's first connect is legitimate, so refusing on absence would break a
    // real workflow to catch a typo.
    //
    // It exists because the alternative failed silently: a grant to `kimi-cod` persists, moves
    // the generation, and never matches anything, and nothing on screen would have said so.
    // Worth recording that the FIRST version of this check was inert — it asked
    // `member_lct(..).is_some()`, and `member_lct` DERIVES a label by hashing the plugin_id, so
    // it returned `Some` for every string ever passed to it. It printed "the gate consults it
    // immediately" over grants that could never match. A guard structurally incapable of
    // failing is worse than none, because it reassures; this now asks the registry, which can
    // answer no, and both arms were demonstrated on one daemon before it shipped.
    //
    // DEGRADATION DIRECTION, since that is what this table really wants to know: if the
    // registry were empty or unreadable, every grant would be labelled "no member by that
    // name" — over-warning, not under-warning. The operator is told to check a spelling that
    // was fine. That is the loud direction and the safe one: it cannot cause a grant to be
    // made, and it cannot cause one to be silently trusted. The opposite failure — a registry
    // that wrongly reports a member present — would restore exactly the silent-typo state this
    // was added to end, so if this ever becomes a gate rather than an advisory, that reading
    // must be redone.
    ("server/http.rs::scope_grant", &[
        "let member_known = s.member_registry.get(&plugin_id).is_some();",
    ]),
    // Added 2026-08-17 (codex, PR #490 NOT-SAME pass). READING, answering the question
    // this table schedules — **is this a safety use of presence?**
    //
    // NO. `scope_floor_add` reads only `member_registry.len()` and writes that number into
    // the immutable INTENT as contemporaneous context. It does not branch on the value:
    // zero, stale, or incomplete membership produces the same operator-authorized floor
    // mutation, whose stated scope is every present and future member. A bad count weakens
    // the evidence record; it cannot widen or refuse authority.
    ("server/http.rs::scope_floor_add", &[
        "let members_affected = s.member_registry.len();",
    ]),
    // Added 2026-08-07 (claude-code, the #226 invitation writer). READING, answering the
    // question this table schedules — **is this a safety use of presence?**
    //
    // RENAMED 2026-08-07, same day, by the factoring that moved the writer to the door the
    // gate actually walks through: this site was `tool_gate_escalation_open` and is now
    // `resolve_invitation`, a helper both doors call. The lines are byte-identical and the
    // reading below is unchanged — but the site is now reached from the CLAIM path too,
    // which is where the production traffic was all along, so the reading went from
    // describing a surface with no callers to describing the live one.
    //
    // NOT a gate, and structurally cannot become one: this read happens after the
    // escalation is opened, and nothing it produces is consulted by `bar_met` or can
    // refuse, delay or alter the open. A registry that returned zero members yields an
    // empty invitation list and an escalation that proceeds exactly as it does today.
    //
    // But it is CONSEQUENTIAL in the same shape as `tool_appeal`'s pool — hestia#80 — and
    // for the same reason, so it is logged here rather than waved through: presence
    // decides WHO IS ASKED. A member absent from the registry is never invited, and the
    // record then shows it as not-invited rather than as unreachable. That is the fail-
    // open direction (the escalation stands; the pool silently shrinks), which is the
    // #80 degradation exactly: the pool quietly narrows and the entry that results still
    // looks complete. The mitigation is that the invitation is RECORDED with its
    // evidence — `invited_peers` plus `invitation_evidence` (liveness at invite) plus
    // `invitation_passed_over` (cap overflow) — so a reader can tell an empty pool from
    // an unasked one. That is a record that makes the narrowing visible; it is not a
    // check that prevents it. The unclosed half: nothing distinguishes "registry holds
    // no other member" from "registry failed to load", because `state::open` fails open
    // to an empty registry. If that distinction ever matters, it is measured HERE.
    ("server/handler.rs::resolve_invitation", &[
        ".iter_sorted()",
        ".member_registry",
    ]),
    ("server/handler.rs::tool_appeal", &[
        ".iter_sorted()",
        ".member_registry",
    ]),
    ("server/handler.rs::tool_connect", &[
        "crate::member_registry::ensure_member(",
    ]),
    ("server/state.rs::open", &[
        "let member_registry = crate::member_registry::load_members(&vault);",
    ]),
];

const REGISTRY_SYMBOLS: &[&str] = &[
    ".member_registry",
    "load_members(",
    "ensure_member(",
    "attach_citizenship(",
    "MemberRegistry::",
    ".iter_sorted(",
];

/// Definition lines of the registry fns are excluded from the registry
/// census — same rule that excludes `fn member_lct` from the naming census.
const REGISTRY_DEF_FNS: &[&str] = &["load_members(", "ensure_member(", "attach_citizenship("];

fn rs_files(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in
        fs::read_dir(dir).unwrap_or_else(|e| panic!("read_dir {}: {e}", dir.display()))
    {
        let path = entry.expect("dir entry").path();
        if path.is_dir() {
            rs_files(&path, out);
        } else if path.extension().map_or(false, |x| x == "rs") {
            out.push(path);
        }
    }
}

/// The production lines of a file: everything OUTSIDE a `#[cfg(test)] mod` block.
///
/// The cut must be a `#[cfg(test)]` in ITEM POSITION at column 0 whose next
/// non-blank line opens a module — the same item-position discipline
/// [`fn_item_name`] applies to `fn`, and for the same reason, one severity
/// worse. A raw `text.find("#[cfg(test)]")` cuts on the token wherever it
/// appears, and in this tree it appears twice where it must not:
/// `constellation.rs:96` writes it inside a doc comment (1088 production
/// lines below the cut) and `operator_auth.rs:71` uses it as an item-level
/// attribute on a test-only helper INSIDE a production impl (496 lines
/// below). A consumer written below either cut is invisible to this census
/// and the test stays GREEN — verified by inserting one identical registry
/// consumer twice into `constellation.rs`: above the cut RED and named,
/// below the cut green (claude-code, 2026-07-28). The `fn`-in-a-comment
/// defect cried wolf; this one goes quiet, which is the worse direction.
///
/// **2026-08-02, claude-code — the same quiet defect, one layer up, found by
/// walking into it.** This was `prod_prefix`, returning everything before the
/// FIRST test module and calling it "the trailing `#[cfg(test)] mod`". That
/// name encodes an assumption — one test module, at the end — which
/// `handler.rs` has never satisfied: it carries **nine** `#[cfg(test)]` blocks
/// interleaved with production code, the first at line 4778 of 10050. So the
/// census read 47% of the largest and most governance-dense file in the tree
/// and reported on all of it. Everything past 4778 was invisible: the entire
/// gate-escalation surface, and four live `member_lct` attribution sites that
/// have never appeared in the pinned table.
///
/// It was found because adding a tenth production fn below the cut went red on
/// one of its two new naming sites and green on the other. A tripwire that
/// fires on half of a change is how you learn the tripwire is the thing being
/// measured — and had the new code landed entirely below 4778, the census
/// would have stayed green through a whole new consequential surface.
///
/// So the scan now SKIPS test modules and resumes after them, rather than
/// stopping at the first one. The end of a module is a `}` at column 0: an
/// item-position brace, the mirror of the item-position rules above, and far
/// more robust than counting braces through test bodies full of `json!({..})`
/// and string literals. If a file is ever formatted so that a top-level item
/// does not close at column 0, this reverts to over-scanning — a LOUD failure
/// (test code shows up in the census and a human dispositions it), which is
/// the correct direction for this instrument to fail.
fn production_lines(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut lines = text.lines().enumerate().peekable();
    let all: Vec<&str> = text.lines().collect();
    let mut skipping = false;
    while let Some((i, line)) = lines.next() {
        if skipping {
            // Item-position closing brace ends the module.
            if line == "}" {
                skipping = false;
            }
            continue;
        }
        if line.starts_with("#[cfg(test)]") {
            // Look ahead past blank lines for a module opener.
            let opens_mod = all[i + 1..]
                .iter()
                .find(|l| !l.trim().is_empty())
                .is_some_and(|l| {
                    let t = l.trim_start();
                    t.starts_with("mod ") || t.starts_with("pub mod ")
                });
            if opens_mod {
                skipping = true;
                continue;
            }
        }
        out.push(line);
    }
    out
}

/// The name defined by a `fn` item on this line, if any. The `fn` keyword
/// must sit in item position — start of the trimmed line, after any
/// visibility/modifier prefixes — so prose like "a new helper fn above" in a
/// comment can never hijack the enclosing-fn tracking (an innocent-edit red
/// is how a team learns to ignore red).
fn fn_item_name(line: &str) -> Option<String> {
    const PREFIXES: &[&str] = &[
        "pub(crate) ",
        "pub ",
        "async ",
        "const ",
        "unsafe ",
        "extern \"C\" ",
    ];
    let mut t = line.trim_start();
    loop {
        match PREFIXES.iter().find_map(|p| t.strip_prefix(p)) {
            Some(rest) => t = rest,
            None => break,
        }
    }
    let rest = t.strip_prefix("fn ")?;
    let name: String = rest
        .chars()
        .take_while(|c| c.is_alphanumeric() || *c == '_')
        .collect();
    if name.is_empty() { None } else { Some(name) }
}

/// Walk `src`, and for every line matching `symbols` (in the production
/// prefix, skipping registry fn definition lines when `skip_defs`) record
/// its trimmed text under `(file, enclosing fn)`.
fn census(symbols: &[&str], skip_defs: bool) -> BTreeMap<String, Vec<String>> {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut files = Vec::new();
    rs_files(&src, &mut files);

    let mut found: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for f in &files {
        let text = fs::read_to_string(f)
            .unwrap_or_else(|e| panic!("read {}: {e}", f.display()));
        let rel = f
            .strip_prefix(&src)
            .expect("walked file is under src")
            .to_str()
            .expect("utf-8 path")
            .replace('\\', "/");
        let mut current_fn = "(top-level)".to_string();
        let mut seen: BTreeMap<String, usize> = BTreeMap::new();
        for line in production_lines(&text) {
            if let Some(name) = fn_item_name(line) {
                let n = seen.entry(name.clone()).or_insert(0);
                *n += 1;
                current_fn = if *n == 1 { name } else { format!("{name}#{n}") };
            }
            if !symbols.iter().any(|s| line.contains(s)) {
                continue;
            }
            if skip_defs
                && line.contains("fn ")
                && REGISTRY_DEF_FNS.iter().any(|d| line.contains(d))
            {
                continue;
            }
            found
                .entry(format!("{rel}::{current_fn}"))
                .or_default()
                .push(line.trim().to_string());
        }
    }
    for lines in found.values_mut() {
        lines.sort();
    }
    found
}

fn expected(table: &[(&str, &[&str])]) -> BTreeMap<String, Vec<String>> {
    table
        .iter()
        .map(|(k, v)| (k.to_string(), v.iter().map(|s| s.to_string()).collect()))
        .collect()
}

/// Trimmed production lines of one named fn in one file under `src`, using
/// the same item-position fn tracking as `census`. Matching is on the base
/// name (a `#N` suffix, if the key carries one, is stripped): no file in the
/// pinned sets currently needs the suffix, and if one ever does, the line
/// census goes red first and schedules the human this helper would need.
fn fn_production_lines(rel: &str, want_fn: &str) -> Vec<String> {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let text = fs::read_to_string(src.join(rel))
        .unwrap_or_else(|e| panic!("read {rel}: {e}"));
    let want = want_fn.split('#').next().unwrap_or(want_fn);
    let mut current_fn = "(top-level)".to_string();
    let mut out = Vec::new();
    for line in production_lines(&text) {
        if let Some(name) = fn_item_name(line) {
            current_fn = name;
        }
        if current_fn == want {
            out.push(line.trim().to_string());
        }
    }
    out
}

#[test]
fn member_lct_consumer_census_is_exact() {
    let found = census(&[".member_lct("], false);
    let projected: Vec<(&str, &[&str])> = MEMBER_LCT_CENSUS
        .iter()
        .map(|(k, v, _)| (*k, *v))
        .collect();
    let expected = expected(&projected);
    assert_eq!(
        found, expected,
        "\n\nCENSUS RED — the naming-function consumer set changed.\n\
         This table pins ATTRIBUTION hygiene AND name-gates, not presence\n\
         (see header). Before editing it, read the delta and answer BOTH\n\
         questions: does this change who gets named, and does any derived\n\
         name get COMPARED to decide control flow? Assign the site's\n\
         SiteClass accordingly — a Predicate also pins its comparison in\n\
         MEMBER_LCT_PREDICATE_CENSUS — then record the reading in the header.\n\
         found:    {found:?}\n\
         expected: {expected:?}\n"
    );
}

/// The class column and the comparison-pin table must describe the same site
/// set, and every pinned comparison must exist verbatim in the named fn.
/// This is the assertion that makes a NEW refusal-on-a-name go red as a
/// gate: the author who tags a site `Predicate` is compile-compelled to pin
/// its comparison, and the author who weakens a comparison without touching
/// any `.member_lct(` line is caught here, where the line census is blind.
#[test]
fn member_lct_predicate_sites_pin_their_comparison() {
    let tagged: std::collections::BTreeSet<&str> = MEMBER_LCT_CENSUS
        .iter()
        .filter(|(_, _, c)| *c == SiteClass::Predicate)
        .map(|(k, _, _)| *k)
        .collect();
    let pinned: std::collections::BTreeSet<&str> =
        MEMBER_LCT_PREDICATE_CENSUS.iter().map(|(k, _)| *k).collect();
    assert_eq!(
        tagged, pinned,
        "\n\nCENSUS RED — the Predicate class column and the comparison-pin table\n\
         disagree. Every site that gates on a name must pin its comparison line,\n\
         and only those sites may appear in MEMBER_LCT_PREDICATE_CENSUS.\n\
         tagged: {tagged:?}\n\
         pinned: {pinned:?}\n"
    );
    for (site, lines) in MEMBER_LCT_PREDICATE_CENSUS {
        let (file, f) = site.rsplit_once("::").expect("site key is file::fn");
        let body = fn_production_lines(file, f);
        assert!(
            !body.is_empty(),
            "\n\nCENSUS RED — predicate site {site} resolves to no production lines:\n\
             the fn was renamed, moved, or deleted. Re-key or re-classify the site.\n"
        );
        for want in *lines {
            assert!(
                body.iter().any(|l| l == want),
                "\n\nCENSUS RED — the comparison this site is classified on was edited\n\
                 or removed.\nsite: {site}\nmissing line: {want}\n\
                 If the gate moved, re-pin it. If it was deleted, the site is no\n\
                 longer a Predicate and the class column must change DELIBERATELY —\n\
                 a name-gate quietly becoming hygiene is the defect this table\n\
                 exists to catch.\n"
            );
        }
    }
}

#[test]
fn member_registry_consumer_census_is_exact() {
    let found = census(REGISTRY_SYMBOLS, true);
    let expected = expected(REGISTRY_CENSUS);
    assert_eq!(
        found, expected,
        "\n\nCENSUS RED — the member-PRESENCE consumer set changed.\n\
         This test asserts the ENUMERATION, not the property (see header).\n\
         Before editing the table, read the new/removed call site and answer:\n\
         is this a safety use of presence? Then record that reading in the\n\
         header.\n\
         found:    {found:?}\n\
         expected: {expected:?}\n"
    );
}

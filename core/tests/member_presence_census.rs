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
//!   #80 defect class; what it pins is attribution hygiene — every place an
//!   identity is minted into a chain entry, an emit path, or the appeal
//!   self-filter. A red here asks "does this change who gets named?"
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
//! `core/src/**/*.rs`, truncate each file at its first `#[cfg(test)]` (test
//! modules are consumers of the *API*, not of *presence*), track the nearest
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
/// Every entry here was read by a person and judged a non-gating use
/// (attribution / emit-path identity resolution) on 2026-07-27. Editing this
/// table without performing that judgment on the delta is the one move this
/// test exists to make expensive.
///
/// Delta readings, recorded as the header requires:
/// - 2026-07-28 (kimi-code), merge with `main` at `bc24d82` (PR #67) added
///   `tool_open_appeals`: caller and appellant are resolved through
///   `member_lct` and compared for equality — the same NOT-SAME identity
///   comparison `tool_arbitrate_appeal` performs, here as queue-listing
///   advisory (`you_may_rule`). It names two existing identities to compare
///   them; it does not change who gets named, and it does not read the
///   registry (the presence table stayed green over the same merge).
const MEMBER_LCT_CENSUS: &[(&str, &[&str])] = &[
    ("server/handler.rs::gate_direct_tool", &[
        "let instance_lct = s.member_lct(&who.plugin_id);",
    ]),
    ("server/handler.rs::tool_appeal", &[
        "let appellant_lct = s.member_lct(&appellant.plugin_id);",
        "match (&appellant_lct, s.member_lct(id)) {",
    ]),
    ("server/handler.rs::tool_arbitrate_appeal", &[
        "let a = s.member_lct(&arbiter.plugin_id);",
        "let b = s.member_lct(appellant);",
    ]),
    ("server/handler.rs::tool_open_appeals", &[
        "let a = s.member_lct(&c.plugin_id);",
        "let b = s.member_lct(appellant);",
    ]),
    ("server/handler.rs::tool_query_policy", &[
        "let instance_lct = s.member_lct(&plugin_id_for_chain);",
        "let instance_lct = s.member_lct(&plugin_id_for_chain);",
    ]),
    ("server/handler.rs::tool_record_outcome", &[
        "let instance_lct = s.member_lct(&plugin_id);",
    ]),
    ("server/handler.rs::tool_record_reversal", &[
        "let subject_instance_lct = s.member_lct(&subject_plugin_id);",
    ]),
    ("server/handler.rs::tool_witness_adjudication", &[
        "let adjudicator_instance_lct = s.member_lct(&adjudicator.plugin_id);",
        "let subject_instance_lct = s.member_lct(&subject_plugin_id);",
    ]),
    ("server/handler.rs::tool_witness_decision", &[
        "let instance_lct = s.member_lct(&plugin_id);",
    ]),
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
    ]),
    ("server/http.rs::operator_adjudicate", &[
        "let subject_instance_lct = s.member_lct(&a.subject_plugin_id);",
    ]),
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
    ]),
    ("server/state.rs::apply_adjudication_ctx", &[
        "if let Some(subject_lct) = self.member_lct(subject_plugin_id) {",
    ]),
    ("server/state.rs::apply_judgment_ctx", &[
        "if let Some(subject_lct) = self.member_lct(plugin_id) {",
    ]),
    ("server/state.rs::apply_outcome_ctx", &[
        "if let Some(subject_lct) = self.member_lct(plugin_id) {",
    ]),
    ("server/state.rs::trust_entity_key", &[
        "match self.member_lct(plugin_id) {",
    ]),
];

/// Consumers of presence itself: trimmed text of every line touching
/// `member_registry` / `load_members(` / `ensure_member(` /
/// `attach_citizenship(` / `MemberRegistry::` / `.iter_sorted(`, minus the
/// three registry fns' own definition lines, keyed `(file, enclosing fn)`.
/// 8 keys, 9 lines.
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

/// The production prefix: everything before the trailing `#[cfg(test)] mod`.
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
fn prod_prefix(text: &str) -> &str {
    let mut off = 0usize;
    let mut lines = text.split_inclusive('\n').peekable();
    while let Some(line) = lines.next() {
        if line.starts_with("#[cfg(test)]") {
            // Look ahead past blank lines for a module opener.
            let opens_mod = text[off + line.len()..]
                .lines()
                .find(|l| !l.trim().is_empty())
                .map_or(false, |l| {
                    let t = l.trim_start();
                    t.starts_with("mod ") || t.starts_with("pub mod ")
                });
            if opens_mod {
                return &text[..off];
            }
        }
        off += line.len();
    }
    text
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
        for line in prod_prefix(&text).lines() {
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

#[test]
fn member_lct_consumer_census_is_exact() {
    let found = census(&[".member_lct("], false);
    let expected = expected(MEMBER_LCT_CENSUS);
    assert_eq!(
        found, expected,
        "\n\nCENSUS RED — the naming-function consumer set changed.\n\
         This table pins ATTRIBUTION hygiene, not presence (see header).\n\
         Before editing it, read the delta and answer: does this change who\n\
         gets named? Then record that reading in the header.\n\
         found:    {found:?}\n\
         expected: {expected:?}\n"
    );
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

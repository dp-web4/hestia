//! `DERIVATION_EVENT_TYPES` is a declaration with no enforcement. This is its guard.
//!
//! ## The defect class
//!
//! There are two curated event-type lists in this daemon and they fail in opposite
//! directions. `GOVERNANCE_EVENTS` (governance_ledger.rs) is a filter-IN followed by a
//! `match`, so its dangerous direction is *declared but not projected* — a name in the list
//! with no match arm admits rows and then drops them. That direction already has a drift
//! guard: `every_declared_governance_event_is_actually_projected`.
//!
//! `DERIVATION_EVENT_TYPES` is the reverse shape. It is an SQL prefilter — `scan_recent`
//! narrows the window *before* `derive()` sees it (http.rs:1094, http.rs:1127,
//! dashboard.rs:46) — and `derive()` then dispatches on a dozen `e.event_type == "..."`
//! comparisons. So the dangerous direction is *read but not declared*: a scorer whose
//! event type is missing from the list receives *zero rows*, forever, and reads as
//! "this never happens" rather than as a bug. Two filters in series; repairing the visible
//! one greens a zero. Nothing in the tree checked either direction — as of 2026-08-18,
//! `git grep DERIVATION_EVENT_TYPES` returns three call sites, one definition, and no test.
//!
//! ## Why now
//!
//! #502 declares `gate_escalation_expired` and `gate_escalation_withdrawn` in
//! `GOVERNANCE_EVENTS`, so a lapse and a withdrawal *render* differently in the ledger.
//! #503 makes the scoring asymmetry explicit: withdrawal is attributable member conduct and
//! belongs in the fold at 0.85, while expiry has no performer and stays out. The declared set
//! below is the UNION of the legacy list and the live governance prefilter, so adding a scorer
//! to only one list cannot silently zero the other path.
//!
//! ## What is asserted, and what each assertion is worth
//!
//! The two directions are separate tests, because a single equality assertion tells you the
//! sets differ and not which way — and the two ways need opposite remedies (add a scorer vs
//! widen the scan). The extractor asserts against *itself* too: an operand it cannot resolve
//! fails the test rather than being skipped, because a matcher that silently under-reads its
//! own input is the exact failure this file exists to catch.
//!
//! Both directions currently hold: ten names declared, ten names read, equal. That equality
//! is a measured result, not an assumption — and it is unpinned until this file exists.

use hestia::derivation::{
    DERIVATION_EVENT_TYPES, DERIVATION_GOVERNANCE_EVENT_TYPES, IDENTITY_ALIAS_EVENT,
};
use std::collections::BTreeSet;

const SRC: &str = include_str!("../src/derivation.rs");

/// Every event type named in an `event_type` comparison in the PRODUCTION region of
/// `derivation.rs` — everything before the first `#[cfg(test)]`. Test-module comparisons are
/// excluded deliberately: a name only a test mentions is not read by the fold, and including
/// them would let a fixture keep this guard green after its scorer was deleted.
fn event_types_read_by_the_fold() -> BTreeSet<String> {
    let prod = SRC
        .split("#[cfg(test)]")
        .next()
        .expect("split always yields one element");

    let (names, unresolved) = extract(prod);

    assert!(
        unresolved.is_empty(),
        "the extractor found event_type dispatch sites it cannot resolve to a name: \
         {unresolved:?}. Resolve them here — a skipped dispatch site makes both assertions \
         below vacuously weaker in the direction that hides a dead scorer."
    );

    // Positive control on the extractor itself. If the parse silently stops working — a
    // refactor to a helper, a rename — the difference sets go empty and BOTH tests below
    // pass while covering nothing. `policy_decision` is the fold's densest input
    // (temperament reads it at four sites); if it is absent, the extractor is broken, not
    // the code under test.
    assert!(
        names.contains("policy_decision"),
        "extractor recovered {} names and none of them is `policy_decision` — the parse is \
         broken, so an empty diff below would mean nothing. Names found: {names:?}",
        names.len()
    );

    names
}

// ---------------------------------------------------------------------------------------
// The extractor. It understands three dispatch forms, and each form it meets but cannot
// resolve to a set of names is reported in `unresolved` rather than skipped:
//
//   1. `x.event_type == LIT`, `!=`, with an optional `.as_str()`;
//   2. `matches!(x.event_type.as_str(), "a" | "b")`;
//   3. `match x.event_type.as_str() { "a" | "b" => .., "c" => .., _ => .. }`.
//
// Forms 2 and 3 arrived with the revision-event fold (#689 stage 1). Before that, form 2
// was refused outright and form 3 was SILENTLY skipped — the scrutinee has no `==`, so the
// comparison scan read it as "not a dispatch". A `match` arm is exactly as much a read of
// that name as a comparison is.
//
// What it still cannot see: a dispatch that never names `event_type` at the site (a helper
// that takes the string), and set-membership forms such as `[..].contains(&x.event_type)`.
// Neither exists in derivation.rs today.
// ---------------------------------------------------------------------------------------

fn is_ident_byte(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_'
}

/// If a comment, string literal or char literal starts at `i`, the index just past it.
/// A lone `'` (a lifetime or a label) is stepped over as one byte.
fn skip_non_code(b: &[u8], i: usize) -> Option<usize> {
    let rest = &b[i..];
    if rest.starts_with(b"//") {
        return Some(i + rest.iter().position(|c| *c == b'\n').unwrap_or(rest.len()));
    }
    if rest.starts_with(b"/*") {
        let end = rest
            .windows(2)
            .position(|w| w == b"*/")
            .expect("block comment in source is terminated");
        return Some(i + end + 2);
    }
    if rest[0] == b'"' {
        let mut j = i + 1;
        loop {
            match b.get(j) {
                None => panic!("string literal opened at byte {i} is not terminated"),
                Some(b'\\') => j += 2,
                Some(b'"') => return Some(j + 1),
                Some(_) => j += 1,
            }
        }
    }
    if rest[0] == b'r' && (i == 0 || !is_ident_byte(b[i - 1])) {
        let hashes = rest[1..].iter().take_while(|c| **c == b'#').count();
        if rest.get(1 + hashes) == Some(&b'"') {
            let mut j = i + 2 + hashes;
            loop {
                assert!(j < b.len(), "raw string opened at byte {i} is not terminated");
                if b[j] == b'"'
                    && b.len() >= j + 1 + hashes
                    && b[j + 1..j + 1 + hashes].iter().all(|c| *c == b'#')
                {
                    return Some(j + 1 + hashes);
                }
                j += 1;
            }
        }
    }
    if rest[0] == b'\'' {
        if rest.get(1) == Some(&b'\\') {
            let close = rest[3..]
                .iter()
                .position(|c| *c == b'\'')
                .expect("escaped char literal in source is terminated");
            return Some(i + 3 + close + 1);
        }
        let width = match rest.get(1) {
            Some(c) if *c >= 0xF0 => 4,
            Some(c) if *c >= 0xE0 => 3,
            Some(c) if *c >= 0xC0 => 2,
            _ => 1,
        };
        if rest.get(1 + width) == Some(&b'\'') {
            return Some(i + 2 + width);
        }
        return Some(i + 1);
    }
    None
}

/// The index just past the delimiter that closes the `(`, `[` or `{` at `open`.
fn close_of(b: &[u8], open: usize) -> usize {
    let mut depth = 0usize;
    let mut i = open;
    while i < b.len() {
        if let Some(j) = skip_non_code(b, i) {
            i = j;
            continue;
        }
        match b[i] {
            b'(' | b'[' | b'{' => depth += 1,
            b')' | b']' | b'}' => {
                depth -= 1;
                if depth == 0 {
                    return i + 1;
                }
            }
            _ => {}
        }
        i += 1;
    }
    panic!("delimiter opened at byte {open} is never closed");
}

/// First occurrence of `needle` in `b[from..to]` that sits outside every nested delimiter,
/// comment and literal.
fn find_top_level(b: &[u8], from: usize, to: usize, needle: &[u8]) -> Option<usize> {
    let mut depth = 0usize;
    let mut i = from;
    while i < to {
        if let Some(j) = skip_non_code(b, i) {
            i = j;
            continue;
        }
        if depth == 0 && b[i..to].starts_with(needle) {
            return Some(i);
        }
        match b[i] {
            b'(' | b'[' | b'{' => depth += 1,
            b')' | b']' | b'}' => depth = depth.checked_sub(1)?,
            _ => {}
        }
        i += 1;
    }
    None
}

/// `None`: the expression is not about `event_type`. `Some(true)`: it is exactly
/// `<path>.event_type` or `<path>.event_type.as_str()`. `Some(false)`: it mentions
/// `event_type` through something else (`.to_lowercase()`, a call, a tuple), so the arms
/// cannot be read as event-type names.
fn event_type_scrutinee(expr: &str) -> Option<bool> {
    let expr = expr.trim();
    if !expr.contains("event_type") {
        return None;
    }
    let core = expr.strip_suffix(".as_str()").unwrap_or(expr);
    let core = core.trim_start_matches(['&', '*']);
    Some(
        core.ends_with(".event_type")
            && core.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '.'),
    )
}

/// Resolve one pattern (`"a" | "b"`) to names. Anything that is not a string literal or a
/// known constant — a binding, a guard, a range — is unresolved. `_` is accepted only as a
/// `match` arm, where it names nothing; in `matches!` it would match every event type.
fn pattern_names(
    pat: &str,
    wildcard_ok: bool,
    names: &mut BTreeSet<String>,
    unresolved: &mut Vec<String>,
) {
    for alt in pat.split('|') {
        let alt = alt.trim();
        if alt == "_" && wildcard_ok {
            continue;
        }
        let literal = alt
            .strip_prefix('"')
            .and_then(|s| s.strip_suffix('"'))
            .filter(|s| !s.contains('"') && !s.contains('\\'));
        match (literal, alt) {
            (Some(lit), _) => {
                names.insert(lit.to_string());
            }
            (None, "IDENTITY_ALIAS_EVENT") => {
                names.insert(IDENTITY_ALIAS_EVENT.to_string());
            }
            (None, other) => unresolved.push(format!("<pattern `{other}`>")),
        }
    }
}

/// Read every arm pattern of the `match` block whose `{` is at `open`.
fn match_arm_names(
    src: &str,
    open: usize,
    names: &mut BTreeSet<String>,
    unresolved: &mut Vec<String>,
) {
    let b = src.as_bytes();
    let end = close_of(b, open) - 1;
    let mut i = open + 1;
    loop {
        loop {
            while i < end && b[i].is_ascii_whitespace() {
                i += 1;
            }
            if i < end && (b[i..].starts_with(b"//") || b[i..].starts_with(b"/*")) {
                i = skip_non_code(b, i).expect("a comment starts here");
            } else {
                break;
            }
        }
        if i >= end {
            break;
        }
        let Some(arrow) = find_top_level(b, i, end, b"=>") else {
            unresolved.push("<match arm without `=>`>".to_string());
            break;
        };
        pattern_names(&src[i..arrow], true, names, unresolved);
        i = arrow + 2;
        while i < end && b[i].is_ascii_whitespace() {
            i += 1;
        }
        if i < end && b[i] == b'{' {
            i = close_of(b, i);
            while i < end && b[i].is_ascii_whitespace() {
                i += 1;
            }
            if i < end && b[i] == b',' {
                i += 1;
            }
        } else {
            i = find_top_level(b, i, end, b",").map_or(end, |c| c + 1);
        }
    }
}

/// Forms 2 and 3: `matches!(..)` and `match .. { .. }` whose scrutinee is the event type.
fn extract_match_forms(prod: &str, names: &mut BTreeSet<String>, unresolved: &mut Vec<String>) {
    let b = prod.as_bytes();
    let mut i = 0;
    while i < b.len() {
        if let Some(j) = skip_non_code(b, i) {
            i = j;
            continue;
        }
        let at_word_start = i == 0 || !is_ident_byte(b[i - 1]);
        if at_word_start && b[i..].starts_with(b"matches!(") {
            let open = i + "matches!".len();
            let (lo, hi) = (open + 1, close_of(b, open) - 1);
            match find_top_level(b, lo, hi, b",") {
                Some(comma) => match event_type_scrutinee(&prod[lo..comma]) {
                    None => {}
                    Some(false) => unresolved
                        .push(format!("<matches! scrutinee `{}`>", prod[lo..comma].trim())),
                    Some(true) => {
                        let pat = prod[comma + 1..hi].trim().trim_end_matches(',');
                        pattern_names(pat, false, names, unresolved);
                    }
                },
                None => {
                    if prod[lo..hi].contains("event_type") {
                        unresolved.push(format!("<matches! `{}`>", prod[lo..hi].trim()));
                    }
                }
            }
            i = open + 1;
            continue;
        }
        if at_word_start
            && b[i..].starts_with(b"match")
            && b.get(i + 5).is_some_and(|c| c.is_ascii_whitespace())
        {
            let from = i + 5;
            if let Some(open) = find_top_level(b, from, b.len(), b"{") {
                match event_type_scrutinee(&prod[from..open]) {
                    None => {}
                    Some(false) => unresolved
                        .push(format!("<match scrutinee `{}`>", prod[from..open].trim())),
                    Some(true) => match_arm_names(prod, open, names, unresolved),
                }
            }
            i = from;
            continue;
        }
        i += 1;
    }
}

/// Every event type the given source dispatches on, and every dispatch site that could not
/// be resolved to names.
fn extract(prod: &str) -> (BTreeSet<String>, Vec<String>) {
    let mut names = BTreeSet::new();
    let mut unresolved: Vec<String> = Vec::new();

    extract_match_forms(prod, &mut names, &mut unresolved);

    // Form 1: `x.event_type == LIT`, `!=`, and an optional `.as_str()`. Any other method
    // chain between the field and the operator is unresolved (see below).
    let mut rest = prod;
    while let Some(i) = rest.find("event_type") {
        rest = &rest[i + "event_type".len()..];

        // Consume a `.ident()` chain, remembering whether it was value-preserving.
        let mut tail = rest.trim_start();
        let mut chain_is_transparent = true;
        while let Some(after_dot) = tail.strip_prefix('.') {
            let ident: String = after_dot
                .chars()
                .take_while(|c| c.is_alphanumeric() || *c == '_')
                .collect();
            let Some(after_call) = after_dot[ident.len()..].strip_prefix("()") else {
                break;
            };
            if ident != "as_str" {
                chain_is_transparent = false;
            }
            tail = after_call.trim_start();
        }

        let Some(operand) = tail
            .strip_prefix("==")
            .or_else(|| tail.strip_prefix("!="))
            .map(str::trim_start)
        else {
            continue; // a declaration, a construction, or a clone — not a dispatch.
        };

        if !chain_is_transparent {
            unresolved.push("<method chain>".to_string());
            continue;
        }

        if let Some(after_quote) = operand.strip_prefix('"') {
            let end = after_quote
                .find('"')
                .expect("string literal in source is terminated");
            names.insert(after_quote[..end].to_string());
        } else {
            let ident: String = operand
                .chars()
                .take_while(|c| c.is_alphanumeric() || *c == '_')
                .collect();
            match ident.as_str() {
                "IDENTITY_ALIAS_EVENT" => {
                    names.insert(IDENTITY_ALIAS_EVENT.to_string());
                }
                _ => unresolved.push(ident),
            }
        }
    }

    (names, unresolved)
}

fn set(names: &[&str]) -> BTreeSet<String> {
    names.iter().map(|s| (*s).to_string()).collect()
}

/// The extractor against source it has never seen: all three forms, with the things that
/// break a naive brace counter (a `}` in a string, a nested block, a char literal, a
/// comment) inside the arm bodies.
#[test]
fn the_extractor_reads_comparisons_matches_and_match_arms() {
    let src = r##"
        fn f(e: &E) -> Option<u8> {
            if e.event_type == "cmp_a" || e.event_type.as_str() != "cmp_b" { return None; }
            let hit = matches!(e.event_type.as_str(), "mac_a" | "mac_b");
            let alias = matches!(&e.event_type, IDENTITY_ALIAS_EVENT);
            match e.event_type.as_str() {
                // a comment with a brace } and an arrow =>
                "arm_a" | "arm_b" => {
                    if hit { log("} => \"not_a_name\""); }
                    let c = '}';
                    Some(1)
                }
                "arm_c" => inner(|| { 2 }),
                "arm_d" => match e.kind { "not_an_event_type" => Some(3), _ => None },
                _ => None,
            }
        }
    "##;
    let (names, unresolved) = extract(src);
    assert!(unresolved.is_empty(), "unresolved: {unresolved:?}");
    assert_eq!(
        names,
        set(&[
            "cmp_a", "cmp_b", "mac_a", "mac_b", IDENTITY_ALIAS_EVENT, "arm_a", "arm_b", "arm_c",
            "arm_d",
        ])
    );
}

/// The other half of the contract: a dispatch the extractor cannot turn into names is
/// REPORTED. Each line below is one way a scorer could read an event type that this guard
/// would otherwise claim to cover and not cover.
#[test]
fn the_extractor_reports_every_dispatch_it_cannot_resolve() {
    let cases = [
        // a binding arm reads every event type
        r#"match e.event_type.as_str() { other => score(other) }"#,
        // a guard: the name is read only sometimes
        r#"match e.event_type.as_str() { "a" if strict => 1, _ => 0 }"#,
        // the scrutinee is transformed, so the arms are not event-type names
        r#"match e.event_type.to_lowercase().as_str() { "a" => 1, _ => 0 }"#,
        r#"match (e.event_type.as_str(), e.ok) { ("a", true) => 1, _ => 0 }"#,
        // matches! with a guard, a wildcard, a constant this file does not know
        r#"matches!(e.event_type.as_str(), "a" if strict)"#,
        r#"matches!(e.event_type.as_str(), _)"#,
        r#"matches!(e.event_type.as_str(), SOME_OTHER_CONST)"#,
        r#"matches!(e.event_type.trim(), "a")"#,
        // the comparison form's own refusals, unchanged
        r#"e.event_type.to_lowercase() == "a""#,
        r#"e.event_type == SOME_OTHER_CONST"#,
    ];
    for case in cases {
        let (names, unresolved) = extract(case);
        assert!(
            !unresolved.is_empty(),
            "`{case}` was read as fully resolved (names {names:?}); it must be reported"
        );
    }
}

/// A red control for the guard itself: remove one dispatch form from the source and the
/// name it carried must drop out of the read set. Run against the real file, so this fails
/// if a refactor leaves the extractor reading nothing through `match` or `matches!`.
#[test]
fn the_match_forms_carry_names_the_comparison_form_does_not() {
    let prod = SRC
        .split("#[cfg(test)]")
        .next()
        .expect("split always yields one element");
    let (all, _) = extract(prod);
    let mut by_match = BTreeSet::new();
    let mut ignored = Vec::new();
    extract_match_forms(prod, &mut by_match, &mut ignored);
    assert!(
        by_match.is_subset(&all),
        "match-form names must be part of the read set: {by_match:?} vs {all:?}"
    );
    // If derivation.rs stops using these forms, this test has nothing to say and should be
    // deleted with them — it must not go quietly green.
    assert!(
        !by_match.is_empty(),
        "derivation.rs no longer dispatches on event_type through `match` or `matches!`; \
         delete this test (and, if nothing else uses them, the match-form parser)."
    );
}

fn declared() -> BTreeSet<String> {
    DERIVATION_EVENT_TYPES
        .iter()
        .chain(DERIVATION_GOVERNANCE_EVENT_TYPES.iter())
        .map(|s| (*s).to_string())
        .collect()
}

/// The direction that silently zeroes a scorer.
#[test]
fn every_event_type_the_fold_reads_is_declared_for_the_sql_prefilter() {
    let read = event_types_read_by_the_fold();
    let declared = declared();
    let undeclared: Vec<&String> = read.difference(&declared).collect();
    assert!(
        undeclared.is_empty(),
        "SILENT ZERO: derive() dispatches on {undeclared:?}, and the SQL prefilter passed at \
         http.rs (x2) and dashboard.rs does not fetch them. Those scorers receive an empty \
         window on every fold — they do not under-count, they count nothing, and the trust \
         verdict reads as though the conduct never occurred. Remedy: add the name to \
         DERIVATION_EVENT_TYPES. Adding it to GOVERNANCE_EVENTS does NOT fix this; that is a \
         different list read by a different surface."
    );
}

/// The harmless direction, asserted anyway — because "the list is what the fold reads" is a
/// claim the comment at both call sites makes ("Fetch what the model DECLARES it reads"),
/// and an unread name makes that comment false and widens every scan for nothing.
#[test]
fn every_declared_event_type_is_actually_read() {
    let read = event_types_read_by_the_fold();
    let declared = declared();
    let unread: Vec<&String> = declared.difference(&read).collect();
    assert!(
        unread.is_empty(),
        "DEAD WIDENING: DERIVATION_EVENT_TYPES declares {unread:?}, which no comparison in \
         derivation.rs reads. Every fold pays SQL for those rows and folds none of them. \
         Either a scorer was deleted and its declaration left behind (remove the name), or a \
         scorer was declared before it was written (write it, or drop the name until it is). \
         This direction is cheap; it is here so the failure names WHICH way the two disagree."
    );
}

/// The prefilter is only load-bearing if every fold call site applies the SAME one. Two
/// call sites with different windows would score the same member differently depending on
/// which endpoint you asked, and neither would be wrong on its own terms.
///
/// THIS TEST CAUGHT EXACTLY THAT, and then caught its own repair. Measured 2026-08-23:
/// dashboard.rs passed `STATS_WINDOW` (2,000 rows ≈ 17 hours) while the two http.rs routes
/// passed `DERIVATION_SCAN` (10,000) — the surface a human looked at reached back five
/// times less far than the API answering for it, and both named `DERIVATION_EVENT_TYPES`,
/// so the FILE-grained assertion below went green through the whole divergence. The
/// mention was never the invariant; the ARGUMENT was.
///
/// The repair removed the ambiguity rather than parsing it: the ordinary sites take their
/// window from `derivation::scan_window`, one function, split budgets inside it. The
/// event-triggered cache has ONE explicitly audited alternative: its per-member call to
/// `scan_subject_window`, introduced for #578. That alternative must prove population parity
/// behaviorally (aliases, global events, backfill and replay); naming it here only prevents
/// an unreviewed third window from slipping into another fold. It is not evidence of parity.
///
/// GRAIN, stated because it bounds what a green here means: still FILE-grained. A file
/// that calls `scan_window` and ALSO hand-builds a second window still passes. Catching
/// that needs the call's arguments, and this test has always declined to write a parser —
/// bare `scan_recent` cannot stand in for it, because dashboard.rs legitimately reads a
/// stats/feed window that way and it is not a fold at all.
#[test]
fn every_fold_call_site_applies_the_declared_prefilter() {
    let src_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut checked = Vec::new();
    let mut offenders = Vec::new();

    let mut stack = vec![src_root];
    while let Some(dir) = stack.pop() {
        for e in std::fs::read_dir(&dir).expect("core/src is readable") {
            let path = e.expect("dir entry").path();
            if path.is_dir() {
                stack.push(path);
                continue;
            }
            if path.extension().and_then(|s| s.to_str()) != Some("rs") {
                continue;
            }
            let body = std::fs::read_to_string(&path).expect("source file is utf8");
            // Skip derivation.rs itself: it DEFINES derive() and tests it directly with
            // hand-built windows, which is what a unit test is supposed to do.
            if path.file_name().and_then(|s| s.to_str()) == Some("derivation.rs") {
                continue;
            }
            let prod = body.split("#[cfg(test)]").next().unwrap_or(&body);
            // Every fold entry point: `derive`, `derive_with_volume` (which carries the
            // grain's persisted lifetime totals), and `derive_evidence` — the window half the
            // event-triggered cache (`derivation_cache.rs`) folds and keeps. Renaming a call
            // site must not be able to empty this scan silently — the assertion below fails
            // loudly if it does. (`with_volume` is NOT an entry point: it reads no window.)
            let folds = prod.contains("derivation::derive(")
                || prod.contains("derivation::derive_with_volume(")
                || prod.contains("derivation::derive_evidence(");
            if folds {
                checked.push(path.display().to_string());
                // Ordinary folds use the canonical prefiltered path. The cache's exact
                // subject-indexed call is the sole declared alternative; any other custom
                // window remains an offender.
                let subject_indexed_cache = path.file_name().and_then(|s| s.to_str())
                    == Some("derivation_cache.rs")
                    && prod.contains(
                        "derivation::scan_subject_window(chain_store, &plugin_id)"
                    );
                if !prod.contains("derivation::scan_window(") && !subject_indexed_cache {
                    offenders.push(path.display().to_string());
                }
            }
        }
    }

    assert!(
        !checked.is_empty(),
        "no file outside derivation.rs calls `derivation::derive(` or \
         `derivation::derive_with_volume(` — either the fold lost its callers or this scan \
         stopped finding them. Either way the two tests above are guarding a list nothing \
         reads, and that is worth knowing."
    );
    assert!(
        offenders.is_empty(),
        "{offenders:?} fold trust without the canonical `derivation::scan_window` or the \
         cache's one sanctioned subject-indexed call. Any other custom prefilter or BUDGET \
         can score a member from a different population than /api/trust/derivation. The \
         subject-indexed exception separately owes behavioral parity evidence. Checked: \
         {checked:?}"
    );
}

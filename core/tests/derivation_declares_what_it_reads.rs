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
//! `GOVERNANCE_EVENTS`, so a lapse and a withdrawal now *render* differently in the ledger.
//! Neither name is in `DERIVATION_EVENT_TYPES`, so both are still filtered out in SQL and
//! *score* identically — invisibly. That asymmetry (#503) is not a typo in #502; it is what
//! an unguarded declaration looks like from the outside. This test does not decide whether
//! the fold *should* see those events — that is an operator question. It makes the answer
//! **loud** instead of silent: whichever way it is decided, the list and the scorers can no
//! longer disagree without a red test.
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

use hestia::derivation::{DERIVATION_EVENT_TYPES, IDENTITY_ALIAS_EVENT};
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

    // The extractor understands `x.event_type == LIT`, `!=`, and an optional `.as_str()`.
    // `matches!(e.event_type.as_str(), "a" | "b")` would parse as "no comparison" and be
    // skipped, so refuse to run rather than under-read. Same for any other method chain
    // between the field and the operator (see `unresolved` below).
    for (i, line) in prod.lines().enumerate() {
        assert!(
            !(line.contains("event_type") && line.contains("matches!")),
            "derivation.rs:{} dispatches on event_type through `matches!`, which this \
             extractor does not parse. Teach it that form before trusting this guard: an \
             unparsed dispatch site is a scorer this test claims to cover and does not.",
            i + 1
        );
    }

    let mut names = BTreeSet::new();
    let mut unresolved: Vec<String> = Vec::new();
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

    assert!(
        unresolved.is_empty(),
        "the extractor found event_type comparisons it cannot resolve to a name: {unresolved:?}. \
         Resolve them here — a skipped dispatch site makes both assertions below vacuously \
         weaker in the direction that hides a dead scorer."
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

fn declared() -> BTreeSet<String> {
    DERIVATION_EVENT_TYPES
        .iter()
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
/// The repair removed the ambiguity rather than parsing it: all three sites now take their
/// window from `derivation::scan_window`, one function, split budgets inside it. So the
/// assertion is no longer "names the declared list somewhere" — it is "gets its window
/// from the ONE place that applies the declared prefilters". That is strictly stronger
/// than what this test asserted before, and it needs no parser: a second, unprefiltered
/// fold beside a prefiltered one now fails, because the check is that a folding file
/// obtains windows ONLY through `scan_window`.
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
            // Both fold entry points: `derive` and `derive_with_volume` (which carries the
            // grain's persisted lifetime totals). Renaming a call site must not be able to
            // empty this scan silently — the assertion below fails loudly if it does.
            let folds = prod.contains("derivation::derive(")
                || prod.contains("derivation::derive_with_volume(");
            if folds {
                checked.push(path.display().to_string());
                // The window must come from the ONE prefiltered path. A file that builds
                // its own window with `scan_recent` is exactly the divergence that let the
                // dashboard read 17 hours while the API read 3.6 days.
                // NOT also flagging bare `scan_recent` in the file: dashboard.rs reads a
                // stats/feed window that way and it is not a derivation fold. Separating
                // those needs the call's ARGUMENTS, which is the parser this test has
                // always declined to write.
                if !prod.contains("derivation::scan_window(") {
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
        "{offenders:?} fold trust without taking the window from `derivation::scan_window`, \
         or build one by hand with `scan_recent` alongside it. A fold whose window came from \
         a different prefilter or a different BUDGET scores the same member from a different \
         population than /api/trust/derivation does — measured 2026-08-23, that was 17 hours \
         of chain against 3.6 days, and both sites named the declared list. Checked: \
         {checked:?}"
    );
}

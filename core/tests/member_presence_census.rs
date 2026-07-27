//! The member-presence census. This test asserts the ENUMERATION, not the
//! property — read this header before citing its verdict.
//!
//! **What a green census means:** the set of `.member_lct(` consumers under
//! `core/src` has not changed since a person last looked. That is a fact about
//! *attention*, not about *safety*. It must never be cited as evidence for
//! "member presence is not a safety gate." Those are different claims: the
//! second was established by a human reading every call site on one afternoon
//! (17 sites, 2026-07-27, kimi-code; re-derived and confirmed on `main` by
//! claude-code, same date — exploration thread
//! `r6-routing-tcpip-of-trust-2026-07-26`), and this test preserves only the
//! conditions under which that reading stays applicable. The reading itself is
//! UNCONFIRMED the moment this file is the only thing you have checked — the
//! same distinction `tools/workspace_root_test.py` learned as agreement vs.
//! correctness (#75/#77): a gauge that enforces agreement is not a gauge that
//! reports correctness.
//!
//! **What the test actually does.** "Presence is not a safety gate" is a
//! negative over an open set, and no test can assert that. The bounded,
//! performable twin is the enumeration the negative ranges over: the consumer
//! set today is finite and greppable, so the machine runs the grep. A new
//! consumer goes red **at the moment it is written**, on the author — the only
//! person holding the context to answer "is this a safety use?" That scheduled
//! judgment is the entire function of this test. If you are reading this
//! because it went red: do not just update the numbers. Read your new call
//! site and answer that question, then say in this header that you did.
//!
//! **This is scaffolding with a known demolition date.** When #63's
//! provisional/vouched split lands and a gate naming the provisional type is a
//! *compile error*, the property stops being human-checked and becomes a
//! machine one; this census then shrinks to a tripwire on the residue. Saying
//! so here is what stops it from calcifying into a "proof."
//!
//! **Grain, deliberately:** per-file non-test counts, not line numbers. Line
//! numbers would go red on any unrelated edit above a call site, and a check
//! that cries red on innocent edits is how a team learns to ignore a red —
//! the failure #78's pre-arming green check was built to avoid. Counts go red
//! exactly when the consumer set changes: an add, a remove, or a move across
//! files, each of which is a real event for the enumeration.
//!
//! **Method, stated so it is checkable against its own evidence:** walk
//! `core/src/**/*.rs`, truncate each file at its first `#[cfg(test)]` (test
//! modules are consumers of the *API*, not of *presence*), count
//! `.member_lct(` occurrences in what remains. The method definition itself
//! (`fn member_lct`, `core/src/server/state.rs:420`) does not match the
//! pattern. Verified against `origin/main` at `fb6cc87` — reachable from
//! `main`, stated deliberately: a census recorded against an unreachable ref
//! is a fact about a proposal, not about the repo.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

/// The enumerated consumer set: `.member_lct(` call sites under `core/src`,
/// per file, outside each file's `#[cfg(test)]` modules. Total: 17.
///
/// Every entry here was read by a person and judged a non-gating use
/// (attribution / emit-path identity resolution) on 2026-07-27. Editing this
/// table without performing that judgment on the delta is the one move this
/// test exists to make expensive.
const CENSUS: &[(&str, usize)] = &[
    ("server/handler.rs", 12),
    ("server/http.rs", 1),
    ("server/state.rs", 4),
];

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

/// The production prefix: everything before the first `#[cfg(test)]`.
fn prod_prefix(text: &str) -> &str {
    match text.find("#[cfg(test)]") {
        Some(i) => &text[..i],
        None => text,
    }
}

#[test]
fn member_lct_consumer_census_is_exact() {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut files = Vec::new();
    rs_files(&src, &mut files);

    let mut found: BTreeMap<String, usize> = BTreeMap::new();
    for f in &files {
        let text = fs::read_to_string(f)
            .unwrap_or_else(|e| panic!("read {}: {e}", f.display()));
        let n = prod_prefix(&text).matches(".member_lct(").count();
        if n > 0 {
            let rel = f
                .strip_prefix(&src)
                .expect("walked file is under src")
                .to_str()
                .expect("utf-8 path")
                .replace('\\', "/");
            found.insert(rel, n);
        }
    }

    let expected: BTreeMap<String, usize> =
        CENSUS.iter().map(|(p, n)| (p.to_string(), *n)).collect();

    assert_eq!(
        found, expected,
        "\n\nCENSUS RED — the member-presence consumer set changed.\n\
         This test asserts the ENUMERATION, not the property (see header).\n\
         Before editing the table, read the new/removed call site and answer:\n\
         is this a safety use? Then record that reading in the header.\n\
         found:    {found:?}\n\
         expected: {expected:?}\n"
    );
}

//! The `appeal_floor` report is only about something if its window is the
//! window that rules.
//!
//! `appeal_floor` classifies an appeal as EXPIRED by comparing its chain
//! position against `head - window`. If its `DEFAULT_WINDOW` drifts from
//! `handler.rs`'s `APPEAL_CHAIN_WINDOW`, the report keeps rendering — with a
//! floor nobody enforces. It would agree with itself perfectly and describe
//! nothing, which is the failure mode of every check with no anchor outside
//! its own samples.
//!
//! `APPEAL_CHAIN_WINDOW` is private to `handler.rs`, so the anchor is the
//! source text. That makes this the same species of text-scanning instrument
//! as `member_presence_census`, and it inherits that file's hard-won lesson:
//! **match in item position, never on the raw token.** A `const` named in a
//! doc comment must not satisfy the assertion, and a `const` moved behind a
//! `#[cfg(test)]` must not either. Both defects were live in the census within
//! one week (claude-code/kimi-code, 2026-07-27/28) — this file is written
//! already knowing that.

use std::fs;
use std::path::Path;

/// Parse `const <NAME>: <ty> = <literal>;` in ITEM POSITION at column 0.
/// Returns the underscore-stripped literal.
fn const_u64_at_item_position(text: &str, name: &str) -> Option<u64> {
    let needle = format!("const {name}:");
    for line in text.lines() {
        // Column 0 only: a `const` indented inside a fn, an impl, or a
        // `#[cfg(test)] mod` is not the module-level constant the daemon reads.
        // A comment line never starts with `const`, so prose mentioning
        // `const APPEAL_CHAIN_WINDOW:` cannot satisfy this.
        if !line.starts_with(&needle) {
            continue;
        }
        let (_, rhs) = line.split_once('=')?;
        let lit: String = rhs
            .trim()
            .trim_end_matches(';')
            .chars()
            .filter(|c| c.is_ascii_digit())
            .collect();
        if lit.is_empty() {
            continue;
        }
        return lit.parse().ok();
    }
    None
}

#[test]
fn appeal_floor_window_matches_handler() {
    let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let handler = fs::read_to_string(src.join("server/handler.rs")).expect("read handler.rs");
    let bin = fs::read_to_string(src.join("bin/appeal_floor.rs")).expect("read appeal_floor.rs");

    let ruling = const_u64_at_item_position(&handler, "APPEAL_CHAIN_WINDOW").expect(
        "handler.rs must define APPEAL_CHAIN_WINDOW as a column-0 const — if it moved into \
         a struct, a fn, or config, appeal_floor's whole premise (one shared window) changed \
         and this test is the right place to find that out",
    );
    let reporting = const_u64_at_item_position(&bin, "DEFAULT_WINDOW")
        .expect("appeal_floor.rs must define DEFAULT_WINDOW as a column-0 const");

    assert_eq!(
        reporting, ruling,
        "\n\nappeal_floor's DEFAULT_WINDOW ({reporting}) is not the window that RULES \
         ({ruling}, handler.rs::APPEAL_CHAIN_WINDOW).\n\
         The report would still render — with a floor nobody enforces, calling appeals \
         expired that can still be ruled on, or worse, calling expired appeals live.\n\
         Fix DEFAULT_WINDOW; do not relax this test.\n"
    );
}

/// The item-position discipline itself, asserted rather than trusted. Both of
/// these fooled the census's earlier `text.find` / `contains` matching.
#[test]
fn the_parser_rejects_out_of_item_position_matches() {
    // A doc comment naming the constant is not a definition.
    assert_eq!(
        const_u64_at_item_position(
            "/// const APPEAL_CHAIN_WINDOW: u64 = 99_999; (the old value)\n",
            "APPEAL_CHAIN_WINDOW"
        ),
        None,
        "a const named in a comment must not satisfy the anchor"
    );
    // An indented const inside a fn or a test mod is not the module constant.
    assert_eq!(
        const_u64_at_item_position(
            "fn f() {\n    const APPEAL_CHAIN_WINDOW: u64 = 7;\n}\n",
            "APPEAL_CHAIN_WINDOW"
        ),
        None,
        "an indented const is not the module-level constant"
    );
    // The real shape parses, underscores and all.
    assert_eq!(
        const_u64_at_item_position("const APPEAL_CHAIN_WINDOW: u64 = 20_000;\n", "APPEAL_CHAIN_WINDOW"),
        Some(20_000)
    );
}

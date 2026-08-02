//! Category coverage: every policy category the code MINTS, declared against
//! whether any shipped rule actually MATCHES it.
//!
//! ## The defect class this schedules judgment on
//!
//! `gate_direct_tool` builds a `PolicyAction` with a `category` and asks the
//! engine. The engine matches a rule whose `match.categories` contains that
//! string. If no shipped rule names the category, the evaluation returns the
//! config's `default_policy` — `Allow` on every built-in preset except
//! `strict`. So the call site reads as a gate, the reviewer reads it as a
//! gate, and it admits everything. **Gate installed ≠ gate enforced** — the
//! same class as the `witness_append` finding (classifier at
//! `policy/extract.rs`, call site at `handler.rs::tool_request_witness`, no
//! shipped rule; verified independently by kimi-code and claude-code,
//! 2026-07-28), and its third instance in one week.
//!
//! Default-allow is not itself a bug. A category can be deliberately
//! ungated — `member_notify` says so out loud in `server/state.rs`
//! ("law-gateable but default-allow on a permissive base", 2026-07-24). The
//! bug is default-allow that *nobody decided*. This test does not forbid
//! default-allow; it forbids default-allow being **silent**.
//!
//! ## Two producers, not one
//!
//! A category string reaching the engine has two origins, and an audit of
//! either alone misses half the surface:
//!
//! 1. **`gate_direct_tool` call sites** (`server/handler.rs`) — the daemon's
//!    direct-MCP gate, where the category is a hand-written literal argument.
//! 2. **`policy::extract::classify`** — the hook-side tool→category map that
//!    labels every ordinary tool call (`Bash`, `Read`, …) before evaluation.
//!
//! `witness_append` is minted by both. `mesh_egress` only by the first,
//! `command` only by the second. Enumerating one producer against the rule
//! set is the mistake this file exists to not repeat: a class fix that scopes
//! to the one broken sample you happened to hold is not a class fix.
//!
//! ## What a green run means, and what it does not
//!
//! Green means: the minted-category set has not changed since a person last
//! looked, and each category's declared coverage still matches whether a
//! built-in preset rule names it. That is a fact about **attention plus the
//! built-in presets**. It is NOT a claim that the enforcement is adequate,
//! and it explicitly does not range over:
//!
//! * **Operator-installed and role/instance overlay rules.** A deployment can
//!   ship a `mesh_egress` rule this test never sees; the coverage column
//!   reads "no BUILT-IN rule names it," not "ungoverned everywhere."
//! * **Rules that reach the same act via `tools:` instead of `categories:`.**
//!   `command` is declared `DefaultAllow` below even though the safety preset
//!   is full of `Bash` rules — because those match on `tools`, so a rule
//!   author writing `categories: ["command"]` gets silence. That is the
//!   distinction the column reports and the reason `classify`'s own doc
//!   comment (which lists `command` among "the ones the preset rules
//!   reference") is wrong today.
//! * **Whether the rule that exists is the right rule.** `credential_access`
//!   is `Ruled`, but the only rule naming it also carries secret-file
//!   `target_patterns` — so `tool_notify`'s `credential_access` gate (a
//!   category reuse for an outward message, not a secret read) matches no
//!   pattern and allows. Coverage is not efficacy. Read the rule.
//!
//! Stated plainly because a coverage table is exactly the artifact someone
//! will later cite as "the categories are governed."
//!
//! ## Method
//!
//! Source-scanning, in the `member_presence_census` lineage and inheriting
//! its lessons: comments are stripped before parsing (a category name in
//! prose must not satisfy the enumeration), the `fn gate_direct_tool`
//! definition line is excluded, and every match is keyed by
//! `(file, enclosing fn)` so a move goes red. Call arguments are read by
//! balanced-paren scan with string-literal awareness; the category is the
//! second string literal of the call, matching the signature
//! `(s, who, tool_name, category, target)`.
//!
//! Blind spot, stated: a category built at runtime rather than written as a
//! literal is invisible here. Today every call site passes a `&'static str`
//! literal and the signature requires it, so the blind spot is closed by the
//! type — if that ever loosens, this note is the warning.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

#[derive(Debug, PartialEq, Eq)]
enum Coverage {
    /// A built-in preset rule names this category in `match.categories`.
    Ruled,
    /// No built-in preset rule names it: evaluation falls through to
    /// `default_policy`. The string is the recorded reason a person accepted
    /// that — this is the "say default-allow out loud" requirement.
    DefaultAllow(&'static str),
}

use Coverage::{DefaultAllow, Ruled};

/// Every category minted by either producer, its declared coverage, and the
/// `(file, enclosing fn)` sites that mint it.
///
/// Editing this table without reading the delta is the one move this test
/// exists to make expensive. When a new category appears, answer at write
/// time: *should law be able to deny this act?* If yes, ship a rule. If no,
/// write down why here.
///
/// Readings recorded:
/// - 2026-07-28 (claude-code), initial. Eight of twelve categories are
///   default-allow; none had ever been written down as such. `witness_append`
///   is the one whose absence was independently found and is load-bearing:
///   `hestia_request_witness` lets a caller append audit history, and the
///   comment at its classifier arm says law "must be able to deny it for
///   unattended roles the same way it denies credential_access" — the
///   capability exists, the rule does not. Filed as its own item rather than
///   fixed here: shipping a deny rule is a law change, and law changes are
///   dp's, not a test author's.
const CATEGORY_COVERAGE: &[(&str, Coverage, &[&str])] = &[
    (
        "adjudication_report",
        DefaultAllow(
            "no built-in rule; the surface's authorization is the NOT-SAME arbiter \
             identity check inside tool_witness_adjudication, not a category rule",
        ),
        &["server/handler.rs::tool_witness_adjudication"],
    ),
    (
        "command",
        DefaultAllow(
            "classifier-only; the safety preset governs shell via tools:[\"Bash\"] + \
             command/target patterns, so a categories:[\"command\"] rule would be the \
             thing that is silently dead, not the shell",
        ),
        &["policy/extract.rs::classify"],
    ),
    (
        "credential_access",
        Ruled,
        &[
            "policy/extract.rs::classify",
            "server/handler.rs::tool_inbox",
            "server/handler.rs::tool_notify",
            "server/handler.rs::tool_pair_inbox",
            "server/handler.rs::tool_vault_get",
            "server/handler.rs::tool_vault_set",
        ],
    ),
    ("file_read", Ruled, &["policy/extract.rs::classify"]),
    ("file_write", Ruled, &["policy/extract.rs::classify"]),
    (
        "member_notify",
        DefaultAllow(
            "deliberate and pre-existing: bounded by the daemon's member_notify_limiter \
             (server/state.rs, 2026-07-24 Finding 2) rather than by law — plumbing \
             against runaway wake volume, explicitly not trust law",
        ),
        &[
            "server/handler.rs::tool_member_inbox",
            "server/handler.rs::tool_member_notify",
            "server/handler.rs::tool_member_unanswered",
        ],
    ),
    (
        "mesh_egress",
        DefaultAllow("no built-in rule; outward mesh sends are ungoverned by category"),
        &["server/handler.rs::tool_egress_pending"],
    ),
    ("network", Ruled, &["policy/extract.rs::classify"]),
    (
        "reversal_report",
        DefaultAllow("no built-in rule; reversal reports are ungoverned by category"),
        &["server/handler.rs::tool_record_reversal"],
    ),
    (
        "task_management",
        DefaultAllow("classifier-only; TodoWrite is not a consequential act"),
        &["policy/extract.rs::classify"],
    ),
    (
        "unknown",
        DefaultAllow(
            "the classifier's fallback for unrecognised tools. A rule naming it would \
             be a catch-all whose membership shifts every time a tool is added — the \
             wrong shape for law; govern by tools: instead",
        ),
        &["policy/extract.rs::classify"],
    ),
    (
        "witness_append",
        DefaultAllow(
            "NOT deliberate — the capability was built to be gateable (see the \
             classifier arm's own comment) and no rule was ever shipped. Recorded as \
             default-allow so it stops being invisible; the fix is a law change, \
             tracked separately, and this line must be revisited when it lands",
        ),
        &[
            "policy/extract.rs::classify",
            "server/handler.rs::tool_request_witness",
        ],
    ),
];

/// Strip `//`-comments, respecting string literals, so a category named in
/// prose can never satisfy the enumeration. (`member_presence_census` learned
/// the item-position version of this lesson twice in one week; here the
/// cheaper total form is available because we parse expressions, not items.)
fn strip_line_comments(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for line in text.lines() {
        let bytes = line.as_bytes();
        let mut in_str = false;
        let mut cut = line.len();
        let mut i = 0;
        while i < bytes.len() {
            match bytes[i] {
                b'\\' if in_str => i += 1,
                b'"' => in_str = !in_str,
                b'/' if !in_str && i + 1 < bytes.len() && bytes[i + 1] == b'/' => {
                    cut = i;
                    break;
                }
                _ => {}
            }
            i += 1;
        }
        out.push_str(&line[..cut]);
        out.push('\n');
    }
    out
}

/// String literals in `text`, in order, with escapes honoured.
fn string_literals(text: &str) -> Vec<String> {
    let bytes = text.as_bytes();
    let mut lits = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'"' {
            let start = i + 1;
            let mut j = start;
            while j < bytes.len() && bytes[j] != b'"' {
                if bytes[j] == b'\\' {
                    j += 1;
                }
                j += 1;
            }
            if j >= bytes.len() {
                break;
            }
            lits.push(text[start..j].to_string());
            i = j + 1;
        } else {
            i += 1;
        }
    }
    lits
}

/// The name defined by a `fn` item on this line, if any — `fn` in item
/// position, after visibility/modifier prefixes.
fn fn_item_name(line: &str) -> Option<String> {
    const PREFIXES: &[&str] = &["pub(crate) ", "pub ", "async ", "const ", "unsafe "];
    let mut t = line.trim_start();
    loop {
        match PREFIXES.iter().find_map(|p| t.strip_prefix(p)) {
            Some(rest) => t = rest,
            None => break,
        }
    }
    let name: String = t
        .strip_prefix("fn ")?
        .chars()
        .take_while(|c| c.is_alphanumeric() || *c == '_')
        .collect();
    (!name.is_empty()).then_some(name)
}

/// Text of the balanced-paren argument list starting at `open` (the index of
/// `(`), string-literal aware so a paren inside a literal cannot close it.
fn balanced_args(text: &str, open: usize) -> Option<&str> {
    let bytes = text.as_bytes();
    let mut depth = 0i32;
    let mut in_str = false;
    let mut i = open;
    while i < bytes.len() {
        match bytes[i] {
            b'\\' if in_str => i += 1,
            b'"' => in_str = !in_str,
            b'(' if !in_str => depth += 1,
            b')' if !in_str => {
                depth -= 1;
                if depth == 0 {
                    return Some(&text[open + 1..i]);
                }
            }
            _ => {}
        }
        i += 1;
    }
    None
}

/// Producer 1: every `gate_direct_tool(...)` call site, as
/// `category -> "file::fn"`.
fn gate_call_site_categories() -> BTreeMap<String, BTreeSet<String>> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/server/handler.rs");
    let raw = fs::read_to_string(&path).expect("read handler.rs");
    let text = strip_line_comments(&raw);

    // Enclosing-fn index by byte offset.
    let mut fn_at: Vec<(usize, String)> = Vec::new();
    let mut off = 0usize;
    for line in text.split_inclusive('\n') {
        if let Some(name) = fn_item_name(line) {
            fn_at.push((off, name));
        }
        off += line.len();
    }

    let mut out: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let needle = "gate_direct_tool(";
    let mut from = 0usize;
    while let Some(rel) = text[from..].find(needle) {
        let at = from + rel;
        from = at + needle.len();
        // The definition itself is not a call site.
        if text[..at].ends_with("fn ") {
            continue;
        }
        let open = at + needle.len() - 1;
        let Some(args) = balanced_args(&text, open) else {
            continue;
        };
        let lits = string_literals(args);
        // (s, who, tool_name, category, target): tool_name then category.
        let Some(category) = lits.get(1) else {
            panic!("gate_direct_tool call at byte {at} has fewer than two string literals — \
                    the argument shape this test assumes has changed; re-read the signature");
        };
        let enclosing = fn_at
            .iter()
            .rev()
            .find(|(o, _)| *o <= at)
            .map(|(_, n)| n.clone())
            .unwrap_or_else(|| "(top-level)".into());
        out.entry(category.clone())
            .or_default()
            .insert(format!("server/handler.rs::{enclosing}"));
    }
    out
}

/// Producer 2: every category `policy::extract::classify` can return, read
/// from its match arms — the first string literal after each `=>`.
fn classifier_categories() -> BTreeSet<String> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/policy/extract.rs");
    let raw = fs::read_to_string(&path).expect("read extract.rs");
    let text = strip_line_comments(&raw);

    let start = text
        .find("pub fn classify(")
        .expect("classify is defined in extract.rs");
    let body_open = text[start..].find('{').expect("classify has a body") + start;
    let body = balanced_braces(&text, body_open).expect("classify body is balanced");

    let mut out = BTreeSet::new();
    for arm in body.split("=>").skip(1) {
        if let Some(first) = string_literals(arm).into_iter().next() {
            out.insert(first);
        }
    }
    assert!(
        !out.is_empty(),
        "classify's arms parsed to zero categories — the match shape changed"
    );
    out
}

/// Balanced-brace body starting at `open` (index of `{`), string-aware.
fn balanced_braces(text: &str, open: usize) -> Option<&str> {
    let bytes = text.as_bytes();
    let mut depth = 0i32;
    let mut in_str = false;
    let mut i = open;
    while i < bytes.len() {
        match bytes[i] {
            b'\\' if in_str => i += 1,
            b'"' => in_str = !in_str,
            b'{' if !in_str => depth += 1,
            b'}' if !in_str => {
                depth -= 1;
                if depth == 0 {
                    return Some(&text[open + 1..i]);
                }
            }
            _ => {}
        }
        i += 1;
    }
    None
}

/// Categories named by any rule in any built-in preset.
fn categories_with_a_builtin_rule() -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    for preset in hestia::policy::presets::list_presets() {
        for rule in &preset.config.rules {
            if let Some(cats) = &rule.r#match.categories {
                out.extend(cats.iter().cloned());
            }
        }
    }
    out
}

/// The declared table as `category -> sites`.
fn declared_sites() -> BTreeMap<String, BTreeSet<String>> {
    CATEGORY_COVERAGE
        .iter()
        .map(|(cat, _, sites)| {
            (
                (*cat).to_string(),
                sites.iter().map(|s| (*s).to_string()).collect(),
            )
        })
        .collect()
}

/// Every category minted by either producer, with its sites.
fn minted_sites() -> BTreeMap<String, BTreeSet<String>> {
    let mut found = gate_call_site_categories();
    for cat in classifier_categories() {
        found
            .entry(cat)
            .or_default()
            .insert("policy/extract.rs::classify".into());
    }
    found
}

#[test]
fn minted_category_producers_are_enumerated() {
    let found = minted_sites();
    let declared = declared_sites();
    assert_eq!(
        found, declared,
        "\n\nCOVERAGE RED — the set of policy categories the code mints changed.\n\
         Before editing CATEGORY_COVERAGE, answer for the delta: should law be\n\
         able to DENY this act? If yes, ship a rule naming the category. If no,\n\
         declare DefaultAllow with the reason — an undeclared category is a gate\n\
         that reads as installed and admits everything.\n\
         found:    {found:#?}\n\
         declared: {declared:#?}\n"
    );
}

#[test]
fn ruled_categories_have_a_shipped_rule() {
    let ruled_in_presets = categories_with_a_builtin_rule();
    let missing: Vec<&str> = CATEGORY_COVERAGE
        .iter()
        .filter(|(cat, cov, _)| *cov == Ruled && !ruled_in_presets.contains(*cat))
        .map(|(cat, _, _)| *cat)
        .collect();
    assert!(
        missing.is_empty(),
        "\n\nCOVERAGE RED — declared Ruled, but no built-in preset rule names it:\n\
         {missing:?}\n\
         Either the rule was removed (the gate is now silently default-allow and\n\
         the declaration is a lie), or it moved to an overlay this test cannot\n\
         see (then say so and reclassify).\n"
    );
}

#[test]
fn default_allow_categories_still_have_no_shipped_rule() {
    let ruled_in_presets = categories_with_a_builtin_rule();
    let now_ruled: Vec<&str> = CATEGORY_COVERAGE
        .iter()
        .filter(|(cat, cov, _)| matches!(cov, DefaultAllow(_)) && ruled_in_presets.contains(*cat))
        .map(|(cat, _, _)| *cat)
        .collect();
    assert!(
        now_ruled.is_empty(),
        "\n\nCOVERAGE RED — declared DefaultAllow, but a built-in rule now names it:\n\
         {now_ruled:?}\n\
         Good news, probably — but the declaration is stale. Reclassify as Ruled\n\
         and, for witness_append specifically, revisit its recorded reason: it\n\
         says the fix is pending.\n"
    );
}

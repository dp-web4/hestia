//! `hestia mesh` — the member-mesh CLI, carried inside this binary (#1503).
//!
//! WHY THIS COMMAND EXISTS. The SessionStart hook every mesh member gets (#1373) told it to drain and
//! ack with `python3 $HESTIA_HOME/deploy/…/hestia-mesh.py` and to "act per KINDS.md". That install dir
//! is under `$HESTIA_HOME`, which no member grant reaches (the vault lives there), so every act the
//! hook instructed was refused and opened an operator scope request — dp, 2026-11-07: *"the mesh stuff
//! is needing a bunch of grants … it's a friction"*.
//!
//! WHY EMBEDDED, NOT LINKED. The first cut (#1504 v1) linked `~/.local/bin/hestia-mesh` to the
//! installed script. Nova's HOLD: a bare word on PATH binds no executable — the gate admits whatever
//! that word resolves to when the member runs it. Here the code that runs is the bytes compiled into
//! this release: `hestia-mesh.py` and `KINDS.md` are `include_str!`ed from `plugins/member-mesh`, so the
//! mesh CLI a member runs is the one this binary's version names, not a file anyone can swap later.
//! ONE SOURCE: the Python file stays the implementation (its resend guard, drain copy, operation-id
//! retry and exit-code contract are not re-implemented here), and `embedded_cli_is_the_plugin_file`
//! fails the build's tests if the two ever differ.
//!
//! WHAT THIS IS NOT. It adds no authority. Every act still goes to the daemon's member tools
//! (`hestia_member_inbox`, `hestia_member_notify`, `hestia_member_unanswered`) under the identity the
//! caller states in `HESTIA_MESH_PLUGIN` — a claim, as everywhere on `hestia_connect` (#63, #128). The
//! embedded CLI keeps its fail-closed identity guard.
//!
//! `kinds` is answered here, natively: it reads no file and opens no session.
//! Everything else runs the embedded CLI as `python3 -c <source> <args…>`, inheriting stdio, the
//! environment and the exit code (0 ok · 1 never got there · 2 usage/identity · 3 declined ·
//! 4 undetermined · 5 refused locally).

use std::process::Command;

/// The mesh CLI, byte for byte as `plugins/member-mesh/hestia-mesh.py` at build time.
pub const EMBEDDED_CLI: &str = include_str!("../../plugins/member-mesh/hestia-mesh.py");
/// The notice-kind semantics the wake hook tells a member to act by.
pub const EMBEDDED_KINDS: &str = include_str!("../../plugins/member-mesh/KINDS.md");

/// `kinds [term]`: the whole of KINDS.md, or only the `#`-headed sections that mention `term`
/// (case-insensitive). `None` when a term matches nothing — said aloud by the caller, never an empty
/// success.
pub fn kinds(term: &str) -> Option<String> {
    let term = term.trim().to_lowercase();
    if term.is_empty() {
        return Some(EMBEDDED_KINDS.to_string());
    }
    let mut sections: Vec<String> = Vec::new();
    let mut cur = String::new();
    for line in EMBEDDED_KINDS.split_inclusive('\n') {
        if line.starts_with('#') && !cur.is_empty() {
            sections.push(std::mem::take(&mut cur));
        }
        cur.push_str(line);
    }
    if !cur.is_empty() {
        sections.push(cur);
    }
    let hits: Vec<String> = sections
        .into_iter()
        .filter(|s| s.to_lowercase().contains(&term))
        .map(|s| format!("{}\n", s.trim_end_matches('\n')))
        .collect();
    if hits.is_empty() { None } else { Some(hits.join("\n")) }
}

/// Run `hestia mesh <args…>`. Returns the process exit code to use (the embedded CLI's own).
pub fn run(args: &[String]) -> i32 {
    if args.first().map(String::as_str) == Some("kinds") {
        let term = args[1..].join(" ");
        return match kinds(&term) {
            Some(text) => {
                print!("{text}");
                0
            }
            None => {
                eprintln!("hestia mesh: no KINDS.md section mentions {:?}", term.trim().to_lowercase());
                1
            }
        };
    }
    let python = std::env::var("HESTIA_MESH_PYTHON").unwrap_or_else(|_| "python3".to_string());
    match Command::new(&python)
        .arg("-c")
        .arg(EMBEDDED_CLI)
        .args(args)
        // The embedded CLI names itself in its refusals; under `-c` its argv[0] is "-c".
        .env("HESTIA_MESH_PROG", "hestia mesh")
        .status()
    {
        Ok(status) => match status.code() {
            Some(c) => c,
            None => {
                eprintln!("hestia mesh: the mesh CLI was killed by a signal");
                1
            }
        },
        Err(e) => {
            // rc=1 is the CLI's own "I never got there".
            eprintln!("hestia mesh: cannot run {python}: {e}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_cli_is_the_plugin_file() {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../plugins/member-mesh/hestia-mesh.py");
        assert_eq!(std::fs::read_to_string(path).unwrap(), EMBEDDED_CLI);
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../plugins/member-mesh/KINDS.md");
        assert_eq!(std::fs::read_to_string(path).unwrap(), EMBEDDED_KINDS);
    }

    #[test]
    fn kinds_without_a_term_is_the_whole_file() {
        assert_eq!(kinds("").as_deref(), Some(EMBEDDED_KINDS));
        assert_eq!(kinds("   ").as_deref(), Some(EMBEDDED_KINDS));
    }

    #[test]
    fn kinds_with_a_term_is_only_the_sections_naming_it() {
        let out = kinds("one row per RULING").expect("a section names it");
        assert!(out.contains("a disposition is one row per RULING"));
        assert!(!out.contains("Local member-mesh notice kinds"), "the first section does not name it");
    }

    #[test]
    fn an_unmatched_term_is_none_not_empty() {
        assert_eq!(kinds("zz-no-such-term-zz"), None);
    }
}

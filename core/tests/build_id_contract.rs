//! Guards the deployment-freshness recipe (docs/DASHBOARD.md, #231): the
//! supervisor's manifest `build_id` must be the exact `git describe` string
//! the deployed binary reports in `hestia --version`. The contract is sound
//! by construction — `cli.rs`'s VERSION and the dashboard's `running_build`
//! both read the one `env!("HESTIA_GIT_VERSION")` — but nothing asserted it:
//! the `--version` rendering lives in `cli.rs`, which `cargo test --lib`
//! never runs (kimi review residual on #231, carried in hestia#231's
//! post-merge thread). These tests run the actual binary and read the actual
//! doc, so the recipe breaks loudly instead of permanently-amber quietly.

use std::process::Command;

/// The parenthesized substring of `hestia --version` IS the dashboard's
/// `running_build`. If either side drifts — a VERSION format change in
/// `cli.rs`, a different env source in `dashboard.rs` — a manifest written
/// per the recipe can never read `current`, and every deployment reports
/// `stale` forever.
#[test]
fn version_parenthesized_substring_is_the_dashboard_running_build() {
    let output = Command::new(env!("CARGO_BIN_EXE_hestia"))
        .arg("--version")
        .output()
        .expect("hestia --version must run");
    assert!(output.status.success(), "hestia --version failed: {output:?}");
    let stdout = String::from_utf8(output.stdout).expect("version output is utf-8");
    let running_build = env!("HESTIA_GIT_VERSION");
    assert!(
        stdout.contains(&format!("({running_build})")),
        "`hestia --version` must print the exact build id in parentheses — \
         that substring is what the supervisor copies into the manifest. \
         got {stdout:?}, expected to contain ({running_build})"
    );
}

/// The documented recipe must keep naming the binary's self-report as the
/// authority, and its example must not regress to a bare `g<hash>`. The
/// original defect was exactly that example (`g8c44e7a`): a format
/// `git describe --tags --always --dirty` can never emit, so a supervisor
/// following the doc produced a manifest that could never match — the
/// permanently-amber failure this file exists to keep loud.
///
/// Scope, stated so the guard is not over-trusted: the bare-`g<hash>`
/// assertions below guard the *known landmine*, not the value's format
/// generally — a regression to some other non-`git describe` string
/// (`v0.1.2`, `607-ge720d0a`) still passes, and narrowing that is deliberate
/// (claude-code review of #239, note 1). Two passes: a structured scan of
/// every readable `"build_id"` example, and a whole-doc scan for a bare
/// `g<hex>` token, because the structured scan can only check spellings it
/// can parse (claude-code re-measure of the arm-C fix, arm G).
#[test]
fn dashboard_doc_recipe_points_at_version_self_report() {
    let doc = include_str!("../../docs/DASHBOARD.md");
    assert!(
        doc.contains("hestia --version"),
        "DASHBOARD.md must name `hestia --version` as the build_id authority"
    );
    // Scan every `build_id` example, tolerating whitespace around the colon:
    // the literal needle `"build_id":"` matched the doc's spelling of the day
    // only, so a JSON reformat (one space after the colon) dropped this loop
    // to zero iterations and the test passed with the original `g8c44e7a`
    // landmine restored — measured, claude-code review of #239, arm C.
    let mut examples = 0usize;
    for (i, _) in doc.match_indices("\"build_id\"") {
        let rest = &doc[i + "\"build_id\"".len()..];
        let rest = rest.trim_start();
        let Some(rest) = rest.strip_prefix(':') else { continue };
        let rest = rest.trim_start();
        let Some(rest) = rest.strip_prefix('"') else { continue };
        let Some(end) = rest.find('"') else { continue };
        let value = &rest[..end];
        examples += 1;
        let bare_g_hash = value.len() > 1
            && value.starts_with('g')
            && value[1..].chars().all(|c| c.is_ascii_hexdigit());
        assert!(
            !bare_g_hash,
            "DASHBOARD.md example regressed to a bare g<hash> ({value:?}) — a format \
             `git describe` never emits, so the recipe cannot produce it"
        );
    }
    // Without this, a doc that stops showing a readable build_id example at
    // all reports the same green as a doc that passed on the merits.
    assert!(
        examples > 0,
        "DASHBOARD.md must carry at least one `build_id` example for this guard to check; \
         found none, so the bare-g<hash> assertion above never ran"
    );
    // But examples>0 proves the scanner read AT LEAST ONE example, not ALL
    // of them: a landmine in a spelling the loop above cannot parse (single
    // quotes, YAML, an unquoted value) sat green beside one readable good
    // example — arm G, claude-code re-measure of the arm-C fix. The
    // landmine's own signature is spelling-independent, so close the hole
    // where the value actually lives: scan the WHOLE doc for a bare
    // `g<hex>` token — a string `git describe --tags --always --dirty`
    // never emits on its own (its hash always rides a `<tag>-<n>-` prefix,
    // which is why the left boundary below excludes '-', sparing the
    // `-ge720d0a` inside a real describe string). However the example is
    // spelled, the value itself cannot hide.
    let bytes = doc.as_bytes();
    for i in 0..bytes.len() {
        if bytes[i] != b'g' {
            continue;
        }
        if i > 0 && (bytes[i - 1].is_ascii_alphanumeric() || bytes[i - 1] == b'-') {
            continue; // hash inside a real describe string, or an ordinary word
        }
        let hex_run = bytes[i + 1..]
            .iter()
            .take_while(|b| b.is_ascii_hexdigit())
            .count();
        assert!(
            hex_run < 7,
            "DASHBOARD.md carries a bare g<hash> token (`{}…`) — a format \
             `git describe` never emits on its own, so a supervisor copying \
             it produces a manifest that can never match",
            // Char-safe: a byte cut at i+12 can land mid-codepoint and panic
            // while formatting THIS message, burying the report the assert
            // exists to make loud (claude-code review of #239, item 3).
            doc[i..].chars().take(12).collect::<String>()
        );
    }
}

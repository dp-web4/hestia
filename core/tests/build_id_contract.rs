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
#[test]
fn dashboard_doc_recipe_points_at_version_self_report() {
    let doc = include_str!("../../docs/DASHBOARD.md");
    assert!(
        doc.contains("hestia --version"),
        "DASHBOARD.md must name `hestia --version` as the build_id authority"
    );
    let needle = "\"build_id\":\"";
    for (i, _) in doc.match_indices(needle) {
        let rest = &doc[i + needle.len()..];
        let value = &rest[..rest.find('"').expect("build_id example must terminate")];
        let bare_g_hash = value.len() > 1
            && value.starts_with('g')
            && value[1..].chars().all(|c| c.is_ascii_hexdigit());
        assert!(
            !bare_g_hash,
            "DASHBOARD.md example regressed to a bare g<hash> ({value:?}) — a format \
             `git describe` never emits, so the recipe cannot produce it"
        );
    }
}

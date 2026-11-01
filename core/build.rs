//! Bake the actual build provenance (`git describe`) into the binary so
//! `hestia --version` reports the commit it was built from, not a hand-bumped
//! Cargo.toml constant that goes stale the moment nobody remembers to edit it.
//!
//! ONLY RELEASE TAGS NAME A BUILD (web4#904). `--match 'v[0-9]*'` keeps every other tag out of
//! the build id: the Android `app-v*` tags are ancestors of main, and on 2026-08-08 the reference
//! daemon really did call itself `app-v0.1.2-761-g9a6a5c2`. Every producer and consumer of these
//! strings uses the same glob: deploy/from-main/hestia-deploy.sh (`BUILD_TAG_MATCH`),
//! deploy/install-members.sh, plugins/member-mesh/hestia-watch-member.sh and
//! tools/upgrade_path_test.py (`BUILD_TAG_MATCH`); tools/build_tag_match_test.py holds them to it.

use std::process::Command;

fn main() {
    let git = Command::new("git")
        .args(["describe", "--tags", "--match", "v[0-9]*", "--always", "--dirty"])
        .output()
        .ok()
        .filter(|o| o.status.success())
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "unknown".to_string());

    println!("cargo:rustc-env=HESTIA_GIT_VERSION={git}");

    // Re-run when the checked-out commit moves so the string stays fresh.
    // (Paths are relative to this crate dir; absent in a source tarball, which
    // is fine — the build just keeps the last-computed value.)
    println!("cargo:rerun-if-changed=../.git/HEAD");
    println!("cargo:rerun-if-changed=../.git/refs");
}

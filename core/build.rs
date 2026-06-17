//! Bake the actual build provenance (`git describe`) into the binary so
//! `hestia --version` reports the commit it was built from, not a hand-bumped
//! Cargo.toml constant that goes stale the moment nobody remembers to edit it.

use std::process::Command;

fn main() {
    let git = Command::new("git")
        .args(["describe", "--tags", "--always", "--dirty"])
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

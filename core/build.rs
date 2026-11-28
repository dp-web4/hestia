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

    // hestia #342: Windows reserves 1 MiB for the main thread, Linux 8 MiB. The debug `hestia`
    // binary overflowed 1 MiB before printing anything (STATUS_STACK_OVERFLOW on `init` and
    // `--version`), and `serve` polls its whole server future on the main thread in `block_on`.
    // Give the binary the stack it has on Linux rather than shrinking every frame for one platform.
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        const STACK: u32 = 8 * 1024 * 1024;
        match std::env::var("CARGO_CFG_TARGET_ENV").as_deref() {
            Ok("msvc") => println!("cargo:rustc-link-arg-bin=hestia=/STACK:{STACK}"),
            _ => println!("cargo:rustc-link-arg-bin=hestia=-Wl,--stack,{STACK}"),
        }
    }

    // Re-run when the checked-out commit moves so the string stays fresh.
    // (Paths are relative to this crate dir; absent in a source tarball, which
    // is fine — the build just keeps the last-computed value.)
    println!("cargo:rerun-if-changed=../.git/HEAD");
    println!("cargo:rerun-if-changed=../.git/refs");
}

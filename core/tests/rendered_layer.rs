//! The rendered layer, wired into cargo: the store-layer suite stops one boundary
//! early, and the report path's failure mode has twice lived past that boundary
//! (PR #62's acceptance test asserted at `drain_member`; the wall was in the fire
//! templates). The rendered-layer assertion already exists — checks B4/B4b/B5/B5b of
//! `plugins/member-mesh/tests/fire_sender_allowlist_test.py`, which runs the real
//! templates — but it was Python on the far side of a language seam, invoked by a
//! prose instruction in a Rust tripwire message. A check that runs only when a human
//! remembers the instruction is the W-item failure shape wearing a test's coat.
//!
//! This target closes the seam: `cargo test` now executes the Python suite against the
//! real templates and goes red if it fails. Skip semantics are deliberate and match
//! the thread's own rule (a permanently-red suite trains operators to rerun past red):
//! a checkout without `python3`, or without the plugin tree, SKIPS with a note on
//! stderr rather than failing — the test binds exactly where the checked artifact
//! exists, and claims nothing where it does not.

use std::path::PathBuf;
use std::process::Command;

#[test]
fn fire_templates_render_the_report_path_into_the_prompt() {
    let script = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../plugins/member-mesh/tests/fire_sender_allowlist_test.py");
    if !script.is_file() {
        eprintln!("SKIP: {} not present in this checkout", script.display());
        return;
    }
    let out = match Command::new("python3").arg(&script).output() {
        Ok(out) => out,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            eprintln!("SKIP: python3 not found; rendered-layer suite not run");
            return;
        }
        Err(e) => panic!("could not spawn python3: {e}"),
    };
    assert!(
        out.status.success(),
        "rendered-layer suite failed — a store-layer green says the row was written, \
         never that a member was woken by it:\n{}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr),
    );
}

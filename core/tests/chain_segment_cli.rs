use std::path::PathBuf;
use std::process::Command;

fn run_smoke(fixtures: PathBuf, write: bool) {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let mut cmd = Command::new("python3");
    cmd.arg(root.join("tools/chain_segment_smoke.py"))
        .arg("--binary")
        .arg(env!("CARGO_BIN_EXE_hestia"))
        .arg("--fixtures-dir")
        .arg(fixtures);
    if write {
        cmd.arg("--write");
    }
    let out = cmd.output().unwrap();
    assert!(
        out.status.success(),
        "chain segment smoke failed\nstdout: {}\nstderr: {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn a_real_daemon_produces_an_offline_verifiable_segment() {
    let scratch = tempfile::tempdir().unwrap();
    let fixtures = std::env::var_os("HESTIA_CHAIN_SEGMENT_WRITE_FIXTURES")
        .map(PathBuf::from)
        .unwrap_or_else(|| scratch.path().join("fixtures"));
    run_smoke(fixtures, true);
}

#[test]
fn shipped_segment_fixtures_match_the_cli_contract() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    run_smoke(root.join("fixtures/chain-segment"), false);
}

//! `$HESTIA_HOME/.passphrase` is read by the daemon's `serve` path ONLY (#581,
//! hestia#1587 CBP/NOVA hold). The file exists on every installed seat, so if the
//! shared CLI prompt read it, any same-UID caller with no env and no TTY could run
//! `hestia vault get` and have the binary read the guarded file on its behalf.
//! These tests run the real binary against a throwaway vault: CLI commands must
//! still stop at the human-presence prompt, and `serve` must still unlock.

use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Child, Command, Output, Stdio};
use std::time::{Duration, Instant};

const PASSPHRASE: &str = "throwaway-1587-passphrase";
const SECRET: &str = "throwaway-1587-secret-value";

/// A child with no `HESTIA_PASSPHRASE`, stdin `/dev/null`, and HOME pinned to the
/// scratch dir so nothing outside it is read. Its own process group: on a developer
/// terminal a TTY read stops it (SIGTTIN) rather than prompting, and `run` kills it.
fn hestia(home: &Path) -> Command {
    use std::os::unix::process::CommandExt;
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_hestia"));
    cmd.arg("--home")
        .arg(home)
        .env_remove("HESTIA_PASSPHRASE")
        .env_remove("HESTIA_SECRET")
        .env("HOME", home.parent().unwrap())
        .env("HESTIA_HOME", home)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0);
    cmd
}

fn run(mut cmd: Command) -> Output {
    let mut child: Child = cmd.spawn().expect("spawn hestia");
    let deadline = Instant::now() + Duration::from_secs(30);
    while child.try_wait().unwrap().is_none() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    let _ = child.kill();
    child.wait_with_output().unwrap()
}

/// A scratch home holding an initialized vault with one entry and a `.passphrase`.
fn scratch_home() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path().join("h");
    let mut init = hestia(&home);
    init.arg("init").env("HESTIA_PASSPHRASE", PASSPHRASE);
    let out = run(init);
    assert!(out.status.success(), "init failed: {out:?}");
    let mut add = hestia(&home);
    add.args(["vault", "add", "probe1587"])
        .env("HESTIA_PASSPHRASE", PASSPHRASE)
        .env("HESTIA_SECRET", SECRET);
    let out = run(add);
    assert!(out.status.success(), "vault add failed: {out:?}");
    std::fs::write(home.join(".passphrase"), format!("{PASSPHRASE}\n")).unwrap();
    dir
}

#[test]
fn cli_commands_do_not_unlock_the_vault_from_the_passphrase_file() {
    let dir = scratch_home();
    let home = dir.path().join("h");

    // Control: the same command WITH the env passphrase unlocks, so a refusal
    // below is the missing credential, not a broken probe.
    let mut get = hestia(&home);
    get.args(["vault", "get", "probe1587"])
        .env("HESTIA_PASSPHRASE", PASSPHRASE);
    let out = run(get);
    assert!(
        String::from_utf8_lossy(&out.stdout).contains(SECRET),
        "control get: {out:?}"
    );

    for args in [
        &["vault", "list"][..],
        &["vault", "get", "probe1587"][..],
        &["vault", "remove", "probe1587"][..],
        &["policy", "set", "permissive"][..],
    ] {
        let mut cmd = hestia(&home);
        cmd.args(args);
        let out = run(cmd);
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !out.status.success() && !stdout.contains(SECRET) && !stdout.contains('✓'),
            "`hestia {}` unlocked the vault from .passphrase: {out:?}",
            args.join(" ")
        );
    }

    // The entry survived the refused remove.
    let mut get = hestia(&home);
    get.args(["vault", "get", "probe1587"])
        .env("HESTIA_PASSPHRASE", PASSPHRASE);
    let out = run(get);
    assert!(
        String::from_utf8_lossy(&out.stdout).contains(SECRET),
        "entry removed: {out:?}"
    );
}

#[test]
fn serve_unlocks_the_vault_from_the_passphrase_file() {
    let dir = scratch_home();
    let home = dir.path().join("h");
    let mut cmd = hestia(&home);
    cmd.args(["serve", "--bind", "127.0.0.1:0"]);
    let mut child = cmd.spawn().expect("spawn hestia serve");
    let stdout = child.stdout.take().unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if tx.send(line).is_err() {
                break;
            }
        }
    });
    let deadline = Instant::now() + Duration::from_secs(60);
    let mut unlocked = false;
    while let Ok(line) = rx.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
        if line.starts_with("Vault unlocked") {
            unlocked = true;
            break;
        }
    }
    let _ = child.kill();
    let out = child.wait_with_output().unwrap();
    assert!(unlocked, "serve did not unlock from .passphrase: {out:?}");
}

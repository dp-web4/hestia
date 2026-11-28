//! The real Windows binary must refuse an existing home with unsafe secret permissions before
//! unlocking, replacing a vault, or starting the server. A private parent alone does not revoke
//! explicit child ACEs or reach a child whose DACL is protected (hestia #342, #1742).
#![cfg(windows)]

use std::path::Path;
use std::process::{Child, Command, Output, Stdio};
use std::time::{Duration, Instant};

struct Daemon(Child);

impl Drop for Daemon {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn hestia(home: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_hestia"))
        .arg("--home")
        .arg(home)
        .args(args)
        // Deliberately present: a daemon must also reject a shared .passphrase when the
        // environment would otherwise bypass reading that file.
        .env("HESTIA_PASSPHRASE", "windows-permission-regression-only")
        .output()
        .unwrap()
}

fn icacls(path: &Path, args: &[&str]) -> Output {
    let out = Command::new("icacls").arg(path).args(args).output().unwrap();
    assert!(
        out.status.success(),
        "icacls {}: {} {}",
        path.display(),
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    out
}

fn existing_home() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    hestia::fsperm::restrict_dir(dir.path()).unwrap();
    // Intentionally invalid: the ACL preflight must fail BEFORE vault parsing or decryption.
    std::fs::write(dir.path().join("vault.enc"), b"vault bytes must remain unchanged").unwrap();
    dir
}

fn assert_refused(home: &Path, args: &[&str], offending: &Path, reason: &str) {
    let vault = home.join("vault.enc");
    let before = std::fs::read(&vault).unwrap();
    let out = hestia(home, args);
    let err = String::from_utf8_lossy(&out.stderr);
    assert!(!out.status.success(), "unsafe home was accepted: {args:?}");
    assert!(
        err.contains(reason) && err.contains(offending.to_string_lossy().as_ref()),
        "expected {reason:?} at {}, got: {err}",
        offending.display()
    );
    assert_eq!(std::fs::read(vault).unwrap(), before, "refusal must not replace the vault");
    assert!(!home.join("endpoint").exists(), "refusal must precede daemon startup");
    assert!(
        !String::from_utf8_lossy(&out.stdout).contains("Vault unlocked"),
        "refusal must precede vault unlock"
    );
}

#[test]
fn existing_explicit_secret_grants_are_refused_by_serve_and_cli() {
    for relative in ["vault.enc", "operator.key", ".passphrase", "router-memberships/member.key"] {
        let home = existing_home();
        // Match the native spelling returned by read_dir in the refusal diagnostic.
        let secret = relative.split('/').fold(home.path().to_path_buf(), |path, part| path.join(part));
        std::fs::create_dir_all(secret.parent().unwrap()).unwrap();
        if relative != "vault.enc" {
            std::fs::write(&secret, b"existing secret must remain unchanged").unwrap();
        }
        let before = std::fs::read(&secret).unwrap();
        icacls(&secret, &["/grant", "*S-1-1-0:R"]);
        assert!(hestia::fsperm::is_private(home.path()).unwrap(), "parent already private");
        assert!(!hestia::fsperm::is_private(&secret).unwrap(), "fixture has an explicit grant");

        assert_refused(home.path(), &["serve"], &secret, "not owner-only");
        assert_refused(home.path(), &["vault", "list"], &secret, "not owner-only");
        assert_eq!(std::fs::read(&secret).unwrap(), before);
    }
}

#[test]
fn a_protected_shared_child_directory_is_refused() {
    let home = existing_home();
    let keys = home.path().join("router-memberships");
    std::fs::create_dir(&keys).unwrap();
    // restrict_dir protects the child's DACL; its explicit Everyone grant cannot be removed
    // by applying the owner-only inheritable ACL to the parent home again.
    hestia::fsperm::restrict_dir(&keys).unwrap();
    icacls(&keys, &["/grant", "*S-1-1-0:(OI)(CI)R"]);
    let key = keys.join("member.key");
    std::fs::write(&key, b"channel seed").unwrap();
    assert!(!hestia::fsperm::is_private(&key).unwrap());

    assert_refused(home.path(), &["serve"], &keys, "not owner-only");
    assert_refused(home.path(), &["vault", "list"], &keys, "not owner-only");
    assert_eq!(std::fs::read(&key).unwrap(), b"channel seed");
}

#[test]
fn force_init_refuses_before_replacing_an_existing_vault() {
    let home = existing_home();
    let key = home.path().join("operator.key");
    std::fs::write(&key, b"existing operator seed").unwrap();
    icacls(&key, &["/grant", "*S-1-1-0:R"]);

    assert_refused(home.path(), &["init", "--force", "--ai"], &key, "not owner-only");
    assert_eq!(std::fs::read(&key).unwrap(), b"existing operator seed");
}

#[test]
fn a_junction_is_refused_without_changing_its_target() {
    let home = existing_home();
    let outside = tempfile::tempdir().unwrap();
    let secret = outside.path().join("outside.key");
    std::fs::write(&secret, b"unrelated secret").unwrap();
    icacls(outside.path(), &["/grant", "*S-1-1-0:(OI)(CI)R"]);
    let dir_acl = icacls(outside.path(), &[]).stdout;
    let file_acl = icacls(&secret, &[]).stdout;
    let link = home.path().join("router-memberships");
    // Junctions do not require the developer-mode / SeCreateSymbolicLinkPrivilege needed by
    // symlink_dir, so this exercises a real Windows reparse point on an ordinary CI account.
    let out = Command::new("cmd")
        .args(["/D", "/C", "mklink", "/J"])
        .arg(&link)
        .arg(outside.path())
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "mklink: {} {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );

    assert_refused(home.path(), &["serve"], &link, "reparse");
    assert_eq!(icacls(outside.path(), &[]).stdout, dir_acl, "target directory ACL unchanged");
    assert_eq!(icacls(&secret, &[]).stdout, file_acl, "target file ACL unchanged");
    assert_eq!(std::fs::read(&secret).unwrap(), b"unrelated secret");
    std::fs::remove_dir(&link).unwrap();
}

#[test]
fn a_private_home_initializes_opens_and_serves_with_a_private_operator_key() {
    let home = tempfile::tempdir().unwrap();
    let init = hestia(home.path(), &["init", "--ai"]);
    assert!(init.status.success(), "init: {}", String::from_utf8_lossy(&init.stderr));
    assert!(hestia::fsperm::is_private(home.path()).unwrap());
    assert!(hestia::fsperm::is_private(&home.path().join("vault.enc")).unwrap());
    let list = hestia(home.path(), &["vault", "list"]);
    assert!(list.status.success(), "vault list: {}", String::from_utf8_lossy(&list.stderr));

    let bind = {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        listener.local_addr().unwrap().to_string()
    };
    let log_path = home.path().join("serve-test.log");
    let log = std::fs::File::create(&log_path).unwrap();
    let mut daemon = Daemon(
        Command::new(env!("CARGO_BIN_EXE_hestia"))
            .arg("--home")
            .arg(home.path())
            .args(["serve", "--bind", &bind])
            .env("HESTIA_PASSPHRASE", "windows-permission-regression-only")
            .stdout(Stdio::from(log.try_clone().unwrap()))
            .stderr(Stdio::from(log))
            .spawn()
            .unwrap(),
    );
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(60);
    let mut ready = false;
    while Instant::now() < deadline {
        if let Some(status) = daemon.0.try_wait().unwrap() {
            panic!("serve exited {status}: {}", std::fs::read_to_string(&log_path).unwrap());
        }
        if let Ok(response) = client.get(format!("http://{bind}/api/version")).send() {
            if response.status().is_success() {
                let body: serde_json::Value = response.json().unwrap();
                assert!(body["version"].is_string(), "daemon version response: {body}");
                ready = true;
                break;
            }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(ready, "serve never became ready: {}", std::fs::read_to_string(&log_path).unwrap());
    // The listener is created after operator bootstrap. A warning-only bootstrap failure must
    // not satisfy this smoke: require the actual private credential, not just an open port.
    let key = home.path().join("operator.key");
    assert!(hestia::fsperm::is_private(&key).unwrap());
    let credential: serde_json::Value = serde_json::from_slice(&std::fs::read(&key).unwrap()).unwrap();
    assert_eq!(credential["secret_key_hex"].as_str().unwrap().len(), 64);
    assert!(hestia::fsperm::is_private(&home.path().join("vault.enc")).unwrap());
}

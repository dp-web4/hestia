//! Sprint A / A1 guard — the principal credential is encrypted at rest.
//!
//! Binds the migration outcome, not merely the presence of encryption-shaped code: the
//! encrypted vault must be reopenable, and a byte search of it must not recover either
//! representation of the seed.
//!
//! Custody policy, dp 2026-09-25: *"for now we can keep the key but should be resilient
//! to manual delete (do not re-project, use vault copy only)."* Until then these tests
//! asserted the plaintext was DELETED on import; they now assert the opposite — it is
//! kept byte-identical — and that once a vault exists the plaintext is never consulted:
//! changed, corrupt, or deleted, it cannot affect a sign-in, and nothing re-creates it.

use std::fs;

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier};
use hestia_app_lib::identity_vault::{migrate_plaintext_operator_key, open_or_import, IdentityVault};

const PRINCIPAL: &str = "lct:web4:human:test-principal";
const PASSPHRASE: &str = "correct horse battery staple";
const SEED: [u8; 32] = [0x5a; 32];

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn write_legacy_key(path: &std::path::Path) {
    write_legacy_seed(path, SEED);
}

fn write_legacy_seed(path: &std::path::Path, seed: [u8; 32]) {
    fs::write(
        path,
        serde_json::json!({
            "lct_id": PRINCIPAL,
            "secret_key_hex": hex(&seed),
        })
        .to_string(),
    )
    .unwrap();
}

/// The key a vault actually signs with, proved by a signature rather than by field
/// reads — the assertion that tells "the vault's credential" from "whatever the
/// plaintext says now".
fn signs_as(vault: &IdentityVault, seed: [u8; 32]) -> bool {
    let message = b"which key is this";
    let sig: [u8; 64] = hex::decode(vault.sign_hex(message).unwrap())
        .unwrap()
        .try_into()
        .unwrap();
    SigningKey::from_bytes(&seed)
        .verifying_key()
        .verify(message, &Signature::from_bytes(&sig))
        .is_ok()
}

#[test]
fn an_existing_vault_is_the_only_source_a_changed_plaintext_is_ignored() {
    let dir = tempfile::tempdir().unwrap();
    let legacy = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    write_legacy_key(&legacy);
    migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE).unwrap();

    // Someone replaces the plaintext with a different key. Under the old policy
    // this refused the sign-in; now the vault is the credential and the file is
    // not read.
    write_legacy_seed(&legacy, [0x6b; 32]);
    let changed = fs::read(&legacy).unwrap();
    let opened = open_or_import(&encrypted, Some(&legacy), PASSPHRASE).unwrap();
    assert!(signs_as(&opened, SEED), "signed with something other than the vault's key");
    assert!(!signs_as(&opened, [0x6b; 32]), "the replaced plaintext became the credential");
    assert_eq!(fs::read(&legacy).unwrap(), changed, "the plaintext was touched");
}

#[test]
fn a_corrupt_plaintext_cannot_veto_a_sign_in() {
    let dir = tempfile::tempdir().unwrap();
    let legacy = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    write_legacy_key(&legacy);
    migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE).unwrap();

    fs::write(&legacy, b"not json at all").unwrap();
    let opened = open_or_import(&encrypted, Some(&legacy), PASSPHRASE)
        .expect("a corrupt plaintext blocked a sign-in it has no part in");
    assert!(signs_as(&opened, SEED));
}

#[test]
fn deleting_the_plaintext_by_hand_changes_nothing_and_nothing_recreates_it() {
    let dir = tempfile::tempdir().unwrap();
    let legacy = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    write_legacy_key(&legacy);
    migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE).unwrap();

    fs::remove_file(&legacy).unwrap();
    // Twice, via both entry points: neither may re-project the plaintext.
    let a = open_or_import(&encrypted, None, PASSPHRASE).unwrap();
    let b = migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE).unwrap();
    assert!(signs_as(&a, SEED) && signs_as(&b, SEED));
    assert!(!legacy.exists(), "the app re-created operator.key");
}

#[test]
fn no_vault_and_no_plaintext_is_a_clear_refusal() {
    let dir = tempfile::tempdir().unwrap();
    let encrypted = dir.path().join("identity.vault");
    // IdentityVault has no Debug on purpose (it holds a secret), so no unwrap_err.
    let err = match open_or_import(&encrypted, None, PASSPHRASE) {
        Ok(_) => panic!("opened a vault that does not exist"),
        Err(e) => e,
    };
    assert!(err.contains("no identity vault"), "{err}");
    assert!(!encrypted.exists());
}



#[test]
fn migration_keeps_the_plaintext_and_writes_a_reopenable_encrypted_credential() {
    let dir = tempfile::tempdir().unwrap();
    let legacy = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    write_legacy_key(&legacy);
    let before = fs::read(&legacy).unwrap();

    let opened = migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE)
        .expect("legacy credential should migrate");
    assert_eq!(opened.principal_lct(), PRINCIPAL);
    let harness_lct = opened.harness_lct().to_string();
    let device_lct = opened.device_lct().to_string();
    assert_ne!(harness_lct, PRINCIPAL);
    assert_ne!(device_lct, PRINCIPAL);
    assert_ne!(harness_lct, device_lct);
    assert!(
        encrypted.exists(),
        "encrypted identity vault was not written"
    );
    // Kept, byte-identical (dp, 2026-09-25): other views of this engine read it.
    assert_eq!(
        fs::read(&legacy).unwrap(),
        before,
        "migration changed or removed the plaintext operator key"
    );
    drop(opened);

    let raw = fs::read(&encrypted).unwrap();
    assert!(
        !raw.windows(SEED.len()).any(|window| window == SEED),
        "raw Ed25519 seed is recoverable by a byte search"
    );
    assert!(
        !String::from_utf8_lossy(&raw).contains(&hex(&SEED)),
        "hex Ed25519 seed is recoverable by a text search"
    );

    let reopened = IdentityVault::open(&encrypted, PASSPHRASE)
        .expect("encrypted vault should survive app restart");
    assert_eq!(reopened.principal_lct(), PRINCIPAL);
    assert_eq!(reopened.harness_lct(), harness_lct);
    assert_eq!(reopened.device_lct(), device_lct);

    let message = b"daemon challenge";
    let sig_bytes: [u8; 64] = hex::decode(reopened.sign_hex(message).unwrap())
        .unwrap()
        .try_into()
        .unwrap();
    let signature = Signature::from_bytes(&sig_bytes);
    let expected = SigningKey::from_bytes(&SEED);
    assert!(expected.verifying_key().verify(message, &signature).is_ok());
    assert_eq!(expected.sign(message), signature);
}

#[test]
fn wrong_passphrase_and_tampering_fail_closed() {
    let dir = tempfile::tempdir().unwrap();
    let legacy = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    write_legacy_key(&legacy);
    migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE).unwrap();

    assert!(IdentityVault::open(&encrypted, "wrong passphrase").is_err());

    let mut raw = fs::read(&encrypted).unwrap();
    let last = raw.len() - 1;
    raw[last] ^= 0x80;
    fs::write(&encrypted, raw).unwrap();
    assert!(
        IdentityVault::open(&encrypted, PASSPHRASE).is_err(),
        "tampered vault opened successfully"
    );
}

#[test]
fn failed_import_does_not_destroy_the_only_plaintext_copy() {
    let dir = tempfile::tempdir().unwrap();
    let legacy = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    fs::write(&legacy, r#"{"lct_id":"lct:test","secret_key_hex":"abcd"}"#).unwrap();

    assert!(migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE).is_err());
    assert!(
        legacy.exists(),
        "failed import destroyed the source credential"
    );
    assert!(
        !encrypted.exists(),
        "failed import left a vault-shaped artifact"
    );
}

#[cfg(unix)]
#[test]
fn identity_vault_is_owner_only() {
    use std::os::unix::fs::PermissionsExt;

    let dir = tempfile::tempdir().unwrap();
    let legacy = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    write_legacy_key(&legacy);
    migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE).unwrap();

    assert_eq!(
        fs::metadata(encrypted).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

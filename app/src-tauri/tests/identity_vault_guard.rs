//! Sprint A / A1 guard — the principal credential is encrypted at rest.
//!
//! This test is intentionally committed RED before the identity-vault implementation.
//! It binds the migration outcome, not merely the presence of encryption-shaped code:
//! the encrypted vault must be reopenable, the old plaintext file must be gone, and a
//! byte search of the storage directory must not recover either representation of the seed.

use std::fs;

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier};
use hestia_app_lib::identity_vault::{IdentityVault, migrate_plaintext_operator_key};

const PRINCIPAL: &str = "lct:web4:human:test-principal";
const PASSPHRASE: &str = "correct horse battery staple";
const SEED: [u8; 32] = [0x5a; 32];

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn write_legacy_key(path: &std::path::Path) {
    fs::write(
        path,
        serde_json::json!({
            "lct_id": PRINCIPAL,
            "secret_key_hex": hex(&SEED),
        })
        .to_string(),
    )
    .unwrap();
}

#[test]
fn migration_leaves_only_an_encrypted_reopenable_credential() {
    let dir = tempfile::tempdir().unwrap();
    let legacy = dir.path().join("operator.key");
    let encrypted = dir.path().join("identity.vault");
    write_legacy_key(&legacy);

    let opened = migrate_plaintext_operator_key(&legacy, &encrypted, PASSPHRASE)
        .expect("legacy credential should migrate");
    assert_eq!(opened.principal_lct(), PRINCIPAL);
    assert!(encrypted.exists(), "encrypted identity vault was not written");
    assert!(
        !legacy.exists(),
        "successful migration left the plaintext operator key behind"
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
    assert!(legacy.exists(), "failed import destroyed the source credential");
    assert!(!encrypted.exists(), "failed import left a vault-shaped artifact");
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

    assert_eq!(fs::metadata(encrypted).unwrap().permissions().mode() & 0o777, 0o600);
}

//! Vault crypto primitives.
//!
//! Format choices (per ADR-0005 cryptography section):
//! - Key derivation: **Argon2id** (m=64MB, t=3, p=4) — OWASP-recommended
//! - Symmetric: **ChaCha20-Poly1305** AEAD — fast, side-channel-resistant
//! - Random: OS CSPRNG via `rand::rngs::OsRng`
//!
//! The on-disk format is a self-contained struct with the salt + nonce +
//! ciphertext, so the file can be moved between machines and decrypted with
//! the user's passphrase.

use argon2::{
    Algorithm, Argon2, Params, Version,
    password_hash::{SaltString, rand_core::OsRng},
};
use chacha20poly1305::{
    ChaCha20Poly1305, Key, Nonce,
    aead::{Aead, KeyInit},
};
use rand::RngCore;
use zeroize::Zeroize;

use crate::error::{CoreError, Result};

/// Argon2id parameters. Increase the cost factors if performance permits.
/// m_cost in KiB; t_cost in iterations; p_cost in lanes.
const ARGON_M_COST_KIB: u32 = 64 * 1024; // 64 MB
const ARGON_T_COST: u32 = 3;
const ARGON_P_COST: u32 = 4;

/// 32-byte ChaCha20 key derived from the passphrase via Argon2id.
pub struct DerivedKey([u8; 32]);

impl DerivedKey {
    pub fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }
}

impl Drop for DerivedKey {
    fn drop(&mut self) {
        self.0.zeroize();
    }
}

/// Derive a 32-byte symmetric key from a passphrase + salt.
pub fn derive_key(passphrase: &str, salt: &[u8]) -> Result<DerivedKey> {
    let params = Params::new(ARGON_M_COST_KIB, ARGON_T_COST, ARGON_P_COST, Some(32))
        .map_err(|e| CoreError::KeyDerivation(e.to_string()))?;

    let argon = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);

    let mut key = [0u8; 32];
    argon
        .hash_password_into(passphrase.as_bytes(), salt, &mut key)
        .map_err(|e| CoreError::KeyDerivation(e.to_string()))?;

    Ok(DerivedKey(key))
}

/// Generate a 16-byte random salt for key derivation.
pub fn generate_salt() -> [u8; 16] {
    let mut salt = [0u8; 16];
    OsRng.fill_bytes(&mut salt);
    salt
}

/// Generate a 12-byte random nonce for ChaCha20-Poly1305.
pub fn generate_nonce() -> [u8; 12] {
    let mut nonce = [0u8; 12];
    OsRng.fill_bytes(&mut nonce);
    nonce
}

/// Generate a fresh SaltString (used for password-hash side, distinct from vault-key derivation salt).
#[allow(dead_code)]
pub fn salt_string() -> SaltString {
    SaltString::generate(&mut OsRng)
}

/// Encrypt plaintext with the derived key. Returns ciphertext (which includes the auth tag).
/// Caller supplies the nonce (must be unique per (key, plaintext) pair).
pub fn encrypt(key: &DerivedKey, nonce: &[u8; 12], plaintext: &[u8]) -> Result<Vec<u8>> {
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key.as_bytes()));
    cipher
        .encrypt(Nonce::from_slice(nonce), plaintext)
        .map_err(|e| CoreError::EncryptionFailed(e.to_string()))
}

/// Decrypt ciphertext with the derived key + nonce. Returns plaintext or DecryptionFailed.
pub fn decrypt(key: &DerivedKey, nonce: &[u8; 12], ciphertext: &[u8]) -> Result<Vec<u8>> {
    let cipher = ChaCha20Poly1305::new(Key::from_slice(key.as_bytes()));
    cipher
        .decrypt(Nonce::from_slice(nonce), ciphertext)
        .map_err(|_| CoreError::DecryptionFailed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn key_derivation_is_deterministic_given_passphrase_and_salt() {
        let salt = generate_salt();
        let k1 = derive_key("hunter2", &salt).unwrap();
        let k2 = derive_key("hunter2", &salt).unwrap();
        assert_eq!(k1.as_bytes(), k2.as_bytes());
    }

    #[test]
    fn key_derivation_differs_for_different_passphrases() {
        let salt = generate_salt();
        let k1 = derive_key("hunter2", &salt).unwrap();
        let k2 = derive_key("opensesame", &salt).unwrap();
        assert_ne!(k1.as_bytes(), k2.as_bytes());
    }

    #[test]
    fn key_derivation_differs_for_different_salts() {
        let s1 = generate_salt();
        let s2 = generate_salt();
        assert_ne!(s1, s2);
        let k1 = derive_key("hunter2", &s1).unwrap();
        let k2 = derive_key("hunter2", &s2).unwrap();
        assert_ne!(k1.as_bytes(), k2.as_bytes());
    }

    #[test]
    fn encrypt_decrypt_round_trip() {
        let salt = generate_salt();
        let nonce = generate_nonce();
        let key = derive_key("the-secret-passphrase", &salt).unwrap();
        let plaintext = b"my super-secret API token: sk-ant-blah-blah";

        let ciphertext = encrypt(&key, &nonce, plaintext).unwrap();
        assert_ne!(ciphertext.as_slice(), plaintext);

        let decrypted = decrypt(&key, &nonce, &ciphertext).unwrap();
        assert_eq!(decrypted.as_slice(), plaintext);
    }

    #[test]
    fn decrypt_fails_with_wrong_passphrase() {
        let salt = generate_salt();
        let nonce = generate_nonce();
        let key_a = derive_key("right-passphrase", &salt).unwrap();
        let key_b = derive_key("wrong-passphrase", &salt).unwrap();
        let plaintext = b"sensitive data";

        let ciphertext = encrypt(&key_a, &nonce, plaintext).unwrap();
        let result = decrypt(&key_b, &nonce, &ciphertext);
        assert!(matches!(result, Err(CoreError::DecryptionFailed)));
    }

    #[test]
    fn decrypt_fails_with_tampered_ciphertext() {
        let salt = generate_salt();
        let nonce = generate_nonce();
        let key = derive_key("passphrase", &salt).unwrap();
        let mut ciphertext = encrypt(&key, &nonce, b"data").unwrap();
        // Flip one byte
        ciphertext[0] ^= 0xff;
        let result = decrypt(&key, &nonce, &ciphertext);
        assert!(matches!(result, Err(CoreError::DecryptionFailed)));
    }

    #[test]
    fn decrypt_fails_with_wrong_nonce() {
        let salt = generate_salt();
        let nonce_a = generate_nonce();
        let nonce_b = generate_nonce();
        let key = derive_key("passphrase", &salt).unwrap();
        let ciphertext = encrypt(&key, &nonce_a, b"data").unwrap();
        let result = decrypt(&key, &nonce_b, &ciphertext);
        assert!(matches!(result, Err(CoreError::DecryptionFailed)));
    }
}

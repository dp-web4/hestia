//! Hardware-sealed encrypted storage.

use crate::Result;

/// A vault whose AEAD key is unsealed only on the originally-bound
/// hardware.
///
/// In consumer Hestia, vault encryption is driven by an Argon2id key
/// derived from a passphrase — anyone holding the file *and* the
/// passphrase can decrypt. A `SealedVault` implementation replaces
/// that derivation with an unwrap operation performed inside the
/// hardware anchor (TPM `Unseal`, YubiKey HMAC-derived key, etc.), so
/// the ciphertext cannot be decrypted on a different device even with
/// the user's full credentials.
///
/// The same anchor that backs [`TrustedKeyProvider`][crate::TrustedKeyProvider]
/// is typically the source of the unwrapping key.
pub trait SealedVault: Send + Sync {
    /// Seal `plaintext` into a ciphertext blob that can only be
    /// unsealed by this same anchor.
    fn seal(&self, plaintext: &[u8]) -> Result<Vec<u8>>;

    /// Unseal a previously-sealed blob. Returns
    /// [`Error::VerificationFailed`][crate::Error::VerificationFailed]
    /// if the ciphertext was produced by a different anchor or has
    /// been tampered with.
    fn unseal(&self, ciphertext: &[u8]) -> Result<Vec<u8>>;
}

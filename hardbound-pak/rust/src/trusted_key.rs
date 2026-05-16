//! Hardware-anchored key material.

use crate::Result;

/// A handle to key material that lives inside hardware.
///
/// The private key bytes never leave the bound device; implementations
/// MUST refuse any extraction primitive. Only the public key, an opaque
/// anchor identifier, signing, and verification are exposed.
///
/// Implementations are typically backed by:
///
/// - **TPM 2.0** with a non-migratable key under a sealing policy
/// - **YubiKey** PIV slot or PGP card
/// - **Secure Enclave** on Apple silicon
/// - **HSM** for datacenter deployments
///
/// The [`anchor_id`][Self::anchor_id] string is the stable identifier
/// the rest of the stack uses to reason about *which* hardware backed a
/// given signature. Recommended format: `tpm:sha256:<digest>` or
/// `yubikey:serial:<n>` or `se:keyid:<base64>`.
pub trait TrustedKeyProvider: Send + Sync {
    /// Stable identifier for this hardware-bound key. Survives
    /// reboots; changes only if the hardware is rebound.
    fn anchor_id(&self) -> &str;

    /// Public key bytes. Format is implementation-defined; recommend
    /// DER-encoded SubjectPublicKeyInfo for interoperability.
    fn public_key(&self) -> &[u8];

    /// Sign `message`. Returns the raw signature bytes (DER-encoded
    /// for ECDSA, or whatever the underlying scheme produces).
    fn sign(&self, message: &[u8]) -> Result<Vec<u8>>;

    /// Verify `signature` over `message` against this anchor's public
    /// key. Most callers will use this for self-checks; cross-anchor
    /// verification belongs at a higher layer.
    fn verify(&self, message: &[u8], signature: &[u8]) -> Result<bool>;
}

//! Hardware-attested signatures over witness chain entries.

use crate::Result;

/// One attested signature over a payload, signed by a
/// [`TrustedKeyProvider`][crate::TrustedKeyProvider] inside its
/// hardware anchor.
///
/// In the Hestia chain, each entry's `signer_lct` field today is a
/// software placeholder. With Hardbound, the daemon co-locates an
/// `Attestation` per chain entry; verifiers reconstruct the same
/// payload, then validate the signature against the public key
/// embedded in the anchor's [`TrustedKeyProvider::public_key`][crate::TrustedKeyProvider::public_key].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Attestation {
    /// Anchor that produced this signature.
    /// See [`TrustedKeyProvider::anchor_id`][crate::TrustedKeyProvider::anchor_id].
    pub anchor_id: String,

    /// Optional platform quote / firmware measurement bundle.
    /// For TPM: a `TPM2B_ATTEST` quote over the requested PCRs. For
    /// YubiKey: empty (the device itself is the attestation surface).
    pub quote: Vec<u8>,

    /// The signature bytes from [`TrustedKeyProvider::sign`][crate::TrustedKeyProvider::sign].
    pub signature: Vec<u8>,

    /// Unix epoch milliseconds at which the anchor produced this
    /// attestation. Verifiers cross-check this with the chain entry
    /// timestamp.
    pub timestamp_ms: i64,
}

/// Produces [`Attestation`]s over arbitrary payloads.
///
/// The split between this and [`TrustedKeyProvider`][crate::TrustedKeyProvider]
/// is deliberate: `TrustedKeyProvider` is a bare signer; an
/// `AttestationSigner` adds the platform-attestation envelope around
/// it (PCR quote for TPM, factory cert chain for YubiKey).
pub trait AttestationSigner: Send + Sync {
    /// Produce an attestation over `payload`. `nonce` is supplied by
    /// the caller to defeat replay; implementations MUST incorporate
    /// it into the signed bytes.
    fn sign_attestation(&self, payload: &[u8], nonce: &[u8]) -> Result<Attestation>;
}

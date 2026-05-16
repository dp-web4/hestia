//! Common error types for Hardbound implementations.

/// Result alias used across the contract.
pub type Result<T> = core::result::Result<T, Error>;

/// Categories of failure an implementation may report. The contract
/// avoids being prescriptive about the underlying hardware error — most
/// callers care about which *class* of failure happened.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// The bound hardware (TPM/YubiKey/SE) is not present or
    /// unreachable. Implementations should return this rather than
    /// panicking when the device is unplugged or PCRs don't match.
    #[error("trust anchor unavailable: {0}")]
    AnchorUnavailable(String),

    /// The provided ciphertext / signature / quote did not verify.
    /// Generic so the implementation isn't forced to disclose *why*
    /// (which can be a side channel).
    #[error("verification failed")]
    VerificationFailed,

    /// The caller asked for an operation the anchor doesn't support
    /// (e.g. asking a YubiKey-only anchor for a TPM quote).
    #[error("operation not supported: {0}")]
    Unsupported(String),

    /// Something else. Implementations may wrap any hardware-specific
    /// error here with a short human-readable summary.
    #[error("{0}")]
    Other(String),
}

impl Error {
    /// Convenience constructor for [`Error::Other`].
    pub fn other(msg: impl Into<String>) -> Self {
        Self::Other(msg.into())
    }
}

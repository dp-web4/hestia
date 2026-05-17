//! Core error types for hestia-core.

use std::path::PathBuf;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoreError {
    #[error("I/O error on {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },

    #[error("vault file not found at {0} (run `hestia init` first)")]
    VaultNotFound(PathBuf),

    #[error("vault file already exists at {0} (use --force to overwrite)")]
    VaultAlreadyExists(PathBuf),

    #[error("vault file at {path} is corrupted: {reason}", path = path.display())]
    VaultCorrupted { path: PathBuf, reason: String },

    #[error("decryption failed (wrong passphrase or tampered vault)")]
    DecryptionFailed,

    #[error("encryption failed: {0}")]
    EncryptionFailed(String),

    #[error("key derivation failed: {0}")]
    KeyDerivation(String),

    #[error("credential '{0}' not found in vault")]
    CredentialNotFound(String),

    #[error("credential '{0}' already exists in vault (use --force to overwrite)")]
    CredentialAlreadyExists(String),

    #[error("policy preset '{0}' is not built-in (expected one of: permissive, safety, strict, audit-only)")]
    InvalidPreset(String),

    #[error("invalid passphrase: {0}")]
    InvalidPassphrase(&'static str),

    #[error("serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("HOME directory not set")]
    NoHomeDirectory,
}

pub type Result<T> = std::result::Result<T, CoreError>;

impl CoreError {
    pub fn io(path: impl Into<PathBuf>, source: std::io::Error) -> Self {
        CoreError::Io {
            path: path.into(),
            source,
        }
    }
}

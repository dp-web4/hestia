//! # Hardbound
//!
//! Public trait surface for the hardware-bound enterprise trust tier of
//! Web4. Hardbound implementations anchor identity, vault keys, witness
//! chain signatures, and policy decisions in hardware (TPM 2.0,
//! YubiKey, Secure Enclave, HSM, etc.).
//!
//! This crate is **the contract**, not the implementation. The
//! reference closed-source implementation lives at
//! `https://metalinxx.io`. Any compatible implementation that
//! satisfies these traits can plug into the [Hestia][hestia] daemon at
//! the hardware-trust extension point.
//!
//! ## Four primitives
//!
//! | Trait | Replaces in consumer Hestia |
//! |---|---|
//! | [`TrustedKeyProvider`] | software-derived sovereign LCT |
//! | [`SealedVault`] | passphrase-derived AEAD key |
//! | [`AttestationSigner`] | Phase-1 placeholder signer LCT |
//! | [`OversightPolicy`] | default-allow stub |
//!
//! See `https://github.com/dp-web4/hestia/blob/main/demo/enterprise/README.md`
//! for the architectural map and the rationale behind each replacement.
//!
//! ## Status
//!
//! `0.0.1` — initial contract. Trait shapes may shift before `0.1.0`.
//! Implementations should pin a minor version and watch the changelog.
//!
//! [hestia]: https://github.com/dp-web4/hestia

#![cfg_attr(docsrs, feature(doc_cfg))]
#![deny(missing_docs)]

mod attestation;
mod error;
mod policy;
mod sealed_vault;
mod trusted_key;

pub use attestation::{Attestation, AttestationSigner};
pub use error::{Error, Result};
pub use policy::{OversightPolicy, PolicyAction, PolicyDecision};
pub use sealed_vault::SealedVault;
pub use trusted_key::TrustedKeyProvider;

/// Crate version, for runtime banner messages.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

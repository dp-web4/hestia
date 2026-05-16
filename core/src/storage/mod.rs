//! Persistence backends for the Hestia daemon.
//!
//! - `chain` — SQLite-backed hash-linked witness chain
//! - `trust` — wraps the `web4-trust-core` FileStore for per-entity T3/V3

pub mod chain;
pub mod trust;

pub use chain::{ChainEntry, SqliteChainStore};
pub use trust::TrustStore;

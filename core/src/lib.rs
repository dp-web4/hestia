//! hestia-core — local-first Web4 trust layer for AI agents.
//!
//! See `docs/ARCHITECTURE.md` in the repo root for the technical shape.
//!
//! Phase 1 scope:
//! - **Vault**: ChaCha20-Poly1305 encrypted credential storage (this session)
//! - **MCP server**: rmcp-backed server exposing the surface in ADR-0005 (next)
//! - **Society state**: Web4 society with witness chain + trust evolution (after that)

pub mod callback;
pub mod constellation;
pub mod delegation;
pub mod error;
pub mod hub;
pub mod orchestrators;
pub mod plugin;
pub mod policy;
pub mod profile;
pub mod reputation;
pub mod role_registry;
pub mod server;
pub mod storage;
pub mod tui;
pub mod vault;
pub mod witness_act;

pub use constellation::ConstellationStore;
pub use delegation::DelegationStore;
pub use profile::ProfileStore;
pub use error::{CoreError, Result};
pub use hub::{HubClient, HubStore};
pub use plugin::PluginRegistry;
pub use vault::{Vault, VaultEntry};
